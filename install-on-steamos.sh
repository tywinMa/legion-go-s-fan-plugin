#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

[[ $(id -u) == 0 ]] || fail 'Run with sudo.'
[[ $(cat /sys/class/dmi/id/sys_vendor) == LENOVO &&
   $(cat /sys/class/dmi/id/product_name) == 83Q2 &&
   $(cat /sys/class/dmi/id/bios_version) == QCCN26WW ]] ||
    fail 'This release requires Lenovo Legion Go S (83Q2), BIOS QCCN26WW.'

mod=legion_go_s_fan
for file in "$mod.ko" plugin.json package.json main.py dist/index.js; do
    [[ -f "$file" ]] || fail "Missing package file: $file"
done
kernel=$(uname -r)
vermagic=$(modinfo -F vermagic "./$mod.ko")
[[ ${vermagic%% *} == "$kernel" ]] ||
    fail "Incompatible SteamOS kernel: $kernel. Driver requires ${vermagic%% *}."

homebrew=/home/deck/homebrew
plugin=$homebrew/plugins/legion-go-s-fan
driver_dir=/etc/legion-go-s-fan
driver=$driver_dir/$mod.ko
service=legion-go-s-fan.service
unit=/etc/systemd/system/$service
[[ -d "$homebrew/plugins" ]] && systemctl is-active --quiet plugin_loader.service ||
    fail 'Install and start Decky Loader before installing this plugin.'

if [[ -f "$driver" && -f "$unit" && -f "$plugin/plugin.json" ]]; then
    exec bash ./upgrade.sh
fi
for path in "$driver_dir" "$unit" "$plugin" "/sys/module/$mod"; do
    [[ ! -e "$path" && ! -L "$path" ]] ||
        fail "Found a partial or conflicting installation at $path."
done

stage=$(mktemp -d "$homebrew/.legion-fan-install.XXXXXX")
plugin_installed=false
rollback() {
    status=$?
    trap - EXIT
    rm -rf -- "$stage"
    if (( status )); then
        if "$plugin_installed"; then
            rm -f -- "$plugin"/{plugin.json,package.json,main.py,dist/index.js}
            rmdir -- "$plugin/dist" "$plugin" 2>/dev/null || true
        fi
        systemctl disable --now "$service" >/dev/null 2>&1 || true
        rm -f -- "$unit" "$driver"
        rmdir -- "$driver_dir" 2>/dev/null || true
        systemctl daemon-reload || true
        if "$plugin_installed"; then
            systemctl restart plugin_loader.service || true
        fi
    fi
    exit "$status"
}
trap rollback EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

install -d -m 0755 "$stage/legion-go-s-fan/dist" "$driver_dir"
install -m 0644 plugin.json package.json main.py "$stage/legion-go-s-fan/"
install -m 0644 dist/index.js "$stage/legion-go-s-fan/dist/"
install -m 0644 "./$mod.ko" "$driver"
cat > "$unit" <<UNIT
[Unit]
Description=Legion Go S fan control driver
ConditionKernelVersion=$kernel
Before=plugin_loader.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/usr/bin/modprobe wmi
ExecStart=/usr/bin/insmod $driver
ExecStop=/usr/bin/rmmod $mod

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl start "$service"
shopt -s nullglob
fan_nodes=(/sys/bus/wmi/devices/92549549-4BDE-4F06-AC04-CE8BF898DBAA-*/legion_rpm)
[[ ${#fan_nodes[@]} == 1 ]] || fail 'The driver did not expose exactly one fan.'
node=${fan_nodes[0]%/*}
rpm=$(cat "${fan_nodes[0]}")
[[ "$rpm" =~ ^[0-9]+$ && -e "$node/legion_stop" &&
   $(cat "$node/legion_override") == 0 ]] ||
    fail 'The fan driver did not report a valid RPM in firmware mode.'

systemctl enable "$service"
mv -T -- "$stage/legion-go-s-fan" "$plugin"
plugin_installed=true
systemctl restart plugin_loader.service
systemctl is-active --quiet "$service"
systemctl is-active --quiet plugin_loader.service
printf 'Legion Go S Fan installed. Firmware fan speed: %s RPM. Open Decky in Gaming Mode.\n' "$rpm"

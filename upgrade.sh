#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
[[ $(id -u) == 0 && $(cat /sys/class/dmi/id/product_name) == 83Q2 &&
   $(cat /sys/class/dmi/id/bios_version) == QCCN26WW ]]
[[ $(modinfo -F vermagic ./legion_go_s_fan.ko | cut -d ' ' -f1) == "$(uname -r)" ]]
plugin=/home/deck/homebrew/plugins/legion-go-s-fan
driver=/etc/legion-go-s-fan/legion_go_s_fan.ko
node=/sys/bus/wmi/devices/92549549-4BDE-4F06-AC04-CE8BF898DBAA-1
[[ -f "$driver" && -d "$plugin/dist" ]]
backup=$(mktemp -d)
cp -a "$driver" "$plugin" "$backup"
rollback() {
  status=$?
  if (( status )); then
    systemctl stop plugin_loader legion-go-s-fan || true
    install -m 0644 "$backup/legion_go_s_fan.ko" "$driver"
    cp -a "$backup/legion-go-s-fan/." "$plugin/"
    systemctl start legion-go-s-fan plugin_loader
  fi
  rm -rf -- "$backup"
  exit "$status"
}
trap rollback EXIT
trap 'exit 130' INT TERM
systemctl stop plugin_loader
systemctl stop legion-go-s-fan
install -m 0644 ./legion_go_s_fan.ko "$driver"
systemctl start legion-go-s-fan
[[ $(cat "$node/legion_override") == 0 ]]
if [[ ${1:-} == --verify-stop ]]; then
  /usr/bin/python3 verify-stop.py
elif [[ ${1:-} == --verify ]]; then
  /usr/bin/python3 verify-control.py
fi
install -m 0644 main.py package.json plugin.json "$plugin/"
install -m 0644 dist/index.js "$plugin/dist/"
systemctl start plugin_loader
systemctl is-active legion-go-s-fan plugin_loader
echo 'Legion Go S Fan updated.'

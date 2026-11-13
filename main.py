import asyncio
import json
import os
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic

GUID = "92549549-4BDE-4F06-AC04-CE8BF898DBAA"
HWMON = Path("/sys/class/hwmon")
MODULE = "legion_go_s_fan"
LEGACY_SERVICE = "legion-go-s-fan.service"
DMI = Path("/sys/class/dmi/id")
MIN_RPM = 1800
MAX_RPM = 4200
DEFAULT = [[35, 45], [55, 60], [70, 85], [80, 100]]


def validate(points):
    if not isinstance(points, list) or not 2 <= len(points) <= 10:
        raise ValueError("需要 2–10 个节点。")
    previous_temp, previous_duty = 9, 0
    for point in points:
        if (not isinstance(point, list) or len(point) != 2
                or any(type(value) is not int for value in point)):
            raise ValueError("温度和转速必须为整数。")
        temp, duty = point
        if not previous_temp < temp <= 100 or not previous_duty <= duty <= 100:
            raise ValueError("温度须在 10–100°C 内递增，转速须在 0–100% 内且不能下降。")
        previous_temp, previous_duty = temp, duty


def target_rpm(points, temp):
    if temp <= points[0][0]:
        duty = points[0][1]
    else:
        duty = points[-1][1]
        for (ta, pa), (tb, pb) in zip(points, points[1:]):
            if temp <= tb:
                duty = pa + (pb - pa) * (temp - ta) / (tb - ta)
                break
    if duty == 0:
        return 0
    return max(MIN_RPM, round(duty * MAX_RPM / 100))


def sensor_value(path):
    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return None


def temperature():
    for chip in HWMON.glob("hwmon*"):
        try:
            if (chip / "name").read_text().strip() != "k10temp":
                continue
            for label in chip.glob("temp*_label"):
                if label.read_text().strip() == "Tctl":
                    reading = sensor_value(label.with_name(label.name.replace("_label", "_input")))
                    if reading is not None and 0 < reading < 125000:
                        return round(reading / 1000, 1)
        except OSError:
            continue
    return None


def driver_path():
    devices = list(Path("/sys/bus/wmi/devices").glob(GUID + "-*/legion_rpm"))
    return devices[0].parent if len(devices) == 1 else None


def driver_command(*args):
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise OSError(result.stderr.strip() or f"{args[0]} exited with status {result.returncode}")
    return result.stdout.strip()


class Plugin:
    async def _main(self):
        self.lock = asyncio.Lock()
        self.file = Path(os.environ["DECKY_PLUGIN_SETTINGS_DIR"]) / "fan-curve.json"
        self.points, self.enabled = self._load()
        self.active = False
        self.target = None
        self.spinup_deadline = 0
        self.error = None
        self.driver_error = None
        self.loaded_module = False
        async with self.lock:
            try:
                await asyncio.to_thread(self._load_driver)
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.driver_error = f"风扇驱动无法加载：{exc}"
        self.task = asyncio.create_task(self._run())

    def _load_driver(self):
        plugin_dir = os.environ.get("DECKY_PLUGIN_DIR")
        module_file = Path(plugin_dir) / (MODULE + ".ko") if plugin_dir else None
        if module_file is None or not module_file.is_file():
            # Source checkouts and older script-based installations use the system service.
            return
        expected = {"sys_vendor": "LENOVO", "product_name": "83Q2", "bios_version": "QCCN26WW"}
        if any((DMI / name).read_text().strip() != value for name, value in expected.items()):
            raise OSError("此版本需要 Legion Go S（83Q2）和 BIOS QCCN26WW。")
        vermagic = driver_command("/usr/bin/modinfo", "-F", "vermagic", str(module_file))
        if vermagic.partition(" ")[0] != os.uname().release:
            raise OSError(f"当前 SteamOS 内核不兼容，驱动需要 {vermagic.partition(' ')[0]}。")
        driver_command("/usr/bin/modprobe", "wmi")

        legacy_unit = Path("/etc/systemd/system") / LEGACY_SERVICE
        legacy = legacy_unit.is_file() and Path("/etc/legion-go-s-fan", module_file.name).is_file()
        legacy_active = legacy and Path("/sys/module", MODULE).is_dir()
        if legacy_active:
            driver_command("/usr/bin/systemctl", "stop", LEGACY_SERVICE)
        try:
            driver_command("/usr/bin/insmod", str(module_file))
            self.loaded_module = True
            path = driver_path()
            if (path is None or sensor_value(path / "legion_rpm") is None
                    or not (path / "legion_stop").exists()):
                raise OSError("未检测到可用的风扇控制接口。")
            if legacy_active:
                driver_command("/usr/bin/systemctl", "disable", LEGACY_SERVICE)
        except (OSError, subprocess.TimeoutExpired):
            if self.loaded_module:
                self._remove_driver()
            if legacy_active:
                driver_command("/usr/bin/systemctl", "start", LEGACY_SERVICE)
            raise

    def _remove_driver(self):
        driver_command("/usr/bin/rmmod", MODULE)
        self.loaded_module = False

    def _load(self):
        try:
            settings = json.loads(self.file.read_text())
            points = settings["points"]
            validate(points)
            # Older versions only saved a curve after successfully applying it.
            return points, settings.get("enabled", True) is True
        except (OSError, ValueError, KeyError, TypeError):
            return DEFAULT, False

    def _save(self, points, enabled):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", dir=self.file.parent, delete=False) as stream:
            tmp = Path(stream.name)
            try:
                json.dump({"points": points, "enabled": enabled}, stream)
                stream.flush()
                os.fsync(stream.fileno())
                if os.geteuid() == 0:
                    owner = self.file.parent.stat()
                    os.fchown(stream.fileno(), owner.st_uid, owner.st_gid)
                tmp.replace(self.file)
            finally:
                tmp.unlink(missing_ok=True)

    def _release(self):
        self.active = False
        self.target = None
        path = driver_path()
        if path and (path / "legion_target").exists():
            (path / "legion_target").write_text("0\n")

    def _control(self, points):
        path = driver_path()
        temp = temperature()
        rpm = sensor_value(path / "legion_rpm") if path else None
        if not path or temp is None or rpm is None:
            raise OSError("无法读取风扇或 CPU 温度，已停止接管。")
        desired = target_rpm(points, temp)
        if desired == 0:
            (path / "legion_stop").write_text("1\n")
        else:
            now = monotonic()
            if self.target in (None, 0):
                self.spinup_deadline = now + 6
            if rpm < 700 and now >= self.spinup_deadline:
                raise OSError("风扇未能起转，已交回固件。")
            (path / "legion_target").write_text(f"{desired}\n")
        if sensor_value(path / "legion_override") != 1:
            raise OSError("驱动未确认接管风扇。")
        self.target = desired

    async def _run(self):
        while True:
            async with self.lock:
                if self.enabled and self.driver_error is None:
                    try:
                        await asyncio.to_thread(self._control, self.points)
                    except OSError as exc:
                        await asyncio.to_thread(self._handle_fault, exc)
                    else:
                        self.active = True
                        self.error = None
            await asyncio.sleep(2)

    def _handle_fault(self, exc):
        self.error = str(exc)
        try:
            self._release()
        except OSError:
            self.error += " 驱动正在重试交回控制。"

    async def _unload(self):
        async with self.lock:
            if hasattr(self, "task"):
                self.task.cancel()
            try:
                if self.driver_error is None:
                    await asyncio.to_thread(self._release)
            finally:
                if self.loaded_module:
                    await asyncio.to_thread(self._remove_driver)

    def _reading(self):
        path = driver_path()
        rpm = sensor_value(path / "legion_rpm") if path else None
        override = sensor_value(path / "legion_override") if path else None
        return {"temperature": temperature(), "rpm": rpm, "target": self.target,
                "active": self.active and override == 1, "error": self.error,
                "releasing": not self.active and override == 1, "enabled": self.enabled}

    def _state(self):
        path = driver_path()
        target = path / "legion_target" if path else None
        available = (self.driver_error is None and target is not None and os.access(target, os.W_OK)
                     and os.access(path / "legion_stop", os.W_OK))
        if self.driver_error is not None:
            reason = self.driver_error
        elif available:
            reason = None
        elif target is not None and target.exists():
            reason = "当前风扇驱动不支持停转或 Decky 无写入权限。请更新驱动。"
        else:
            reason = "风扇驱动未加载。"
        return {**self._reading(), "available": available, "reason": reason, "points": self.points,
                "minRpm": MIN_RPM, "maxRpm": MAX_RPM}

    async def get_state(self):
        async with self.lock:
            return await asyncio.to_thread(self._state)

    async def get_telemetry(self):
        async with self.lock:
            return await asyncio.to_thread(self._reading)

    def _apply(self, points):
        if self.driver_error:
            raise OSError(self.driver_error)
        validate(points)
        self.error = None
        try:
            self._control(points)
            self._save(points, True)
        except OSError as exc:
            self._handle_fault(exc)
            raise
        self.points = points
        self.enabled = True
        self.active = True
        return self._state()

    async def apply_curve(self, points):
        async with self.lock:
            return await asyncio.to_thread(self._apply, points)

    def _restore(self):
        self._save(self.points, False)
        self.enabled = False
        self.error = None
        if self.driver_error is None:
            self._release()
        return self._state()

    async def restore_curve(self):
        async with self.lock:
            return await asyncio.to_thread(self._restore)

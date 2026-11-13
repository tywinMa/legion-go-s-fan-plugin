import asyncio
import os
import tempfile
from pathlib import Path

import main


async def verify():
    real_temperature = main.temperature
    driver = main.driver_path()
    if driver is None:
        raise RuntimeError("风扇驱动未加载。")
    for _ in range(30):
        temp = real_temperature()
        if temp is not None and temp <= 50:
            break
        await asyncio.sleep(1)
    else:
        raise RuntimeError(f"停转测试需要在空闲且 CPU 不高于 50°C 时运行，当前温度 {temp}。")

    async def observe(predicate, description):
        for _ in range(12):
            reading = await plugin.get_telemetry()
            print(f"{description}: {reading}", flush=True)
            if reading["active"] and predicate(reading["rpm"]):
                return
            actual = real_temperature()
            if actual is None or actual >= 60:
                raise RuntimeError("测试期间 CPU 温度超过限制。")
            await asyncio.sleep(1)
        raise RuntimeError(f"{description}未在规定时间内达到。")

    plugin = main.Plugin()
    await plugin._main()
    try:
        points = [[60, 0], [80, 60], [90, 100]]
        state = await plugin.apply_curve(points)
        assert state["active"] and state["target"] == 0
        await observe(lambda rpm: rpm == 0, "0% 停转")

        # Exercise the rising edge of the same curve without heating the device.
        main.temperature = lambda: 61
        await observe(lambda rpm: rpm is not None and rpm >= 1500, "重新起转")
        main.temperature = real_temperature
        await observe(lambda rpm: rpm == 0, "再次停转")
        auto = await plugin.restore_curve()
        assert not auto["active"] and not auto["releasing"]
        assert (driver / "legion_override").read_text().strip() == "0"
        print("停转、起转和恢复固件控制均已验证。", flush=True)
    finally:
        main.temperature = real_temperature
        await plugin._unload()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        os.environ["DECKY_PLUGIN_SETTINGS_DIR"] = directory
        asyncio.run(verify())

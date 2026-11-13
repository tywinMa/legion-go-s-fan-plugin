import asyncio
import tempfile

import main


async def verify():
    plugin = main.Plugin()
    await plugin._main()
    baseline = await plugin.get_telemetry()
    print("Firmware baseline:", baseline, flush=True)
    if baseline["temperature"] is None or baseline["temperature"] >= 75:
        raise RuntimeError("Let the device cool below 75°C before this test.")
    if baseline["rpm"] is None or not 700 <= baseline["rpm"] <= 3550:
        raise RuntimeError("Wait for the firmware fan speed to settle below 3550 RPM.")
    try:
        applied = await plugin.apply_curve([[40, 100], [85, 100]])
        assert applied["active"] and applied["target"] == 4200
        peak = baseline["rpm"]
        for _ in range(6):
            await asyncio.sleep(2)
            sample = await plugin.get_telemetry()
            print("Curve sample:", sample, flush=True)
            assert sample["active"] and sample["target"] == 4200
            if sample["rpm"] is not None:
                peak = max(peak, sample["rpm"])
        if peak < max(3750, baseline["rpm"] + 350):
            raise RuntimeError(f"Fan response too small: {peak} RPM")
    finally:
        restored = await plugin.restore_curve()
        assert not restored["active"] and not restored["releasing"]
        print("Firmware control restored:", restored, flush=True)
        await plugin._unload()


if __name__ == "__main__":
    import os
    with tempfile.TemporaryDirectory() as directory:
        os.environ["DECKY_PLUGIN_SETTINGS_DIR"] = directory
        asyncio.run(verify())

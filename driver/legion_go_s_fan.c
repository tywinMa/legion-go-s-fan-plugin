// SPDX-License-Identifier: GPL-3.0-or-later
/* Fan Method WMI protocol: https://lkml.iu.edu/2608.2/11177.html */
#include <linux/device.h>
#include <linux/dmi.h>
#include <linux/module.h>
#include <linux/pm.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/unaligned.h>
#include <linux/wmi.h>
#include <linux/io.h>
#include <linux/ioport.h>
#include <linux/workqueue.h>

#define OTHER_GUID "DC2A8805-3A8C-41BA-A6F7-092E0089CD3B"
#define FAN_GUID "92549549-4BDE-4F06-AC04-CE8BF898DBAA"
static DEFINE_MUTEX(table_lock);

static int read_wmi_rpm(void)
{
	u8 feature[] = { 1, 0, 3, 4 };
	struct acpi_buffer in = { .pointer = feature, .length = sizeof(feature) };
	struct acpi_buffer out = { .length = ACPI_ALLOCATE_BUFFER };
	union acpi_object *result;
	u32 rpm = U32_MAX;

	if (ACPI_SUCCESS(wmi_evaluate_method(OTHER_GUID, 0, 0x11, &in, &out))) {
		result = out.pointer;
		if (result && result->type == ACPI_TYPE_BUFFER &&
		    result->buffer.length == 4)
			rpm = get_unaligned_le32(result->buffer.pointer);
	}
	kfree(out.pointer);
	return rpm <= 10000 ? (int)rpm : -EIO;
}

static ssize_t legion_rpm_show(struct device *dev, struct device_attribute *attr,
			       char *buf)
{
	int rpm;

	guard(mutex)(&table_lock);
	rpm = read_wmi_rpm();
	return rpm < 0 ? rpm : sysfs_emit(buf, "%d\n", rpm);
}
static DEVICE_ATTR_RO(legion_rpm);

/*
 * Lenovo Go S Super I/O transport. Verify the live tachometer against the
 * independent firmware WMI reading before attempting to claim the fan.
 * Reference: Hooandee/panel-de-control, fans/legion_ec.py.
 */
#define EC_INDEX 0x4e
#define EC_DATA 0x4f
#define EC_RPM 0xc6c0
#define EC_TARGET 0xc6c8
#define RPM_CAP 4200
#define RPM_FLOOR 1800
/* EC target zero releases ownership. A nonzero sub-spin target parks the fan. */
#define EC_STOP_TARGET 1
static struct delayed_work release_work;
static bool owned;
static unsigned long expires;
static bool suspending;

static void ec_index_write(u8 index, u8 value)
{
	outb(0x2e, EC_INDEX);
	outb(index, EC_DATA);
	outb(0x2f, EC_INDEX);
	outb(value, EC_DATA);
}

static void ec_select(u16 address)
{
	ec_index_write(0x11, address >> 8);
	ec_index_write(0x10, address & 0xff);
	outb(0x2e, EC_INDEX);
	outb(0x12, EC_DATA);
	outb(0x2f, EC_INDEX);
}

static u8 sio_read(u16 address)
{
	ec_select(address);
	return inb(EC_DATA);
}

static void sio_write(u16 address, u8 value)
{
	ec_select(address);
	outb(value, EC_DATA);
}

static int ec_read_word(u16 address)
{
	u8 high, low;
	int attempt;

	for (attempt = 0; attempt < 3; attempt++) {
		high = sio_read(address + 1);
		low = sio_read(address);
		if (high == sio_read(address + 1))
			return (high << 8) | low;
	}
	return -EIO;
}

static int ec_override(unsigned int rpm)
{
	int tach, firmware_rpm = 0, rc;

	if (rpm && !owned) {
		firmware_rpm = read_wmi_rpm();
		if (firmware_rpm < 0 || firmware_rpm > 6000)
			return -EAGAIN;
	}
	if (!request_muxed_region(EC_INDEX, 2, KBUILD_MODNAME))
		return -EBUSY;
	if (rpm && !owned) {
		tach = ec_read_word(EC_RPM);
		if (tach < 0 || abs(tach - firmware_rpm) > 250 ||
		    ec_read_word(EC_TARGET) != 0) {
			rc = -ENODEV;
			goto out;
		}
	}
	if (rpm) {
		/* Track ownership before the first hardware write. */
		owned = true;
		if (rpm == EC_STOP_TARGET) {
			sio_write(EC_TARGET, rpm);
			sio_write(EC_TARGET + 1, 0);
		} else {
			sio_write(EC_TARGET + 1, rpm >> 8);
			sio_write(EC_TARGET, rpm & 0xff);
		}
	} else {
		sio_write(EC_TARGET, 0);
		sio_write(EC_TARGET + 1, 0);
	}
	rc = ec_read_word(EC_TARGET) == rpm ? 0 : -EIO;
out:
	release_region(EC_INDEX, 2);
	return rc;
}

static void release_target(struct work_struct *work)
{
	guard(mutex)(&table_lock);
	if (owned) {
		if (time_before(jiffies, expires)) {
			mod_delayed_work(system_wq, &release_work, expires - jiffies);
			return;
		}
		if (ec_override(0))
			mod_delayed_work(system_wq, &release_work, HZ);
		else
			owned = false;
	}
}

static ssize_t store_target(unsigned int rpm, size_t count)
{
	int rc;

	guard(mutex)(&table_lock);
	if (rpm && suspending)
		return -EBUSY;
	if (!rpm && !owned)
		return count;
	rc = ec_override(rpm);
	if (!rc && !rpm)
		owned = false;
	if (owned) {
		unsigned long delay = rc ? HZ : 6 * HZ;

		expires = jiffies + delay;
		mod_delayed_work(system_wq, &release_work, delay);
	}
	return rc ? rc : count;
}

static ssize_t legion_target_store(struct device *dev, struct device_attribute *attr,
				   const char *buf, size_t count)
{
	unsigned int rpm;

	if (kstrtouint(buf, 10, &rpm) || (rpm && (rpm < RPM_FLOOR || rpm > RPM_CAP)))
		return -EINVAL;
	return store_target(rpm, count);
}
static DEVICE_ATTR_WO(legion_target);

static ssize_t legion_stop_store(struct device *dev, struct device_attribute *attr,
				 const char *buf, size_t count)
{
	if (!sysfs_streq(buf, "1"))
		return -EINVAL;
	return store_target(EC_STOP_TARGET, count);
}
static DEVICE_ATTR_WO(legion_stop);

static ssize_t legion_override_show(struct device *dev, struct device_attribute *attr,
				    char *buf)
{
	guard(mutex)(&table_lock);
	return sysfs_emit(buf, "%u\n", owned);
}
static DEVICE_ATTR_RO(legion_override);

static struct attribute *fan_attrs[] = {
	&dev_attr_legion_rpm.attr,
	&dev_attr_legion_target.attr,
	&dev_attr_legion_stop.attr,
	&dev_attr_legion_override.attr,
	NULL,
};
ATTRIBUTE_GROUPS(fan);

static int fan_probe(struct wmi_device *dev, const void *ctx)
{
	const char *vendor = dmi_get_system_info(DMI_SYS_VENDOR);
	const char *product = dmi_get_system_info(DMI_PRODUCT_NAME);
	const char *bios = dmi_get_system_info(DMI_BIOS_VERSION);

	if (!vendor || strcmp(vendor, "LENOVO") || !product ||
	    strcmp(product, "83Q2") || !bios || strcmp(bios, "QCCN26WW"))
		return -ENODEV;
	INIT_DELAYED_WORK(&release_work, release_target);
	return device_add_groups(&dev->dev, fan_groups);
}

static void fan_remove(struct wmi_device *dev)
{
	device_remove_groups(&dev->dev, fan_groups);
	cancel_delayed_work_sync(&release_work);
	if (owned) {
		ec_override(0);
		owned = false;
	}
}

static int fan_suspend(struct device *dev)
{
	guard(mutex)(&table_lock);
	if (owned) {
		int rc = ec_override(0);

		if (rc)
			return rc;
		owned = false;
	}
	suspending = true;
	return 0;
}

static int fan_resume(struct device *dev)
{
	guard(mutex)(&table_lock);
	suspending = false;
	return 0;
}

static DEFINE_SIMPLE_DEV_PM_OPS(fan_pm, fan_suspend, fan_resume);

static const struct wmi_device_id fan_ids[] = {
	{ FAN_GUID, NULL },
	{}
};
MODULE_DEVICE_TABLE(wmi, fan_ids);

static struct wmi_driver fan_driver = {
	.driver.name = "legion_go_s_fan",
	.driver.pm = pm_sleep_ptr(&fan_pm),
	.id_table = fan_ids,
	.probe = fan_probe,
	.remove = fan_remove,
};
module_wmi_driver(fan_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Legion Go S EC fan control");

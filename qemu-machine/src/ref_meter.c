/* IC9700 external reference measurement latch, experimental behavioural model.
 * SPDX-License-Identifier: GPL-2.0-or-later
 * Firmware200fc958 reads040007e0; low16=signed error, bits17:16=sample epoch.
 * This is not a physical FPGA/PLL model. No Hz/count or trim-law claim.
 * Optional ideal10MHz input produces zero error with time-based fresh samples;
 * absent input produces the invalid sentinel observed in stock firmware.
 */
#include "qemu/osdep.h"
#include "hw/core/sysbus.h"
#include "hw/core/qdev-properties.h"
#include "qemu/module.h"
#include "qemu/timer.h"
#include "qom/object.h"
#define TYPE_IC9700_REF_METER "ic9700-reference-meter"
OBJECT_DECLARE_SIMPLE_TYPE(IC9700RefMeter, IC9700_REF_METER)
struct IC9700RefMeter {
    SysBusDevice parent_obj;
    MemoryRegion iomem;
    QEMUTimer *sample_timer;
    bool present;
    uint32_t epoch;
    uint32_t committed_tag;
    uint32_t commit_value;
    uint32_t version_word;
    uint32_t error_count;
    uint64_t period_ns;
};
static uint64_t meter_read(void *opaque, hwaddr off, unsigned size)
{
    IC9700RefMeter *s=opaque;
    uint32_t word=0;
    hwaddr reg=off & ~3ULL;
    if (reg==0x3e0) word=((s->epoch & 3)<<16) | (s->present ? s->error_count & 0xffff : 0x8000);
    else if (reg==0x33c) word=s->commit_value;
    else if (reg==0x3e8) word=s->committed_tag;
    else if (reg==0x3f0) word=s->version_word;
    else if (reg==0x3ec) word=0x6d6f6349; /* Firmware-verified bank identity Icom. */
    return (word >> ((off&3)*8)) & (size==4 ? UINT32_MAX : (1u << (size*8))-1);
}
static void meter_write(void *opaque, hwaddr off, uint64_t value, unsigned size)
{
    IC9700RefMeter *s=opaque;
    /* Immediate configuration application: echo commit low nibble, independent
     * from measurement epoch. Other bank registers remain unimplemented. */
    if ((off & ~3ULL)==0x33c && (off&3)==0) {
        s->commit_value=value;
        s->committed_tag=value & 15;
    }
}
static const MemoryRegionOps meter_ops={
    .read=meter_read,.write=meter_write,.endianness=DEVICE_LITTLE_ENDIAN,
    .valid.min_access_size=1,.valid.max_access_size=4,
};
static void sample_tick(void *opaque)
{
    IC9700RefMeter *s=opaque;
    s->epoch=(s->epoch+1)&3;
    timer_mod(s->sample_timer,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)+MAX(s->period_ns,1000000ULL));
}
static void meter_reset(DeviceState *dev)
{
    IC9700RefMeter *s=IC9700_REF_METER(dev);
    s->epoch=0;
    s->committed_tag=0;
    s->commit_value=0;
    timer_mod(s->sample_timer,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)+MAX(s->period_ns,1000000ULL));
}
static void meter_init(Object *obj)
{
    IC9700RefMeter *s=IC9700_REF_METER(obj);
    memory_region_init_io(&s->iomem,obj,&meter_ops,s,TYPE_IC9700_REF_METER,0x400);
    sysbus_init_mmio(SYS_BUS_DEVICE(obj),&s->iomem);
    s->sample_timer=timer_new_ns(QEMU_CLOCK_VIRTUAL,sample_tick,s);
}
static const Property meter_props[]={
    DEFINE_PROP_UINT32("version-word",IC9700RefMeter,version_word,0),
    DEFINE_PROP_BOOL("present",IC9700RefMeter,present,false),
    DEFINE_PROP_UINT32("error-count",IC9700RefMeter,error_count,0),
    DEFINE_PROP_UINT64("sample-period-ns",IC9700RefMeter,period_ns,100000000),
};
static void meter_class_init(ObjectClass *oc,const void *data)
{
    DeviceClass *dc=DEVICE_CLASS(oc);
    device_class_set_props(dc,meter_props);
    device_class_set_legacy_reset(dc,meter_reset);
}
static const TypeInfo meter_info={.name=TYPE_IC9700_REF_METER,.parent=TYPE_SYS_BUS_DEVICE,.instance_size=sizeof(IC9700RefMeter),.instance_init=meter_init,.class_init=meter_class_init};
static void meter_register(void){type_register_static(&meter_info);}
type_init(meter_register)

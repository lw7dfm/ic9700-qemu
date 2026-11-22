/* IC9700 experimental RSPI0 controller. GPIO/flash peer NOT identified.
 * SPDX-License-Identifier: GPL-2.0-or-later
 * Controller and optional explicit synthetic cmd00 peer, no real DSP execution.
 * RX defaults to pulled-up MISO (ff) with no slave attached.
 * Timing is approximate; no full hardware pacing or FIFO-overflow model.
 */
#include "qemu/osdep.h"
#include "hw/core/sysbus.h"
#include "hw/core/irq.h"
#include "qemu/module.h"
#include "qom/object.h"
#include "qemu/error-report.h"
#include "rza1h_debug.h"
#define TYPE_IC9700_RSPI0 "ic9700-rspi0"
OBJECT_DECLARE_SIMPLE_TYPE(IC9700Rspi0, IC9700_RSPI0)
struct IC9700Rspi0 {
    SysBusDevice parent_obj;
    MemoryRegion iomem, notify;
    bool peer_enabled;
    uint8_t identity[20], peer_rx[256], tx_frame[46], control;
    unsigned peer_head, peer_count, tx_pos, tx_length;
    uint64_t valid_requests, unknown_requests;
    qemu_irq rx_irq;
    uint8_t regs[0x100];
    uint8_t fifo[8192];
    unsigned head, count;
    uint64_t bytes;
};
/* Experimental cmd00 peer: stateful framing and queued delayed full-duplex RX.
 * Identity is an explicit synthetic fixture, not DSP firmware execution. */
static uint8_t peer_clock(IC9700Rspi0 *s,uint8_t tx) {
    uint8_t rx=0xff;
    if (!s->peer_enabled) return rx;
    if (s->peer_count) {
        rx=s->peer_rx[s->peer_head++];s->peer_count--;
        if (!s->peer_count) s->peer_head=0;
    }
    if (!s->tx_pos) {
        if (tx==0xff || tx==0 || tx>45) return rx;
        s->tx_length=tx;s->tx_frame[0]=tx;s->tx_pos=1;
    } else {
        s->tx_frame[s->tx_pos++]=tx;
        if (s->tx_pos==s->tx_length+1) {
            if (s->valid_requests+s->unknown_requests<64) rza1h_debug("rspi0","peer frame len=%u cmd=%02x term=%02x",s->tx_length,s->tx_frame[1],tx);
            if (tx==0xff && s->tx_frame[1]==0 && s->tx_length==3) {
                s->control=s->tx_frame[2];s->valid_requests++;
                if (!s->peer_count) {
                    s->peer_rx[0]=0x16;s->peer_rx[1]=0;
                    memcpy(s->peer_rx+2,s->identity,20);
                    s->peer_rx[22]=0xff;s->peer_head=0;s->peer_count=23;
                }
            } else s->unknown_requests++;
            s->tx_pos=0;
        }
    }
    return rx;
}
static uint64_t notify_read(void *opaque,hwaddr off,unsigned size) {
    IC9700Rspi0 *s=opaque;
    return off==0 && s->peer_count ? 2 : 0;
}
static void notify_write(void *opaque,hwaddr off,uint64_t value,unsigned size) {}
static const MemoryRegionOps notify_ops={.read=notify_read,.write=notify_write,.endianness=DEVICE_LITTLE_ENDIAN,.valid.min_access_size=1,.valid.max_access_size=2};
static void update_irq(IC9700Rspi0 *s) {
    qemu_set_irq(s->rx_irq, (s->regs[0] & 0x80) && s->count);
}
static uint64_t spi_read(void *opaque, hwaddr off, unsigned size) {
    IC9700Rspi0 *s=opaque; uint64_t v=0;
    if (off==3) return 0x60 | (s->count ? 0x80 : 0); /* SPTEF/TEND, SPRF */
    if (off==4) {
        v=0xff;
        if (s->count) { v=s->fifo[s->head];s->head=(s->head+1)%sizeof(s->fifo);s->count--; }
        update_irq(s);return v;
    }
    if (off+size<=sizeof(s->regs)) memcpy(&v,s->regs+off,size);
    return v;
}
static void spi_write(void *opaque, hwaddr off, uint64_t val,unsigned size) {
    IC9700Rspi0 *s=opaque;
    if (off==4) {
        uint8_t rx=peer_clock(s,val&255);
        if (s->count<sizeof(s->fifo)) { s->fifo[(s->head+s->count)%sizeof(s->fifo)]=rx;s->count++; }
        if (s->bytes++ < 256) rza1h_debug("rspi0", "TX %02x -> RX %02x (synthetic peer=%d)",(unsigned)val&255,rx,s->peer_enabled);
        update_irq(s);return;
    }
    if (off==0x20 && (val&0x40)) {s->head=0;s->count=0;}
    if (off+size<=sizeof(s->regs)) memcpy(s->regs+off,&val,size);
    update_irq(s);
}
static const MemoryRegionOps spi_ops={.read=spi_read,.write=spi_write,.endianness=DEVICE_LITTLE_ENDIAN,.valid.min_access_size=1,.valid.max_access_size=4};
static void spi_reset(DeviceState *dev) {
    IC9700Rspi0 *s=IC9700_RSPI0(dev);memset(s->regs,0,sizeof(s->regs));s->head=s->count=0;s->bytes=0;s->peer_head=s->peer_count=s->tx_pos=s->tx_length=0;s->control=0;s->valid_requests=s->unknown_requests=0;update_irq(s);
}
static void spi_init(Object *obj) {
    IC9700Rspi0 *s=IC9700_RSPI0(obj);SysBusDevice *sd=SYS_BUS_DEVICE(obj);
    memory_region_init_io(&s->iomem,obj,&spi_ops,s,TYPE_IC9700_RSPI0,0x100);
    sysbus_init_mmio(sd,&s->iomem);sysbus_init_irq(sd,&s->rx_irq);
    memory_region_init_io(&s->notify,obj,&notify_ops,s,"ic9700-rspi0-pending",2);
    sysbus_init_mmio(sd,&s->notify);
    const char *path=getenv("IC9700_DV_STATUS_IMAGE");
    if (path) {
        gchar *data=NULL;gsize n=0;
        if (!g_file_get_contents(path,&data,&n,NULL) || n!=20) {
            error_report("IC9700_DV_STATUS_IMAGE must be20bytes");exit(1);
        }
        memcpy(s->identity,data,20);g_free(data);s->peer_enabled=true;
    }
}
static void spi_class_init(ObjectClass *oc,const void *data) {device_class_set_legacy_reset(DEVICE_CLASS(oc),spi_reset);}
static const TypeInfo spi_info={.name=TYPE_IC9700_RSPI0,.parent=TYPE_SYS_BUS_DEVICE,.instance_size=sizeof(IC9700Rspi0),.instance_init=spi_init,.class_init=spi_class_init};
static void spi_register(void){type_register_static(&spi_info);}
type_init(spi_register)

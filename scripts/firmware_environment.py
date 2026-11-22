#!/usr/bin/env python3
"""Synthetic IC-9700 environment derived only from the selected main image.
This is a model fixture, not physical calibration or a real EEPROM dump.
The known v1.50 ROM-pointer layout is checked, never silently guessed.
"""
import struct
BASE=0x20005000

def auxiliary_image(main):
    image=bytearray(b'\xff'*262144)
    def rom(address,size):
        offset=address-BASE
        if size<0 or offset<0 or offset+size>len(main):
            raise ValueError('Selected firmware ROM-template layout is not supported by this model')
        return main[offset:offset+size]
    def word(address):return struct.unpack('<I',rom(address,4))[0]
    def put(logical,data):
        if logical<0 or logical+len(data)>262144:
            raise ValueError('Selected firmware EEPROM-template address is outside the modeled chip')
        for i,value in enumerate(data):
            a=logical+i
            wire=(a&63)+((a>>7)<<6)+(((a>>6)&1)<<17)
            image[wire]=value
    put(0x3fcc0,rom(0x202eff1c,16))
    put(0x3fd00,rom(word(0x200083a4),0xce))
    put(0x3ff80,rom(word(0x20068620),128))
    put(word(0x20068630),rom(word(word(0x2006862c)),16))
    put(word(0x20024480),b'\x07')
    a=0x3a6f0
    image[(a&63)+((a>>7)<<6)+(((a>>6)&1)<<17)]=0xff
    return bytes(image)

def write_inputs(folder,main):
    (folder/'aux-synthetic-invalid.bin').write_bytes(auxiliary_image(main))
    # Compatibility inputs belong to the partial machine model; no external
    # firmware, prepared stock seed, or second DAT is loaded for these peers.
    panel=bytearray(52);panel[3:9]=b'210E00';panel[51]=0x73
    (folder/'panel-stock-flags.bin').write_bytes(panel)
    dv=bytearray(20);dv[8:12]=b'3.62'
    (folder/'dv-compatible.bin').write_bytes(dv)

def candidate_seed_ready(sample):
    # Observe initialization/save completion, not stock tuning values or TX flags.
    # This gate prepares settings, not a certificate of firmware correctness.
    return (sample['initialized']==1 and sample['power_wait']==0
            and sample['journal_active']==0 and sample['writer_busy']==0)

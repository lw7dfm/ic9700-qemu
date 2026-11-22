#!/usr/bin/env python3
"""Regression of seed gate: UI dirty bits are not transmit requests."""
import copy,unittest
from prepare_firmware import seed_ready
class SeedValidation(unittest.TestCase):
 def sample(self):return {'frequencies_hz':[145000000,433000000],'flags':[0,0,0,0],'front_mismatch':0,'front_latched_hex':b'200000'.hex(),'initialized':1,'journal_active':0,'writer_busy':0}
 def test_ready(self):self.assertTrue(seed_ready(self.sample()))
 def test_ui_dirty_is_not_tx(self):
  s=self.sample();s['flags']=[0,8,8,0x40];self.assertTrue(seed_ready(s))
 def test_actual_tx_rejected(self):
  for byte,mask in [(0,0x10),(0,0x20),(0,0x80),(2,0x10),(2,0x20)]:
   s=self.sample();s['flags'][byte]=mask;self.assertFalse(seed_ready(s))
 def test_waits_for_front(self):
  s=self.sample();s['front_mismatch']=1;self.assertFalse(seed_ready(s))
  s=self.sample();s['front_latched_hex']=b'      '.hex();self.assertFalse(seed_ready(s))
 def test_waits_for_init_and_writers(self):
  for key,value in [('initialized',0),('journal_active',1),('writer_busy',1)]:
   s=self.sample();s[key]=value;self.assertFalse(seed_ready(s))
 def test_bad_defaults_rejected(self):
  s=self.sample();s['frequencies_hz']=[0,0];self.assertFalse(seed_ready(s))
if __name__=='__main__':unittest.main()

#!/usr/bin/env python3
"""Synthetic-data regressions only: no Icom firmware is included or required."""
from pathlib import Path
import hashlib,json,struct,tempfile,unittest
from unittest.mock import patch
import experimental_firmware as exp

def literal(data):
    return b''.join(bytes([(1<<len(data[i:i+8]))-1])+data[i:i+8] for i in range(0,len(data),8))
def body(main=b'ARM-test',graphics=b'graphics'):
    a=literal(main);b=literal(graphics)
    return b'\xff'*0x10000+struct.pack('<II',len(a),len(main))+a+struct.pack('<II',len(b),len(graphics))+b

class ExperimentTests(unittest.TestCase):
    def test_decodes_two_bounded_literal_streams(self):
        self.assertEqual(exp.decode_components(body()),(b'ARM-test',b'graphics'))
    def test_rejects_missing_header(self):
        with self.assertRaises(ValueError):exp.decode_components(b'bad')
    def test_rejects_zero_compressed_length(self):
        data=bytearray(body());struct.pack_into('<I',data,0x10000,0)
        with self.assertRaises(ValueError):exp.decode_components(data)
    def test_rejects_compressed_length_outside_domain(self):
        data=bytearray(body());struct.pack_into('<I',data,0x10000,0xffffffff)
        with self.assertRaises(ValueError):exp.decode_components(data)
    def test_rejects_excessive_main_allocation(self):
        data=bytearray(body());struct.pack_into('<I',data,0x10004,exp.MAX_MAIN+1)
        with self.assertRaises(ValueError):exp.decode_components(data)
    def test_rejects_excessive_graphics_allocation(self):
        data=bytearray(body());offset=0x10008+len(literal(b'ARM-test'));struct.pack_into('<I',data,offset+4,exp.MAX_GRAPHICS+1)
        with self.assertRaises(ValueError):exp.decode_components(data)
    def test_rejects_truncated_lzss(self):
        data=b'\xff'*0x10000+struct.pack('<II',1,8)+b'\xff'
        with self.assertRaises(ValueError):exp.decode_components(data)
    def test_sha_pin(self):
        digest=hashlib.sha256(b'candidate').hexdigest()
        self.assertEqual(exp.require_sha(b'candidate',digest.upper()),digest)
        with self.assertRaises(ValueError):exp.require_sha(b'changed',digest)
    def test_requires_complete_sha(self):
        for expected in [None,'','123','x'*64]:
            with self.assertRaises(ValueError):exp.require_sha(b'candidate',expected)
    def test_profiles_are_firmware_scoped(self):
        a=exp.profile_name('a'*64);b=exp.profile_name('b'*64)
        self.assertNotEqual(a,b);self.assertLessEqual(len(a),48)
        self.assertNotEqual(exp.profile_name('a'*64,'same'),exp.profile_name('b'*64,'same'))
    def test_profile_label_validation(self):
        for label in ['../stock','a/b','a'*19,'']:
            with self.assertRaises(ValueError):exp.profile_name('a'*64,label)
    def test_binding_reuses_only_exact_fingerprint(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);name=exp.profile_name('a'*64)
            exp.bind_profile(root,name,'a'*64);exp.bind_profile(root,name,'a'*64)
            path=root/'work/eeprom'/name/'firmware-binding.json'
            data=json.loads(path.read_text());data['input_sha256']='b'*64;path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):exp.bind_profile(root,name,'a'*64)
    def test_cannot_adopt_unbound_existing_state(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);name=exp.profile_name('a'*64);d=root/'work/eeprom'/name;d.mkdir(parents=True);(d/'state.bin').write_bytes(b'existing')
            with self.assertRaises(ValueError):exp.bind_profile(root,name,'a'*64)
    def test_rejects_profile_symlink(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);name=exp.profile_name('a'*64);(root/'work/eeprom').mkdir(parents=True);(root/'other').mkdir();(root/'work/eeprom'/name).symlink_to(root/'other')
            with self.assertRaises(ValueError):exp.bind_profile(root,name,'a'*64)
    def test_rejects_symlink_output_parents_before_writing(self):
        for parent in ['work','work/eeprom']:
            with tempfile.TemporaryDirectory() as t:
                root=Path(t);outside=root/'outside';outside.mkdir()
                target=root/parent;target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(outside)
                with self.assertRaises(ValueError):exp.bind_profile(root,exp.profile_name('a'*64),'a'*64)
                self.assertEqual(list(outside.iterdir()),[])
    def test_stock_cache_cannot_adopt_modified_input_manifest(self):
        import prepare_firmware as stock
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);dat=root/'modified.dat';dat.write_bytes(b'modified')
            generation=root/'work/processed/generation-forged';generation.mkdir(parents=True)
            (root/'work/current.json').write_text(json.dumps({'generation':generation.name}))
            (generation/'PREPARED.json').write_text(json.dumps({'pipeline_version':stock.PIPELINE_VERSION,'original_dat_sha256':stock.sha(dat.read_bytes()),'arm_seed_evidence':{'cold_boot_verified':True},'outputs_sha256':{}}))
            self.assertIsNone(stock.cached(root,dat))
    def test_stock_cache_requires_all_outputs(self):
        import prepare_firmware as stock
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);dat=root/'input.dat';dat.write_bytes(b'fixture')
            generation=root/'work/processed/generation-forged';generation.mkdir(parents=True)
            (root/'work/current.json').write_text(json.dumps({'generation':generation.name}))
            (generation/'PREPARED.json').write_text(json.dumps({'pipeline_version':stock.PIPELINE_VERSION,'original_dat_sha256':stock.DAT_SHA,'arm_seed_evidence':{'cold_boot_verified':True},'outputs_sha256':{}}))
            with patch.object(stock,'sha',return_value=stock.DAT_SHA):self.assertIsNone(stock.cached(root,dat))
    def test_decoder_accepts_only_one_input_argument(self):
        import inspect
        self.assertEqual(list(inspect.signature(exp.decode_candidate).parameters),['raw'])
    def test_rejects_short_dat(self):
        with tempfile.TemporaryDirectory() as t:
            f=Path(t)/'input.dat';f.write_bytes(b'bad')
            with self.assertRaises(ValueError):exp.read_dat(f)
    def test_checks_md5_before_decoding(self):
        raw=exp.MODEL_TAG+b'\0'*(exp.CONTAINER_SIZE-4)
        with patch.object(exp,'derive_key',side_effect=AssertionError('decoder should not run')):
            with self.assertRaisesRegex(ValueError,'MD5'):exp.decode_candidate(raw)
    def test_candidate_seed_gate_does_not_require_stock_frequencies_or_tx_flags(self):
        from firmware_environment import candidate_seed_ready
        sample={'initialized':1,'power_wait':0,'journal_active':0,'writer_busy':0,
                'frequencies_hz':[123000000,456000000],'flags':[0x80,0,0x30,0]}
        self.assertTrue(candidate_seed_ready(sample))
        for key in ['journal_active','writer_busy','power_wait']:
            bad=dict(sample);bad[key]=1;self.assertFalse(candidate_seed_ready(bad))
    def test_candidate_power_pulse_is_not_blocked_by_stock_frequencies(self):
        from prepare_firmware import power_input_needed
        sample={'power_wait':1,'frequencies_hz':[145000000,433000000]}
        self.assertTrue(power_input_needed(sample,strict_stock=False))
        self.assertFalse(power_input_needed(sample,strict_stock=True))
        sample['power_wait']=0
        self.assertFalse(power_input_needed(sample,strict_stock=False))
    def test_invalid_rom_templates_fail_without_other_firmware_fallback(self):
        from firmware_environment import auxiliary_image
        with self.assertRaisesRegex(ValueError,'ROM-template layout'):auxiliary_image(b'not-a-firmware')
    def test_prior_environment_profile_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);digest='a'*64;old='exp-s2-'+digest[:36]
            directory=root/'work/eeprom'/old;directory.mkdir(parents=True)
            (directory/'state.bin').write_bytes(b'prior environment state')
            with self.assertRaises(ValueError):exp.bind_profile(root,old,digest)
            new=exp.profile_name(digest);exp.bind_profile(root,new,digest)
            self.assertNotEqual(old,new)
            self.assertFalse((root/'work/eeprom'/new/'state.bin').exists())
            self.assertEqual((directory/'state.bin').read_bytes(),b'prior environment state')
    def test_prior_pipeline_cache_is_not_reused(self):
        raw=b'fixture';digest=hashlib.sha256(raw).hexdigest()
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);directory=root/'work/experiments'/digest;folder=directory/'generation-legacy';folder.mkdir(parents=True)
            (directory/'current.json').write_text(json.dumps({'generation':folder.name}))
            (folder/'PREPARED.json').write_text(json.dumps({'experimental_pipeline_version':exp.VERSION-1}))
            with patch.object(exp,'read_dat',return_value=raw):
                self.assertIsNone(exp.cached(root,root/'input.dat',digest))
    def test_checks_model_and_geometry(self):
        with self.assertRaisesRegex(ValueError,'geometry'):exp.decode_candidate(b'wrong')

if __name__=='__main__':unittest.main()

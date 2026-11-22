#!/usr/bin/env python3
"""Atomic DAT -> decoded components -> experimental flash/peers -> ARM-created seed.
Never edits input DAT, guest RAM/PC or existing user EEPROM profiles.
"""
from pathlib import Path
import fcntl,hashlib,json,os,shutil,socket,struct,subprocess,tempfile,time,uuid
from vendor.icom_rza1_decode import derive_key,find_start,autokey_decode,lzss_decompress
from control_panel import QMPClient
DAT_SHA='001f34f2263bddebbf4a277d675918f1d68bef4c96537461d1fc495745ba8bb5'
MAIN_SHA='bee593b658d7658c1267ba95a0770f0236621150d830f822910e4bd65cd5e86d'
BODY_SHA='db681194bc985dec88b12d66d8100e6423b01590676ff37dee5f670f46b5bb50'
PIPELINE_VERSION=2
GRAPHICS_SHA='d1c510cc91302974f9dd6f73f14db6ed0e31b01eac4994541725fa15f2876c08'
def sha(data):return hashlib.sha256(data).hexdigest()
def atomic_json(path,data):
 temp=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
 with temp.open('w') as f:json.dump(data,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 os.replace(temp,path)
 fd=os.open(path.parent,os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)
def cached(root,dat):
 try:
  if sha(dat.read_bytes())!=DAT_SHA:return None
  pointer=json.loads((root/'work/current.json').read_text());name=pointer['generation']
  if Path(name).name!=name or not name.startswith('generation-'):return None
  folder=root/'work/processed'/name
  if folder.is_symlink():return None
  m=json.loads((folder/'PREPARED.json').read_text())
  if m['pipeline_version']!=PIPELINE_VERSION or m['original_dat_sha256']!=DAT_SHA:return None
  if not m.get('arm_seed_evidence',{}).get('cold_boot_verified'):return None
  required={'decoded/body.bin','decoded/main.bin','decoded/graphics.bin','decoded/bootstrap.bin','ic9700-flash-stock.bin','ui-ready-seed.bin','panel-stock-flags.bin','dv-compatible.bin'}
  if not required.issubset(m['outputs_sha256']) or (folder/'decoded').is_symlink():return None
  pins={'decoded/body.bin':BODY_SHA,'decoded/main.bin':MAIN_SHA,'decoded/graphics.bin':GRAPHICS_SHA,'decoded/bootstrap.bin':'9b44bb7c52755e430d87fb91201104eab1458fb3243de522ea31f55d780eb290','ic9700-flash-stock.bin':'30d31dd94c7e40d594109a633dc7c053bb374f14041d5b022f1101e2a5f91334'}
  for rel,pinned in pins.items():
   if m['outputs_sha256'].get(rel)!=pinned:return None
  for rel,expected in m['outputs_sha256'].items():
   p=folder/rel
   if Path(rel).is_absolute() or '..' in Path(rel).parts or not p.is_file() or p.is_symlink() or sha(p.read_bytes())!=expected:return None
  return folder,m
 except (OSError,ValueError,KeyError,TypeError):return None

def seed_ready(sample):
 # FA requests/effective TX and FC outputs only; FB/FD are NOT TX flags.
 return (sample['frequencies_hz']==[145000000,433000000]
         and not (sample['flags'][0] & 0xb0)
         and not (sample['flags'][2] & 0x30)
         and sample['front_mismatch']==0
         and sample['front_latched_hex']==b'200000'.hex()
         and sample['initialized']==1
         and sample['journal_active']==0
         and sample['writer_busy']==0)

def power_input_needed(sample,strict_stock=True):
 # A selected candidate's power input must not depend on stock tuning defaults.
 return sample['power_wait']==1 and (not strict_stock or sample['frequencies_hz']!=[145000000,433000000])

def bootstrap_seed(root,folder,notify,verification_seed=None,seed_gate=None):
 """Generate then cold-boot verify bytes. Observation only; never RAM/PC writes."""
 readback=verification_seed is not None
 gate=seed_gate or seed_ready
 seed=verification_seed if readback else (folder/'aux-synthetic-invalid.bin').read_bytes()
 logpath=folder/('seed-readback.log' if readback else 'seed-generation.log')
 diagpath=folder/('SEED_READBACK_DIAGNOSTIC.json' if readback else 'SEED_DIAGNOSTIC.json')
 with tempfile.TemporaryDirectory(prefix='ic9700-seed-') as temp:
  d=Path(temp);sock=d/'control.sock'
  cmd=[str(root/'qemu-machine/qemu-src/build/qemu-system-arm'),'-M','rz-a1h','-m','10M','-kernel',str(folder/'ic9700-flash-stock.bin'),'-display','none','-serial','none','-monitor','none','-no-reboot','-qmp',f'unix:{sock},server=on,wait=off']
  for bank in range(4):
   path=d/f'bank{bank}.bin';path.write_bytes(seed[bank*65536:(bank+1)*65536])
   for opts in [{'driver':'file','filename':str(path),'node-name':f'seedfile{bank}'},{'driver':'raw','file':f'seedfile{bank}','node-name':f'ic9700_aux_bank{bank}'}]:cmd+=['-blockdev',json.dumps(opts)]
  env={k:v for k,v in os.environ.items() if not k.startswith(('IC9700_','RZA1H_'))}
  env.update(IC9700_AUX_IMAGE=str(folder/'aux-synthetic-invalid.bin'),IC9700_AUX_PERSISTENT='1',IC9700_SHARED_AUX_BUS='1',IC9700_DV_STATUS_IMAGE=str(folder/'dv-compatible.bin'),IC9700_FPGA_VERSION_WORD='0x00333237',IC9700_REFERENCE_PRESENT='1',IC9700_SCIF3_STATUS_IMAGE=str(folder/'panel-stock-flags.bin'),IC9700_SCIF3_HANDSHAKE='1',IC9700_P4_11_HIGH='1',IC9700_P1_5_HIGH='1',IC9700_FRONT_VERSION='200000')
  c=QMPClient(sock,10);proc=None;history=[];power_pulses=0
  with logpath.open('w') as log:
   try:
    proc=subprocess.Popen(cmd,env=env,stdout=log,stderr=log,start_new_session=True)
    end=time.monotonic()+30
    while not sock.exists():
     if proc.poll() is not None or time.monotonic()>end:raise RuntimeError('QEMU could not start. See '+str(logpath))
     time.sleep(.05)
    c.connect()
    notify(('Verifying a cold boot from the saved seed' if readback else 'Waiting for ARM startup and settings save')+' (up to 3 minutes per phase, plus startup/shutdown)…')
    started=time.monotonic();end=started+180;ready=False;stable_since=None;last_hash=None;last_pulse=-20
    def readmem(addr,size):
     remaining=end-time.monotonic()
     if remaining<=0:raise TimeoutError('ARM observation deadline exceeded.')
     c.timeout=min(10,max(.1,remaining))
     p=d/'observe.bin';c.execute('pmemsave',{'val':addr,'size':size,'filename':str(p)});return p.read_bytes()
    def observe():
     sample={'elapsed_s':round(time.monotonic()-started,3),
      'frequencies_hz':[int.from_bytes(readmem(a,4),'little') for a in [0x20482a56,0x20482a9f]],
      'flags':list(readmem(0x204105fa,4)),'front_mismatch':readmem(0x2041026c,1)[0],
      'front_latched_hex':readmem(0x2047a023,6).hex(),
      'initialized':readmem(0x20410668,1)[0],
      'journal_active':readmem(0x204101f8,1)[0],
      'writer_busy':readmem(0x204270dc,1)[0],
      'power_wait':readmem(0x204103a5,1)[0]}
     banks=b''.join((d/f'bank{i}.bin').read_bytes() for i in range(4))
     sample['eeprom_sha256']=sha(banks);sample['eeprom_changed']=banks!=seed
     return sample
    while time.monotonic()<end:
     if proc.poll() is not None:raise RuntimeError('QEMU exited during preparation.')
     c.timeout=min(10,max(.1,end-time.monotonic()));c.execute('stop')
     try:sample=observe()
     finally:c.execute('cont')
     history.append(sample)
     if len(history)%8==0:
      atomic_json(diagpath,{'ready':False,'phase':'readback' if readback else 'generation','history':history})
      notify('Waiting for stable ARM state: '+str(round(sample['elapsed_s']))+'s; FRONT='+str(sample['front_mismatch'])+'; EEPROM changed='+str(sample['eeprom_changed']))
     good=gate(sample) and (readback or sample['eeprom_changed'])
     if good and sample['eeprom_sha256']==last_hash:
      if stable_since is None:stable_since=time.monotonic()
      if time.monotonic()-stable_since>=2:
       # Revalidate under STOP and stay stopped through QUIT/publication.
       c.execute('stop')
       try:
        final=observe();history.append(final)
        ready=gate(final) and final['eeprom_sha256']==sample['eeprom_sha256']
        if ready:sample=final;break
        stable_since=None
       finally:
        if not ready:c.execute('cont')
     else:stable_since=None
     last_hash=sample['eeprom_sha256']
     if not readback and power_input_needed(sample,strict_stock=seed_gate is None) and time.monotonic()-started-last_pulse>=10:
      c.execute('qom-set',{'path':'/machine/gpio','property':'ic9700-power-pulse','value':True});power_pulses+=1;last_pulse=time.monotonic()-started
     time.sleep(.25)
    diagnostic={'validation':('stock masked TX/frequency/version gates' if seed_gate is None else 'selected firmware initialization and EEPROM journal completion; no stock frequency/TX gate')+'; coherent STOP samples; final STOP held through QUIT; cold readback required','phase':'readback' if readback else 'generation','history':history,'ready':ready,'power_pulses':power_pulses}
    atomic_json(diagpath,diagnostic)
    if not ready:raise RuntimeError('ARM state not stable; no generation published. See '+str(diagpath)+'; last='+json.dumps(history[-1] if history else {}))
    c.timeout=10;c.execute('quit');rc=proc.wait(timeout=15)
    if rc!=0:raise RuntimeError('QEMU did not shut down cleanly during preparation.')
    log.flush()
    if 'failed to write backing file' in logpath.read_text().lower():raise RuntimeError('EEPROM backing write failed; generation not published.')
    data=b''.join((d/f'bank{i}.bin').read_bytes() for i in range(4))
    if len(data)!=262144 or (not readback and data==seed):raise RuntimeError('No valid EEPROM defaults.')
    if sha(data)!=sample['eeprom_sha256']:raise RuntimeError('EEPROM changed after final sample; generation not published. See '+str(diagpath))
    diagnostic['post_quit_eeprom_sha256']=sha(data);diagnostic['validated_bytes_equal_published']=True
    atomic_json(diagpath,diagnostic)
    evidence={'frequencies_hz':sample['frequencies_hz'],'tx_flags':bytes(sample['flags']).hex(),'front_mismatch':f"{sample['front_mismatch']:02x}",'guest_ram_or_pc_writes':False,'changed_eeprom_bytes':sum(a!=b for a,b in zip(seed,data)),'validation_version':PIPELINE_VERSION,'coherent_ready_sample':sample,'masked_tx_flags_clear':not (sample['flags'][0]&0xb0 or sample['flags'][2]&0x30),'post_quit_sha256':sha(data),'power_pulses':power_pulses}
    if not readback:
     cold=bootstrap_seed(root,folder,notify,verification_seed=data,seed_gate=seed_gate)
     if cold['power_pulses']!=0:raise RuntimeError('Readback was not a cold boot.')
     evidence['cold_boot_verified']=True;evidence['cold_boot_evidence']=cold
     (folder/'ui-ready-seed.bin').write_bytes(data)
    return evidence
   except Exception as error:
    try:atomic_json(diagpath,{'ready':False,'error':str(error),'history':history,'power_pulses':power_pulses})
    except Exception:pass
    raise
   finally:
    try:
     if proc and proc.poll() is None:
      try:c.timeout=5;c.execute('quit');proc.wait(timeout=10)
      except Exception:
       if proc.poll() is None:
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
    finally:c.close()

def prepare(root,dat,notify=lambda text:None):
 root=Path(root).resolve();dat=Path(dat).resolve();work=root/'work';work.mkdir(exist_ok=True)
 lock=os.open(work/'prepare.lock',os.O_CREAT|os.O_RDWR,0o600)
 folder=None
 try:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  notify('Validating original IC-9700 v1.50 DAT…')
  raw=dat.read_bytes()
  if sha(raw)!=DAT_SHA:raise ValueError('Unsupported or altered DAT. Only original 9700E150.dat (v1.50) is validated.')
  generations=work/'processed';generations.mkdir(exist_ok=True)
  if generations.is_symlink():raise RuntimeError('Unsafe processed directory.')
  folder=generations/('.partial-'+uuid.uuid4().hex);folder.mkdir()
  decode=folder/'decoded';decode.mkdir()
  key,_=derive_key(raw);start,iv,boot=find_start(raw,key)
  if start!=0x38:raise ValueError('Unexpected firmware domain.')
  end=start+0x800000
  if hashlib.md5(raw[start:end]).digest()!=raw[end:end+16]:raise ValueError('Container MD5 checksum mismatch.')
  notify('Decoding autokey and decompressing ARM/graphics LZSS…')
  body,_=autokey_decode(raw[start:end],start,key,iv)
  if sha(body)!=BODY_SHA:raise ValueError('Body does not match validated stock firmware.')
  csz,osz=struct.unpack_from('<II',body,0x10000)
  main,used=lzss_decompress(body[0x10008:0x10008+csz],osz)
  gp=0x10008+csz;gcsz,gosz=struct.unpack_from('<II',body,gp)
  graphics,gused=lzss_decompress(body[gp+8:gp+8+gcsz],gosz)
  if len(main)!=osz or used>csz or sha(main)!=MAIN_SHA or len(graphics)!=gosz or gused>gcsz or sha(graphics)!=GRAPHICS_SHA:raise ValueError('ARM/graphics integrity check failed.')
  for name,data in [('body.bin',body),('main.bin',main),('graphics.bin',graphics),('bootstrap.bin',boot)]: (decode/name).write_bytes(data)
  notify('Building virtual stock flash and synthetic peripherals…')
  flash=bytearray(b'\xff'*0x1000000);flash[:len(body)]=body;flash[0x800000:0xff0000]=body[0x10000:]
  if sha(flash)!='30d31dd94c7e40d594109a633dc7c053bb374f14041d5b022f1101e2a5f91334':raise ValueError('Unexpected reconstructed flash.')
  (folder/'ic9700-flash-stock.bin').write_bytes(flash)
  image=bytearray(b'\xff'*262144)
  def rom(addr,n):return main[addr-0x20005000:addr-0x20005000+n]
  def word(addr):return struct.unpack('<I',rom(addr,4))[0]
  def put(logical,data):
   for i,v in enumerate(data):
    a=logical+i;wire=(a&63)+((a>>7)<<6)+(((a>>6)&1)<<17);image[wire]=v
  put(0x3fcc0,rom(0x202eff1c,16));put(0x3fd00,rom(word(0x200083a4),0xce));put(0x3ff80,rom(word(0x20068620),128))
  put(word(0x20068630),rom(word(word(0x2006862c)),16));put(word(0x20024480),b'\x07')
  a=0x3a6f0;image[(a&63)+((a>>7)<<6)+(((a>>6)&1)<<17)]=0xff
  (folder/'aux-synthetic-invalid.bin').write_bytes(image)
  panel=bytearray(52);panel[3:9]=b'210E00';panel[51]=0x73;(folder/'panel-stock-flags.bin').write_bytes(panel)
  dv=bytearray(20);dv[8:12]=b'3.62';(folder/'dv-compatible.bin').write_bytes(dv)
  evidence=bootstrap_seed(root,folder,notify)
  if dat.read_bytes()!=raw:raise RuntimeError('DAT changed during preparation.')
  outputs={str(p.relative_to(folder)):sha(p.read_bytes()) for p in folder.rglob('*') if p.is_file() and p.name!='seed-generation.log'}
  record={'pipeline_version':PIPELINE_VERSION,'original_dat_sha256':DAT_SHA,'input_name':dat.name,'outputs_sha256':outputs,'arm_seed_evidence':evidence,'synthetic_model':'explicit compatibility peers/ideal reference; not physical EEPROM or RF','prepared_at':time.strftime('%Y-%m-%dT%H:%M:%S%z')}
  atomic_json(folder/'PREPARED.json',record)
  for p in folder.rglob('*'):
   if p.is_file():
    with p.open('rb') as f:os.fsync(f.fileno())
  final=generations/('generation-'+uuid.uuid4().hex);os.rename(folder,final)
  atomic_json(work/'current.json',{'generation':final.name})
  notify('Preparation complete and verified. User profiles preserved.')
  return final,record
 finally:os.close(lock)

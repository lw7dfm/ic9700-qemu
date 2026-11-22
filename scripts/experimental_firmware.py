#!/usr/bin/env python3
"""Explicit unverified DAT execution, separate from the hash-pinned stock pipeline.
One selected DAT supplies all firmware/templates. Its own ARM creates defaults.
No stock DAT, prebuilt seed, or other firmware cache is read for a candidate.
"""
from pathlib import Path
import fcntl,hashlib,json,os,re,struct,uuid
from prepare_firmware import sha,atomic_json,bootstrap_seed
from firmware_environment import write_inputs,candidate_seed_ready
from vendor.icom_rza1_decode import derive_key,autokey_decode,autokey_reverse,lzss_decompress,ARM_VECTORS
VERSION=3
CONTAINER_SIZE=15629913
MODEL_TAG=bytes.fromhex("33991133")
DOMAIN_START=0x38
DOMAIN_SIZE=0x800000
MAX_DAT=32*1024*1024
MAX_MAIN=8*1024*1024
MAX_GRAPHICS=16*1024*1024
BASE_ASSETS=('ui-ready-seed.bin','panel-stock-flags.bin','dv-compatible.bin')
OUTPUTS=set(BASE_ASSETS)|{'ic9700-flash-stock.bin','decoded/body.bin','decoded/main.bin','decoded/graphics.bin','decoded/bootstrap.bin','aux-synthetic-invalid.bin','SEED_DIAGNOSTIC.json','SEED_READBACK_DIAGNOSTIC.json','seed-generation.log','seed-readback.log'}

def read_dat(path):
    path=Path(path)
    if not path.is_file() or not DOMAIN_START+DOMAIN_SIZE+16<=path.stat().st_size<=MAX_DAT:
        raise ValueError('DAT size outside the supported v1.50-compatible layout')
    with path.open('rb') as f:raw=f.read(MAX_DAT+1)
    if len(raw)>MAX_DAT:raise ValueError('DAT exceeds size limit')
    return raw

def require_sha(raw,expected):
    if not re.fullmatch('[0-9a-fA-F]{64}',expected or ''):raise ValueError('An exact candidate SHA-256 is required')
    digest=sha(raw)
    if digest!=expected.lower():raise ValueError('Candidate SHA-256 differs from the selected/confirmed input')
    return digest

def decode_components(body):
    def stream(offset,maximum,label):
        if not 0<=offset<=len(body)-8:raise ValueError(label+' header outside main domain')
        compressed,expected=struct.unpack_from('<II',body,offset)
        if not 0<compressed<=len(body)-offset-8 or not 0<expected<=maximum:
            raise ValueError(label+' stream size outside supported bounds')
        data=body[offset+8:offset+8+compressed]
        try:decoded,used=lzss_decompress(data,expected)
        except (IndexError,ValueError,struct.error) as e:raise ValueError(label+' invalid LZSS stream') from e
        if len(decoded)!=expected or used>compressed:raise ValueError(label+' truncated LZSS stream')
        return decoded,offset+8+compressed
    main,next_offset=stream(0x10000,MAX_MAIN,'ARM')
    graphics,_=stream(next_offset,MAX_GRAPHICS,'Graphics')
    return main,graphics

def decode_candidate(raw):
    if len(raw)!=CONTAINER_SIZE or raw[:4]!=MODEL_TAG:
        raise ValueError('Only IC-9700 DATs compatible with the v1.50 container geometry are supported')
    end=DOMAIN_START+DOMAIN_SIZE
    if hashlib.md5(raw[DOMAIN_START:end]).digest()!=raw[end:end+16]:
        raise ValueError('Candidate container MD5 mismatch; re-export a valid DAT')
    key,_=derive_key(raw)
    if key!=0x2b:raise ValueError('Unsupported IC-9700 autokey model key')
    start,iv,boot=bootstrap_at_fixed_start(raw,key)
    if start!=DOMAIN_START or len(boot)!=0x10000:
        raise ValueError('Candidate is not the supported IC-9700 RZ/A1 DAT layout')
    body,_=autokey_decode(raw[start:end],start,key,iv)
    main,graphics=decode_components(body)
    if boot!=body[:0x10000]:raise ValueError('Decoded bootstrap mismatch')
    return body,main,graphics,{'external_components_present':len(raw)>end+16,'external_components_executed':False,'external_payload_sha256':sha(raw[end+16:]),'container_header_executed':False}

def bootstrap_at_fixed_start(raw,key):
    # Same vendor algorithm, but only two bounded windows at the supported offset.
    # Invalid input must not trigger a generic search over thousands of offsets.
    start=DOMAIN_START
    for window in (0x1000,0x10000):
        head,iv=autokey_reverse(raw[start:start+window],start,key)
        if head[:8]==ARM_VECTORS:
            boot,_=autokey_decode(raw[start:start+0x10000],start,key,iv)
            return start,iv,boot
    raise ValueError('Unsupported or malformed bootstrap at IC-9700 DAT offset')

def decode_bootstrap(raw):
    key,_=derive_key(raw)
    return bootstrap_at_fixed_start(raw,key)[2]

def require_local_parents(root,*parts):
    path=Path(root)
    for name in parts:
        path=path/name
        if path.is_symlink():raise ValueError('Symlink output parent rejected: '+name)
    return path

def cached(root,dat,expected_sha):
    raw=read_dat(dat);digest=require_sha(raw,expected_sha)
    parent=require_local_parents(root,'work','experiments',digest)
    try:
        if parent.is_symlink():return None
        pointer=json.loads((parent/'current.json').read_text());name=pointer['generation']
        if Path(name).name!=name or not name.startswith('generation-'):return None
        folder=parent/name
        if folder.is_symlink() or (folder/'decoded').is_symlink():return None
        m=json.loads((folder/'PREPARED.json').read_text())
        if (m['experimental_pipeline_version']!=VERSION or m['mode']!='experimental'
            or m['input_sha256']!=digest or m['seed_source']!='selected-input-only'
            or not m.get('own_seed_evidence',{}).get('cold_boot_verified')
            or m['status']!='PREPARED_UNVERIFIED_EXPERIMENT'
            or set(m['outputs_sha256'])!=OUTPUTS):return None
        for rel,expected in m['outputs_sha256'].items():
            p=folder/rel
            if p.is_symlink() or not p.is_file() or sha(p.read_bytes())!=expected:return None
        return folder,m
    except (OSError,ValueError,KeyError,TypeError):return None

def prepare(root,dat,expected_sha,notify=lambda text:None):
    root=Path(root).resolve();dat=Path(dat).resolve()
    raw=read_dat(dat);digest=require_sha(raw,expected_sha)
    notify('Checking experimental DAT structure, MD5 and bounded decompression…')
    body,main,graphics,scope=decode_candidate(raw)
    parent=require_local_parents(root,'work','experiments',digest)
    parent.mkdir(parents=True,exist_ok=True)
    if parent.is_symlink():raise ValueError('Unsafe experimental cache directory')
    lock=os.open(parent/'prepare.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        folder=parent/('.partial-'+uuid.uuid4().hex);folder.mkdir()
        (folder/'decoded').mkdir()
        for name,data in [('body.bin',body),('main.bin',main),('graphics.bin',graphics),('bootstrap.bin',body[:0x10000])]:
            (folder/'decoded'/name).write_bytes(data)
        flash=bytearray(b'\xff'*0x1000000)
        flash[:len(body)]=body
        flash[0x800000:0xff0000]=body[0x10000:]
        (folder/'ic9700-flash-stock.bin').write_bytes(flash)
        # Historical filename retained for the launcher only. These bytes ARE
        # candidate firmware, not a stock image substituted for the candidate.
        write_inputs(folder,main)
        notify('Selected firmware is creating its OWN synthetic settings; no second DAT is used…')
        seed_evidence=bootstrap_seed(root,folder,notify,seed_gate=candidate_seed_ready)
        outputs={name:sha((folder/name).read_bytes()) for name in sorted(OUTPUTS)}
        record={'experimental_pipeline_version':VERSION,'mode':'experimental',
            'status':'PREPARED_UNVERIFIED_EXPERIMENT','input_sha256':digest,
            'foreign_firmware_loaded':False,'own_seed_evidence':seed_evidence,
            'outputs_sha256':outputs,'main_sha256':sha(main),'bootstrap_sha256':sha(body[:0x10000]),
            'graphics_sha256':sha(graphics),'container_md5_valid':True,'component_scope':scope,
            'candidate_boot_validated':False,'hardware_or_RF_validated':False,
            'seed_source':'selected-input-only',
            'layout':'desktop virtual flash with candidate bootstrap and duplicate candidate slots; not a physical update/recovery simulation'}
        if dat.read_bytes()!=raw:raise ValueError('Candidate changed during preparation')
        atomic_json(folder/'PREPARED.json',record)
        for file in folder.rglob('*'):
            if file.is_file():
                with file.open('rb') as f:os.fsync(f.fileno())
        final=parent/('generation-'+uuid.uuid4().hex);os.rename(folder,final)
        atomic_json(parent/'current.json',{'generation':final.name})
        notify('Experimental image prepared — NOT validated. Stock cache/profile unchanged.')
        return final,record
    finally:os.close(lock)

def profile_name(digest,label=None):
    if not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('Invalid input fingerprint')
    if label is None:return 'exp-s3-'+digest[:36]
    if not re.fullmatch('[A-Za-z0-9_-]{1,18}',label):raise ValueError('Experimental profile labels require 1..18 letters/digits/_/-')
    return 'exp-s3-'+digest[:20]+'-'+label

def bind_profile(root,name,digest,label=None):
    if name!=profile_name(digest,label):raise ValueError('Experimental profile name does not match firmware')
    directory=require_local_parents(root,'work','eeprom',name);directory.mkdir(parents=True,exist_ok=True)
    if directory.is_symlink():raise ValueError('Unsafe experimental profile')
    fd=os.open(directory/'firmware-binding.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        expected={'mode':'experimental','environment_version':VERSION,'input_sha256':digest,'label':label}
        path=directory/'firmware-binding.json'
        if path.is_symlink():raise ValueError('Unsafe firmware binding')
        if path.exists():
            if json.loads(path.read_text())!=expected:raise ValueError('Profile belongs to a different firmware/label')
        else:
            if (directory/'state.bin').exists():raise ValueError('Unbound existing profile cannot be adopted')
            atomic_json(path,expected)
    finally:os.close(fd)

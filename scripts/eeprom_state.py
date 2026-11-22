"""Project-local opt-in synthetic EEPROM session. Publication only on explicit commit.
Atomic aggregated state, advisory lock; incomplete I2C writes are not recoverable.
"""
import fcntl,hashlib,json,os,re,stat,tempfile
from pathlib import Path
P=Path(__file__).resolve().parent.parent
class State:
 def __init__(self,name,fixture):
  if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',name):raise ValueError('state name must be1..48 letters/digits/_/-')
  root=P/'work/eeprom';root.mkdir(exist_ok=True)
  if root.is_symlink():raise ValueError('symlink state root rejected')
  self.directory=root/name
  if self.directory.is_symlink():raise ValueError('symlink state directory rejected')
  self.directory.mkdir(exist_ok=True)
  self.fixture=Path(fixture).resolve();self.canonical=self.directory/'state.bin'
  self.lock=os.open(self.directory/'state.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
  try:
   if not stat.S_ISREG(os.fstat(self.lock).st_mode):raise ValueError('lock is not regular')
   fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   if self.canonical.exists() or self.canonical.is_symlink():
    if self.canonical.is_symlink() or not self.canonical.is_file() or os.path.samefile(self.canonical,self.fixture):raise ValueError('unsafe canonical state')
    seed=self.canonical.read_bytes()
   else:
    seed=self.fixture.read_bytes()
   if len(seed)!=262144:raise ValueError('EEPROM state must be262144bytes')
   self.session=Path(tempfile.mkdtemp(prefix='session-',dir=self.directory))
   for b in range(4):(self.session/f'bank{b}.bin').write_bytes(seed[b*65536:(b+1)*65536])
   (self.session/'manifest.json').write_text(json.dumps({'type':'synthetic bus-addressed EEPROM, not physical dump','source':str(self.canonical if self.canonical.exists() else self.fixture),'input_sha256':hashlib.sha256(seed).hexdigest(),'commit':'only after clean QEMU exit; incomplete I2C transfer may be lost'},indent=2)+'\n')
  except BaseException:
   os.close(self.lock);raise
 def arguments(self):
  args=[]
  for b in range(4):
   for opts in [{'driver':'file','filename':str(self.session/f'bank{b}.bin'),'node-name':f'ic9700_aux_file{b}'},{'driver':'raw','file':f'ic9700_aux_file{b}','node-name':f'ic9700_aux_bank{b}'}]:args+=['-blockdev',json.dumps(opts)]
  return args
 def commit(self):
  data=b''
  for b in range(4):
   path=self.session/f'bank{b}.bin'
   if path.is_symlink() or not path.is_file():raise ValueError('unsafe session bank')
   part=path.read_bytes()
   if len(part)!=65536:raise ValueError('incomplete session bank')
   data+=part
  if self.canonical.is_symlink() or (self.canonical.exists() and os.path.samefile(self.canonical,self.fixture)):raise ValueError('unsafe state destination')
  fd,name=tempfile.mkstemp(prefix='.state-',dir=self.directory)
  with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
  os.replace(name,self.canonical)
  fd=os.open(self.directory,os.O_DIRECTORY)
  try:os.fsync(fd)
  finally:os.close(fd)
  (self.session/'COMMITTED.json').write_text(json.dumps({'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})+'\n')
 def close(self):os.close(self.lock)

#!/usr/bin/env python3
"""Launch experimental stock IC9700, VNC loopback only; not a validated radio.
No dependencies installed or input firmware overwritten; opted-in synthetic state is updated.
"""
from pathlib import Path
import argparse, os, subprocess, sys, socket, json, tempfile, signal
from eeprom_state import State
P=Path(__file__).resolve().parent.parent
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--flash-image',type=Path,help='prepared experimental flash from DAT processing')
ap.add_argument('--no-vnc',action='store_true',help='no TCP listener; use local Tkinter QMP panel only')
ap.add_argument('--display',type=int,default=7,help='VNC display 0..99; TCP5900+display on localhost')
ap.add_argument('--reference',choices=['absent','ideal'],default='absent',help='explicit experimental reference input')
ap.add_argument('--status-image',type=Path,default=P/'work/scif3-neutral-status.bin')
ap.add_argument('--aux-image',type=Path,default=P/'work/aux-synthetic-format.bin')
ap.add_argument('--state-name',help='opt-in project-local synthetic EEPROM state; commits only after clean exit')
ap.add_argument('--front-version',help='six ASCII bytes from stock compatibility contract, e.g.200000; explicit synthetic peer')
ap.add_argument('--shared-aux-bus',action='store_true',help='experimental coherent GPIO read / RIIC0 write path to same synthetic EEPROM')
ap.add_argument('--qmp-socket',type=Path,help='explicit new local UNIX socket for control_panel.py; must not already exist')
ap.add_argument('--dv-status-image',type=Path,help='explicit synthetic 20-byte DV status fixture')
ap.add_argument('--fpga-version-word',type=lambda x:int(x,0),help='explicit synthetic FPGA MMIO word')
ap.add_argument('--dry-run',action='store_true')
a=ap.parse_args()
if not 0<=a.display<=99:ap.error('display must be0..99')
if a.qmp_socket and (a.qmp_socket.exists() or a.qmp_socket.is_symlink()):ap.error('QMP socket path already exists; choose a new path')
if a.dv_status_image and (not a.dv_status_image.is_file() or a.dv_status_image.stat().st_size!=20):ap.error('DV fixture must be20 bytes')
if a.fpga_version_word is not None and not 0<=a.fpga_version_word<=0xffffffff:ap.error('FPGA word must be uint32')
q=P/'qemu-machine/qemu-src/build/qemu-system-arm';flash=a.flash_image or P/'work/ic9700-flash-stock.bin'
for path,size in [(q,None),(flash,None),(a.status_image,52),(a.aux_image,262144)]:
 if not path.is_file() or (size is not None and path.stat().st_size!=size):ap.error(f'missing or wrong-size input: {path}')
env=os.environ.copy();env.update(IC9700_AUX_IMAGE=str(a.aux_image.resolve()),IC9700_SCIF3_STATUS_IMAGE=str(a.status_image.resolve()),IC9700_SCIF3_HANDSHAKE='1',IC9700_P4_11_HIGH='1',IC9700_P1_5_HIGH='1',IC9700_REFERENCE_PRESENT=str(int(a.reference=='ideal')))
if a.front_version:
 if len(a.front_version)!=6 or any(not 0x20<=ord(x)<=0x7e for x in a.front_version):ap.error('front version requires six printable ASCII bytes')
 env['IC9700_FRONT_VERSION']=a.front_version
if a.shared_aux_bus:env['IC9700_SHARED_AUX_BUS']='1'
else:env.pop('IC9700_SHARED_AUX_BUS',None)
if a.dv_status_image:env['IC9700_DV_STATUS_IMAGE']=str(a.dv_status_image.resolve())
if a.fpga_version_word is not None:env['IC9700_FPGA_VERSION_WORD']=hex(a.fpga_version_word)
cmd=[str(q),'-M','rz-a1h','-m','10M','-kernel',str(flash),'-display','none','-serial','none','-monitor','none','-no-reboot']
if not a.no_vnc:cmd+=['-vnc',f'127.0.0.1:{a.display}']
print(f'IC-9700 emulator: configured VNC address 127.0.0.1:{5900+a.display} (disabled by --no-vnc); reference={a.reference}; Ctrl+C requests clean QMP quit. Partial navigation only; no RF/PTT.',flush=True)
if a.dry_run:
 import shlex
 print(shlex.join(cmd));print('EEPROM:', 'opt-in state '+a.state_name if a.state_name else 'volatile');sys.exit(0)
state=None;proc=None;connection=None;log=None;rc=1
interrupt_requested=False
def defer_interrupt(signum, frame):
 global interrupt_requested
 interrupt_requested=True
prior_sigint=signal.signal(signal.SIGINT,defer_interrupt)
try:
 if a.state_name:
  state=State(a.state_name,a.aux_image);env['IC9700_AUX_PERSISTENT']='1';cmd+=state.arguments()
 else:env.pop('IC9700_AUX_PERSISTENT',None)
 # Short temporary socket path avoids UNIX sun_path length limits.
 with tempfile.TemporaryDirectory(prefix='ic9700-qmp-') as tmp:
  sockpath=Path(tmp)/'control.sock';cmd+=['-qmp',f'unix:{sockpath},server=on,wait=off']
  if a.qmp_socket:cmd+=['-qmp',f'unix:{a.qmp_socket.resolve()},server=on,wait=off']
  if state:log=(state.session/'qemu.log').open('w+')
  proc=subprocess.Popen(cmd,env=env,stderr=log,start_new_session=True)
  connection=socket.socket(socket.AF_UNIX);connection.settimeout(10)
  import time
  deadline=time.monotonic()+10
  while True:
   try:connection.connect(str(sockpath));break
   except (FileNotFoundError,ConnectionRefusedError):
    if proc.poll() is not None or time.monotonic()>deadline:raise RuntimeError('QEMU QMP unavailable; state not committed')
    time.sleep(.1)
  stream=connection.makefile('rwb',buffering=0)
  json.loads(stream.readline())
  def qmp(command):
   stream.write((json.dumps({'execute':command})+'\n').encode())
   while True:
    line=stream.readline()
    if not line:raise RuntimeError('QMP closed before reply')
    reply=json.loads(line)
    if 'error' in reply:raise RuntimeError(str(reply))
    if 'return' in reply:return reply
  qmp('qmp_capabilities')
  signal.signal(signal.SIGINT,signal.default_int_handler)
  if interrupt_requested:qmp('quit')
  try:rc=proc.wait()
  except KeyboardInterrupt:
   qmp('quit');rc=proc.wait(timeout=15)
  if rc==0 and state:
   log.flush();log.seek(0);errors=log.read().lower()
   if 'failed to write backing file' in errors:raise RuntimeError('EEPROM backing write failed; state not committed')
   state.commit();print('EEPROM session committed:',state.canonical,flush=True)
  elif state:print('Abnormal exit: prior state preserved; session retained:',state.session,file=sys.stderr)
except BaseException as error:
 print('Launch/session failed:',error,file=sys.stderr);rc=1
finally:
 signal.signal(signal.SIGINT,prior_sigint)
 if proc and proc.poll() is None:
  proc.terminate()
  try:proc.wait(timeout=5)
  except subprocess.TimeoutExpired:proc.kill();proc.wait()
 if connection:connection.close()
 if log:log.close()
 if state:state.close()
sys.exit(rc)

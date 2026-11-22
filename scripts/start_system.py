#!/usr/bin/env python3
"""One command: preflight, QEMU + original LCD/controls, clean persistent close.
Independent emulator; no RF/hardware access or firmware modifications.
"""
import argparse,ctypes,hashlib,json,os,platform,signal,subprocess,sys,tempfile,time,threading,queue
from pathlib import Path
P=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(P/'scripts'))
from control_panel import Panel,QMPClient
from prepare_firmware import cached,prepare,DAT_SHA
import experimental_firmware as experimental

def preflight():
 if platform.machine().lower() not in ('x86_64','amd64'):raise RuntimeError('This launcher requires Linux x86-64.')
 libc=ctypes.CDLL(None);libc.gnu_get_libc_version.restype=ctypes.c_char_p
 version=libc.gnu_get_libc_version().decode()
 if tuple(map(int,version.split('.')[:2]))<(2,38):raise RuntimeError(f'glibc {version}: requires >=2.38. Use Ubuntu 24.04 or later; do not replace glibc manually.')
 for rel,size in [('qemu-machine/qemu-src/build/qemu-system-arm',None)]:
  path=P/rel
  if not path.is_file() or (size and path.stat().st_size!=size):raise RuntimeError(f'Missing/incomplete file: {rel}')
 manifest=P/'PACKAGE_MANIFEST.json'
 if manifest.exists():
  for rel,expected in json.loads(manifest.read_text())['runtime_sha256'].items():
   if hashlib.sha256((P/rel).read_bytes()).hexdigest()!=expected:raise RuntimeError(f'Checksum mismatch: {rel}')
 binary=P/'qemu-machine/qemu-src/build/qemu-system-arm'
 if not os.access(binary,os.X_OK):raise RuntimeError('QEMU is not executable. Run: chmod +x qemu-machine/qemu-src/build/qemu-system-arm')
 check=subprocess.run([str(binary),'--version'],capture_output=True,text=True)
 if check.returncode:raise RuntimeError('Cannot execute QEMU: '+check.stderr.strip())
 import tkinter as tk
 return tk,version

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--firmware',type=Path,help='DAT selected for execution; stock or explicit experimental mode')
 ap.add_argument('--mode',choices=['auto','stock','experimental'],default='auto',help='auto: classify one selected DAT; stock: exact known input; experimental: explicit research input')
 ap.add_argument('--expected-sha256',help='pin the selected experimental DAT fingerprint')
 ap.add_argument('--accept-experimental',action='store_true',help='explicit noninteractive consent; requires --mode experimental and --expected-sha256')
 ap.add_argument('--choice',choices=['run','reprocess'],help='explicit choice for command-line use/testing')
 ap.add_argument('--prepare-only',action='store_true',help='prepare/reuse assets without opening the emulator')
 ap.add_argument('--check',action='store_true',help='check prerequisites without starting QEMU')
 ap.add_argument('--state-name',help='stock profile name, or experimental label (1..18 characters); firmware isolation is automatic')
 ap.add_argument('--smoke-test',action='store_true',help='automated smoke test and clean close after 8 seconds')
 a=ap.parse_args();root=None;proc=None;log=None;panel=None;rc=1;result={}
 try:
  tk,glibc=preflight();root=tk.Tk();root.withdraw()
  if a.check:
   print('OK: Linux x86-64, glibc'+glibc+', Tkinter/display and QEMU. DAT processing is checked at startup.');root.destroy();return 0
  mode=a.mode
  if a.accept_experimental and (mode!='experimental' or not a.expected_sha256 or a.firmware is None):
   raise ValueError('--accept-experimental requires --mode experimental, --firmware and --expected-sha256')
  if a.expected_sha256 and mode!='experimental':raise ValueError('--expected-sha256 requires --mode experimental')
  def choose_dat(path,title,explicit=False):
   if path is not None:
    path=path.expanduser().resolve()
    if path.is_file():return path
   if explicit or a.accept_experimental or a.choice is not None or a.prepare_only:
    raise FileNotFoundError('Required DAT does not exist: '+str(path))
   from tkinter import filedialog
   selected=filedialog.askopenfilename(parent=root,title=title,initialdir=str(P/'firmware'),filetypes=[('Icom DAT','*.dat'),('All files','*')])
   return Path(selected).resolve() if selected else None
  default_dat=P/'firmware/9700E150.dat'
  use_default=(mode=='stock' or a.choice is not None or a.prepare_only)
  dat=choose_dat(a.firmware or (default_dat if use_default else None),'Select IC-9700 DAT — original or modified',explicit=a.firmware is not None)
  if dat is None:root.destroy();return 0
  confirmed_sha=None
  if mode=='auto':
   selected=experimental.read_dat(dat)
   mode='stock' if hashlib.sha256(selected).hexdigest()==DAT_SHA else 'experimental'
  if mode=='experimental':
   raw=experimental.read_dat(dat);confirmed_sha=hashlib.sha256(raw).hexdigest()
   if a.expected_sha256:experimental.require_sha(raw,a.expected_sha256)
   if not a.accept_experimental:
    from tkinter import messagebox
    if not messagebox.askyesno('UNVERIFIED experimental firmware',
       'Run this user-supplied DAT in QEMU only?\n'+dat.name+'\nSHA-256: '+confirmed_sha+
       '\n\nChecksum-valid is NOT safe or compatible. Candidate code may crash or change its own isolated settings. Only this DAT is used. Its ARM creates its own settings. External peripheral payloads are NOT executed. No physical radio is accessed.',parent=root):
     root.destroy();return 0
   previous=experimental.cached(P,dat,confirmed_sha)
   state_name=experimental.profile_name(confirmed_sha,a.state_name)
  else:
   if a.accept_experimental:raise ValueError('Experimental consent cannot be used in stock mode')
   state_name=a.state_name or 'usuario'
   if state_name.startswith('exp-'):raise ValueError('exp- profiles are reserved for isolated experiments')
   previous=cached(P,dat)
  choice=a.choice
  if previous and choice is None:
   dialog=tk.Toplevel(root);dialog.title('IC-9700 — firmware already prepared');selection=[]
   tk.Label(dialog,text='An intact preparation of the selected DAT exists.\nWhat would you like to do?',padx=24,pady=18).pack()
   def choose(value):selection.append(value);dialog.destroy()
   for text,value in [('Run prepared firmware','run'),('Reprocess selected firmware','reprocess'),('Cancel','cancel')]:
    tk.Button(dialog,text=text,command=lambda value=value:choose(value),width=36).pack(padx=20,pady=5)
   dialog.protocol('WM_DELETE_WINDOW',lambda:choose('cancel'));dialog.grab_set();root.wait_window(dialog)
   choice=selection[0]
   if choice=='cancel':root.destroy();return 0
  if choice=='run' and not previous:raise RuntimeError('No intact preparation exists. Choose reprocess or start without --choice.')
  if previous and choice!='reprocess':assets,prepared=previous
  else:
   from tkinter import ttk
   progress=tk.Toplevel(root);progress.title('IC-9700 — preparing '+mode+' firmware')
   status=tk.StringVar(value='Starting full preparation…')
   tk.Label(progress,textvariable=status,wraplength=500,padx=20,pady=20).pack()
   bar=ttk.Progressbar(progress,mode='indeterminate',length=460);bar.pack(padx=20,pady=15);bar.start()
   progress.protocol('WM_DELETE_WINDOW',lambda:None)
   events=queue.Queue();outcome=[]
   def build():
    try:
     notify=lambda text:events.put(('status',text))
     if mode=='experimental':
      value=experimental.prepare(P,dat,confirmed_sha,notify)
     else:value=prepare(P,dat,notify)
     events.put(('result',value))
    except Exception as error:events.put(('error',error))
   worker=threading.Thread(target=build,name='DAT-processing');worker.start()
   def poll_prepare():
    try:
     while True:
      kind,value=events.get_nowait()
      if kind=='status':status.set(value)
      else:outcome.append((kind,value));progress.destroy();return
    except queue.Empty:pass
    root.after(80,poll_prepare)
   root.after(80,poll_prepare);progress.grab_set();root.wait_window(progress);worker.join()
   kind,value=outcome[0]
   if kind=='error':raise value
   assets,prepared=value
  if a.prepare_only:
   print(json.dumps({'prepared_generation':str(assets),'input_sha256':prepared.get('input_sha256',prepared.get('original_dat_sha256')),'mode':mode,'candidate_boot_validated':False if mode=='experimental' else True,'reused':bool(previous and choice!='reprocess')},indent=2));root.destroy();return 0
  if mode=='experimental':experimental.bind_profile(P,state_name,confirmed_sha,a.state_name)
  with tempfile.TemporaryDirectory(prefix='ic9700-auto-') as temp:
   sock=Path(temp)/'panel.sock'
   (P/'work').mkdir(exist_ok=True)
   log=(P/'work/INICIAR.log').open('a',buffering=1)
   log.write('\n--- Start '+time.strftime('%Y-%m-%d %H:%M:%S')+' ---\n')
   env=os.environ.copy()
   # Do not inherit experiment toggles/debugging from another shell.
   for name in list(env):
    if name.startswith(('IC9700_','RZA1H_')):env.pop(name)
   cmd=[sys.executable,str(P/'scripts/run_vnc.py'),'--flash-image',str(assets/'ic9700-flash-stock.bin'),'--no-vnc','--reference','ideal','--status-image',str(assets/'panel-stock-flags.bin'),'--aux-image',str(assets/'ui-ready-seed.bin'),'--dv-status-image',str(assets/'dv-compatible.bin'),'--fpga-version-word','0x00333237','--front-version','200000','--shared-aux-bus','--state-name',state_name,'--qmp-socket',str(sock)]
   proc=subprocess.Popen(cmd,env=env,stdout=log,stderr=log,start_new_session=True)
   deadline=time.monotonic()+12
   while not sock.exists():
    if proc.poll() is not None or time.monotonic()>deadline:raise RuntimeError('QEMU could not start. Check work/INICIAR.log (profile in use or missing dependency).')
    time.sleep(.05)
   from types import SimpleNamespace
   panel=Panel(root,SimpleNamespace(qmp_socket=sock,timeout=5,scale=2,refresh_ms=250))
   root.title('IC-9700 QEMU Emulator — LW7DFM — '+mode+' — '+dat.name)
   if mode=='experimental':
    tk.Label(root,text='UNVERIFIED EXPERIMENT · SHA-256 '+confirmed_sha,fg='red',wraplength=940).pack(padx=8,pady=4)
   log.write('MODE '+mode+' | DAT '+dat.name+' | SHA256 '+(confirmed_sha or prepared['original_dat_sha256'])+' | PROFILE '+state_name+'\n')
   def close():
    if panel.worker:
     panel.worker.stopping.set();panel.worker.join(timeout=6)
    root.destroy()
   root.protocol('WM_DELETE_WINDOW',close)
   def watch():
    if proc.poll() is not None:
     result['unexpected_launcher_exit']=proc.returncode;close();return
    root.after(500,watch)
   root.after(500,watch)
   if a.smoke_test:
    def smoke():
     result.update(mode=mode,input_sha256=confirmed_sha or prepared['original_dat_sha256'],profile_name=state_name,connected=panel.connected,image_size=[panel.photo.width(),panel.photo.height()] if panel.photo else None,buttons=[b.cget('text') for b in panel.actions],status=panel.status.get())
     if panel.photo:panel.photo.write(str(P/'work/automatic-smoke.png'),format='png')
     close()
    root.after(8000,smoke)
   root.deiconify()
   try:root.mainloop()
   except KeyboardInterrupt:close()
   # Closing this integrated application closes QEMU too. Standalone panel still does not.
   if proc.poll() is None:proc.send_signal(signal.SIGINT)
   try:rc=proc.wait(timeout=25)
   except subprocess.TimeoutExpired:
    c=QMPClient(sock,3)
    try:c.connect();c.execute('quit')
    finally:c.close()
    rc=proc.wait(timeout=15)
   if a.smoke_test:
    result['launcher_returncode']=rc
    result['state_published']=(P/'work/eeprom'/state_name/'state.bin').is_file()
    (P/'work/automatic-smoke.json').write_text(json.dumps(result,indent=2)+'\n')
    if not result.get('connected') or result.get('image_size')!=[960,544] or not result['state_published']:rc=1
   if rc:raise RuntimeError('Unclean shutdown: previous state preserved. See work/INICIAR.log.')
 except Exception as error:
  print('IC-9700: '+str(error),file=sys.stderr)
  if root and not (a.accept_experimental or a.choice is not None or a.prepare_only or a.check):
   try:
    from tkinter import messagebox
    messagebox.showerror('IC-9700 — startup/shutdown failed',str(error),parent=root)
   except Exception:pass
  rc=1
 finally:
  if proc and proc.poll() is None:
   proc.send_signal(signal.SIGINT)
   try:proc.wait(timeout=25)
   except subprocess.TimeoutExpired:print('Process did not close; preserve session and inspect INICIAR.log.',file=sys.stderr)
  if log:log.close()
 return rc
if __name__=='__main__':sys.exit(main())

#!/usr/bin/env python3
"""Optional real-GUI regression after preparation; no firmware is bundled.
Runs the selected stock/experimental mode and invokes the navigation widgets.
Screenshots are local ignored test artifacts, not release contents.
"""
from pathlib import Path
import argparse,hashlib,json,sys,time
P=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(P/'scripts'))
import start_system
config=argparse.ArgumentParser(description=__doc__)
config.add_argument('--mode',choices=['stock','experimental'],default='stock')
config.add_argument('--firmware',type=Path)
config.add_argument('--expected-sha256')
config.add_argument('--expected-main-sha256')
config.add_argument('--main-size',type=int,default=4215604)
config.add_argument('--state-name')
options=config.parse_args()
if not 0<options.main_size<=8*1024*1024:config.error('main-size outside supported test bounds')
if options.mode=='experimental' and (not options.firmware or not options.expected_sha256):config.error('experimental GUI test requires firmware and expected-sha256')
started=time.monotonic()
import control_panel
from control_panel import Panel,QMPClient
observed={}
class Observer(QMPClient):
    def execute(self,command,arguments=None):
        result=super().execute(command,arguments)
        if command=='screendump':
            values={}
            path=P/'work/integration-observation.bin'
            for name,address,size in [('modal',0x2042187c,2),('main_hz',0x20482a56,4),('sub_hz',0x20482a9f,4)]:
                super().execute('pmemsave',{'val':address,'size':size,'filename':str(path)})
                values[name]=int.from_bytes(path.read_bytes(),'little')
            observed.update(values)
            if time.monotonic()-started>=30 and 'main_sha256' not in observed:
                super().execute('pmemsave',{'val':0x20005000,'size':options.main_size,'filename':str(path)})
                observed['main_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        return result
control_panel.QMPClient=Observer
report={'scope':'real Tk/QMP navigation, not RF or full peripheral validation','screens':{},'failures':[]}
class TestPanel(Panel):
    def __init__(self,root,args):
        super().__init__(root,args)
        self.test_root=root
        self.dismissals=0
        root.after(35000,self.baseline)
    def capture(self,name):
        if not self.connected or self.photo is None:raise RuntimeError('Panel not connected with LCD')
        path=P/'work'/('integration-'+name+'.ppm')
        self.photo.write(str(path),format='ppm')
        report['screens'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
    def guarded(self,fn):
        try:fn()
        except Exception as e:
            report['failures'].append(str(e));self.finish()
    def baseline(self):
        def act():
            # A synthetic version peer can leave a queued DV/FPGA warning.
            # Dismiss only these known dialogs through normal touch input;
            # never change guest flags, RAM or PC to suppress them.
            if observed.get('modal') in (0xaf,0xad):
                if self.dismissals>=3:raise RuntimeError('Repeated synthetic version warning')
                self.dismissals+=1
                report['version_warning_touch_dismissals']=self.dismissals
                self.send('touch',(355,190))
                self.test_root.after(2500,self.baseline)
                return
            self.capture('main')
            report['initial_observation']=dict(observed)
            if options.expected_main_sha256 and observed.get('main_sha256')!=options.expected_main_sha256:
                raise RuntimeError('Actual guest main bytes do not match the selected firmware')
            next(b for b in self.actions if b.cget('text')=='MENU').invoke()
            self.test_root.after(2500,lambda:self.guarded(self.menu))
        self.guarded(act)
    def menu(self):
        self.capture('menu')
        if report['screens']['main']==report['screens']['menu']:raise RuntimeError('MENU did not change LCD')
        next(b for b in self.actions if b.cget('text')=='EXIT').invoke()
        self.test_root.after(2500,lambda:self.guarded(self.exit_menu))
    def exit_menu(self):
        self.capture('exit')
        if report['screens']['exit']==report['screens']['menu']:raise RuntimeError('EXIT did not change LCD')
        # Stock tuning has mode-dependent detent divisors; one FM detent may
        # update only an internal remainder, with no visible frequency change.
        button=next(b for b in self.actions if b.cget('text')=='Dial +')
        for index in range(10):self.test_root.after(index*250,button.invoke)
        report['before_dial_observation']=dict(observed)
        report['dial_detents_sent']=10
        self.test_root.after(5500,lambda:self.guarded(self.dial))
    def dial(self):
        self.capture('dial')
        report['after_dial_observation']=dict(observed)
        if observed.get('main_hz')==report['before_dial_observation'].get('main_hz'):raise RuntimeError('Dial did not change guest main frequency')
        if report['screens']['dial']==report['screens']['exit']:raise RuntimeError('Dial did not change LCD')
        report['connected']=self.connected
        report['display_size']=[self.photo.width(),self.photo.height()]
        report['buttons']=[b.cget('text') for b in self.actions]
        self.finish()
    def finish(self):
        self.test_root.tk.call(self.test_root.protocol('WM_DELETE_WINDOW'))
start_system.Panel=TestPanel
profile_label=options.state_name or ('integration-test' if options.mode=='stock' else None)
sys.argv=[sys.argv[0],'--mode',options.mode,'--choice','run']
if options.firmware:sys.argv+=['--firmware',str(options.firmware)]
if profile_label:sys.argv+=['--state-name',profile_label]
if options.mode=='experimental':sys.argv+=['--accept-experimental','--expected-sha256',options.expected_sha256]
report['mode']=options.mode

rc=start_system.main()
report['launcher_returncode']=rc
if options.mode=='experimental':
    import experimental_firmware
    state_name=experimental_firmware.profile_name(options.expected_sha256.lower(),profile_label)
else:state_name=profile_label
report['profile_name']=state_name
report['state_published']=(P/'work/eeprom'/state_name/'state.bin').is_file()
report['pass']=rc==0 and not report['failures'] and len(report['screens'])==4 and report['state_published']
(P/'work/gui-integration.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
sys.exit(0 if report['pass'] else 1)

from pathlib import Path
import hashlib,json,os,signal,socket,subprocess,sys,time
batch=Path(__file__).resolve().parent
source_folder=Path('/Users/rogerjohansson/Library/CloudStorage/GoogleDrive-roger@asynkron.se/Min enhet/c64')
names=('arnold','elf','face','face2','ikplus','mage','r-type','tentacles')
name=sys.argv[1]
assert name in names
program=batch/(name+'.prg')
state=batch/'preview-process.json'
if state.exists():
    old=json.loads(state.read_text())
    identity=subprocess.run(['ps','-p',str(old['pid']),'-o','command='],capture_output=True,text=True)
    if identity.returncode==0 and identity.stdout.strip().startswith('/opt/homebrew/bin/x64sc ') and str(batch) in identity.stdout:
        os.kill(old['pid'],signal.SIGTERM)
with socket.socket() as reserve:
    reserve.bind(('127.0.0.1',0))
    port=reserve.getsockname()[1]
command=['/opt/homebrew/bin/x64sc','+saveres','-pal','-speed','100','+warp','+autostart-warp','-VICIIvsync','+reu','-sounddev','dummy','+confirmonexit','+refreshonbreak','+binarymonitor','-autostartprgmode','1','-autostart',str(program),'-remotemonitor','-remotemonitoraddress',f'ip4://127.0.0.1:{port}']
logfile=(batch/(name+'-vice.log')).open('w')
process=subprocess.Popen(command,stdout=logfile,stderr=subprocess.STDOUT,start_new_session=True)
state.write_text(json.dumps({'pid':process.pid,'port':port,'image':name,'command':command},indent=2))
try:
    time.sleep(10)
    with socket.create_connection(('127.0.0.1',port),timeout=3) as monitor:
        monitor.settimeout(.25)
        def receive():
            chunks=[]
            while True:
                try: chunk=monitor.recv(65536)
                except socket.timeout: break
                if not chunk: break
                chunks.append(chunk)
            return b''.join(chunks).decode(errors='replace')
        transcript=[]
        for text in ['r','resourceget "InitialWarpMode"','resourceget "Speed"','resourceget "AutostartWarp"','resourceget "VICIIVSync"','bank ram',f'bsave "{batch/(name+"-phase-b.bin")}" 0 c000 ffa3']:
            monitor.sendall((text+'\n').encode())
            response=receive()
            transcript.append(text+'\n'+response)
            assert not any(word in response for word in ['ERROR','Unknown resource']),response
        combined='\n'.join(transcript)
        for setting in ['InitialWarpMode=0','Speed=100','AutostartWarp=0','VICIIVSync=1']:
            assert setting in combined,setting
        assert '(C:$2088)' in combined,combined
        source=(source_folder/(name+'.fp2')).read_bytes()
        actual=(batch/(name+'-phase-b.bin')).read_bytes()
        expected=bytearray(source[17402:33694])
        for row in range(25):
            expected[8192+row*320:8192+row*320+24]=bytes(24)
        assert actual==expected,name+' masked phase B mismatch'
        screenshot=batch/(name+'-vice.png')
        monitor.sendall((f'scrsh "{screenshot}" 2\n').encode())
        response=receive()
        transcript.append(response)
        assert 'ERROR' not in response,response
        monitor.sendall(b'x\n')
    (batch/(name+'-monitor.log')).write_text('\n'.join(transcript))
    assert screenshot.is_file()
    (batch/(name+'-verification.json')).write_text(json.dumps({'name':name,'pal':True,'speed_percent':100,'warp':False,'autostart_warp':False,'vsync':True,'display_loop':'$2088','phase_b_bytes_matched':len(actual),'display_mask_left_hires_pixels':24,'source_sha256':hashlib.sha256(source).hexdigest(),'output_sha256':hashlib.sha256(program.read_bytes()).hexdigest(),'screenshot':str(screenshot)},indent=2)+'\n')
    print(json.dumps({'name':name,'screenshot':str(screenshot),'pid':process.pid,'verified_phase_b_bytes':len(actual),'warp':False,'speed':100}),flush=True)
except Exception:
    process.terminate()
    process.wait(timeout=10)
    raise
finally:
    logfile.close()

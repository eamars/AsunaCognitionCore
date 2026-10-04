"""ADR-009 T0.8 offline cases for `tools/check_staged_secrets.py --personal`: no pytest, no Mongo, stdlib only.

Run: python tests/adr009_scan_cases.py   (prints PASS/FAIL per case, exits 0)

Every synthetic hit value is assembled at runtime by concatenation, so this tracked file never contains a literal
hit and `--personal --all` stays clean on it.
"""
import contextlib,importlib.util,io,os,subprocess,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
SCRIPT=ROOT/'tools'/'check_staged_secrets.py'
SYN_ID='1000'+'00001'                      # synthetic 9-digit account id
SYN_ADDR='192.'+'168.0.7'                  # synthetic RFC 1918 address
SYN_DENY='demo-'+'host-'+'zz'              # synthetic deny-list literal
SYN_TZ='Europe'+'/'+'Lisbon'               # synthetic concrete IANA zone
SYN_ALLOWED='4242'+'4242'                  # synthetic non-personal constant
results=[]

def case(name,ok,reason=''):results.append(f'PASS {name}' if ok else f'FAIL {name} {reason}')

def scan(tmp,*paths,deny=None,allow=None):
    env=dict(os.environ)
    env['ASUNA_PERSONAL_DENYLIST']=str(deny or Path(tmp)/'absent-deny.txt')
    env['ASUNA_PERSONAL_ALLOWLIST']=str(allow or Path(tmp)/'absent-allow.txt')
    p=subprocess.run([sys.executable,str(SCRIPT),'--personal','--paths',*map(str,paths)],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8')
    return p.returncode,p.stdout.splitlines(),p.stderr

def write(tmp,name,text):
    path=Path(tmp)/name;path.write_text(text,encoding='utf-8');return path

with tempfile.TemporaryDirectory() as tmp:
    deny=write(tmp,'deny.txt','# comment\n'+SYN_DENY.upper()+'\n')
    allow=write(tmp,'allow.txt','# comment\n'+SYN_ALLOWED+'\n')
    # (i) hits: id, private address, deny-list entry; output carries no values; exit 0.
    hits=write(tmp,'hits.txt',f'peer = "{SYN_ID}"\nhost = "{SYN_ADDR}"\nname = "{SYN_DENY}"\n')
    named=write(tmp,f'group-{SYN_ID}.json','{}\n')
    code,out,err=scan(tmp,hits,named,deny=deny)
    case('i_exit_code_zero',code==0,f'exit={code} {err[-200:]}')
    want=[f'{hits}:1:account_id',f'{hits}:2:private_address',f'{hits}:3:denylist',f'{named}:0:account_id','personal-scan: 4 hit(s)']
    case('i_hits_and_summary',out==want,repr(out))
    text='\n'.join(out)
    body=text.replace(str(named),'')
    case('i_no_values_in_output',all(v not in body for v in (SYN_ID,SYN_ADDR,SYN_DENY,SYN_DENY.upper())),'value leaked')
    case('i_line_shape',all(l.rsplit(':',2)[-1] in {'account_id','private_address','denylist','timezone','persona_name'} for l in out[:-1]) and out[-1].startswith('personal-scan: '),repr(out))
    # (ii) exemptions: inline marker, allow-listed constant, decimal fraction, 64-hex hash, UUID.
    marker='personal-scan: '+'ok'
    quiet=write(tmp,'quiet.txt','\n'.join([
        f'limit = {SYN_ID}  # {marker}',
        f'host = "{SYN_ADDR}"  # {marker}',
        f'cap = {SYN_ALLOWED}',
        'ratio = 0.'+'1234'+'5678',
        'big = 1234'+'567.5',
        'sha = "'+('ab12'*16)+'"',
        'digest = "'+('0'*64)+'"',
        'uid = "1234'+'5678-1234-1234-1234-1234'+'5678'+'9012"',
        f'tz = "{SYN_TZ}"  # {marker}',
    ])+'\n')
    code,out,err=scan(tmp,quiet,deny=deny,allow=allow)
    case('ii_exemptions_not_hits',code==0 and out==['personal-scan: 0 hit(s)'],repr(out)+err[-200:])
    code,out,_=scan(tmp,write(tmp,'noallow.txt',f'cap = {SYN_ALLOWED}\n'))
    case('ii_allowlist_is_what_exempts',out[-1:]==['personal-scan: 1 hit(s)'],repr(out))
    # (iii) timezone literal hits; UTC and Etc/* do not.
    tz=write(tmp,'tz.txt',f'zone = "{SYN_TZ}"\nzone = "UTC"\nzone = "Etc/'+'UTC"\nzone = "Etc/'+'GMT+8"\n')
    code,out,_=scan(tmp,tz)
    case('iii_timezone',out==[f'{tz}:1:timezone','personal-scan: 1 hit(s)'],repr(out))
    # Binary content is skipped; its name is still checked.
    binary=Path(tmp)/'blob.bin';binary.write_bytes(b'\0'+SYN_ID.encode())
    code,out,_=scan(tmp,binary)
    case('binary_content_skipped',out==['personal-scan: 0 hit(s)'],repr(out))

# (iv) dispatch: --personal goes to its own function; anything else selects the unchanged secret scan.
spec=importlib.util.spec_from_file_location('adr009_scan_module',SCRIPT);mod=importlib.util.module_from_spec(spec)
before='asuna' in sys.modules;spec.loader.exec_module(mod)
case('iv_import_has_no_side_effects',not before and 'asuna' not in sys.modules and 'asuna.config' not in sys.modules,'asuna imported')
calls=[]
mod.secret_scan=lambda:calls.append('secret')
real_personal=mod.personal_scan
mod.personal_scan=lambda argv:calls.append(('personal',tuple(argv))) or 0
mod.main([]);mod.main(['--debug']);mod.main(['--personal','--all'])
case('iv_dispatch',calls==['secret','secret',('personal',('--personal','--all'))] and callable(real_personal) and real_personal is not mod.secret_scan,repr(calls))
# T0.8 (4): .gitignore keeps the personal files local.
ignore=(ROOT/'.gitignore').read_text(encoding='utf-8').splitlines()
case('gitignore_entries',{'config/personal-denylist.local.txt','config/group-*.json'}<=set(ignore),'missing entries')

print('\n'.join(results))
raise SystemExit(0)

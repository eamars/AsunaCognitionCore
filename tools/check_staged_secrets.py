"""Report paths only; never print configured secret values or matching bytes.

Default mode (no ``--personal``) scans staged blobs for configured secrets; its output and exit code are unchanged.

``--personal [--all | --paths FILE...]`` (ADR-009 CLEANUP 9) is a stdlib-only, report-only personal-data scan; it
needs neither config/local.json, Mongo nor the asuna package. Source: staged blobs by default, the working-tree copy
of every tracked file with ``--all``, the given files with ``--paths``. Each hit prints ``path:line:category`` (line 0
means the file name; for --paths files outside the repo only the base name is checked) and never the matched value.
Hits are deduplicated per path, line and category. The last line is ``personal-scan: <n> hit(s)``; exit code is 0.

Categories:
  account_id       >=7 consecutive ASCII digits in content or file name.
  private_address  RFC 1918 dotted quads (10/8, 172.16/12, 192.168/16), word-bounded, each octet 0-255.
  denylist         entries of config/personal-denylist.local.txt (override: ASUNA_PERSONAL_DENYLIST); one
                   case-insensitive literal per line, ``re:`` prefix for a regex, ``#`` comments. Absent file:
                   category skipped. Invalid regex entries are skipped (never echoed).
  timezone         concrete IANA Region/City literals; UTC and Etc/* never hit.
  persona_name     the bundled persona's id or display name, only under src/asuna/, packages/cognition-core/,
                   config/, tools/ (persona packages and tests/fixtures/ are exempt).
Exclusions:
  - any line containing the marker ``personal-scan: ok`` (all categories);
  - a matched value equal to an entry of tools/personal_scan_allow.txt (override: ASUNA_PERSONAL_ALLOWLIST);
    that file may only list non-personal constants;
  - account_id only: a digit run touching a decimal point that touches another digit (fraction or integer part of
    a decimal); a digit run inside a contiguous hex token of >=32 chars (hashes and hash placeholders; no account
    id is that long); a digit run inside a UUID (8-4-4-4-12 hex);
  - content of files containing NUL bytes or not decodable as UTF-8 (binary) is skipped; the name is still checked;
  - content of lockfiles package-lock.json and uv.lock is skipped (integrity blobs); the name is still checked;
  - paths under node_modules/, .venv/ and vendored third-party code packages/*/integration/vendor/ are skipped.
Report-only scope: hits under docs/development_plans/ outside ADR-009-persona_residency/ print as
``report-only:path:line:category`` and are not counted in n (any mode).
"""
import argparse,base64,json,os,re,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
# Model parameter names describe token accounting, not authentication material.
NON_SECRET_KEYS={'token_counter','maxTokensField'}

def staged_blobs(root):
    paths=subprocess.check_output(['git','diff','--cached','--name-only','--diff-filter=ACM','-z'],cwd=root).decode().split('\0')
    # Read exactly the staged blobs through one Git process. Thousands of preserved
    # provider artifacts should not require thousands of Windows process launches.
    with subprocess.Popen(['git','cat-file','--batch'],cwd=root,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE) as batch:
        for name in filter(None,paths):
            if '\n' in name or '\r' in name:raise ValueError('UNSUPPORTED_STAGED_PATH')
            batch.stdin.write((':'+name+'\n').encode());batch.stdin.flush()
            header=batch.stdout.readline().split()
            if len(header)!=3 or header[1]!=b'blob':raise ValueError('STAGED_BLOB_READ_FAILED')
            size=int(header[2]);raw=batch.stdout.read(size)
            if len(raw)!=size or batch.stdout.read(1)!=b'\n':raise ValueError('STAGED_BLOB_TRUNCATED')
            yield name,raw
        batch.stdin.close()
        if batch.wait()!=0:raise ValueError('STAGED_BLOB_PROCESS_FAILED')

def secret_scan():
    from asuna.config import ROOT,load
    from asuna.evidence import write_json  # noqa: F401  (unchanged import surface of the default mode)
    secrets=set()
    def collect(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in NON_SECRET_KEYS:continue
                if re.search(r'password|token|api.?key|secret',key,re.I) and isinstance(item,str) and len(item)>=6:secrets.add(item)
                else:collect(item)
        elif isinstance(value,list):
            for item in value:collect(item)
    collect(load())
    for name in ('operator-ssh.json','embedding-ssh.json'):
        path=ROOT/'.runtime'/name
        if path.exists():collect(json.loads(path.read_text(encoding='utf-8')))
    patterns=[re.compile(r'(?<![A-Za-z0-9_.:/\\-])'+re.escape(s)+r'(?![A-Za-z0-9_.:/\\-])') for s in secrets]
    matches=[];checked=0
    for name,raw in staged_blobs(ROOT):
        values=[]
        if name.endswith('.zip'):
            import io,zipfile
            with zipfile.ZipFile(io.BytesIO(raw)) as z:values=[z.read(n).decode('utf-8',errors='ignore') for n in z.namelist()]
        else:values=[raw.decode('utf-8',errors='ignore')]
        values += [base64.b64decode(m,validate=True).decode('utf-8') for value in list(values) for m in re.findall(r'data:application/json;base64,([A-Za-z0-9+/=]+)',value)]
        if any(p.search(value) for value in values for p in patterns):matches.append(name)
        checked+=1
    print(json.dumps({'checked':checked,'matching_paths':matches,'status':'FAIL' if matches else 'PASS'}))
    raise SystemExit(bool(matches))

# ---- --personal (ADR-009) ----
OK_MARK='personal-scan: '+'ok'
DIGITS=re.compile(r'(?<![0-9])[0-9]{7,}(?![0-9])')
HEX=re.compile(r'(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])')
UUID=re.compile(r'(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])')
O=r'(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])'
PRIVATE=re.compile(rf'(?<![\w.])(?:10\.{O}\.{O}\.{O}|172\.(?:1[6-9]|2[0-9]|3[01])\.{O}\.{O}|192\.168\.{O}\.{O})(?!\w|\.[0-9])')
TZ=re.compile(r'\b(?:Africa|America|Antarctica|Asia|Atlantic|Australia|Europe|Indian|Pacific)/[A-Z][A-Za-z_]+(?:/[A-Z][A-Za-z_]+)?\b')
PERSONA=re.compile('xiao'+'man|'+chr(0x5c0f)+chr(0x6ee1),re.I)  # built at runtime so this file never matches itself
CORE=('src/asuna/','packages/cognition-core/','config/','tools/')
SKIP=re.compile(r'(?:^|/)(?:node_modules|\.venv)/|^packages/[^/]+/integration/vendor/')
LOCKFILES={'package-lock.json','uv.lock'}

def report_only(key):return key.startswith('docs/development_plans/') and not key.startswith('docs/development_plans/ADR-009-persona_residency/')

def load_list(env,default):
    try:lines=Path(os.environ.get(env) or default).read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:return []
    return [s for s in (l.strip() for l in lines) if s and not s.startswith('#')]

def denylist():
    out=[]
    for entry in load_list('ASUNA_PERSONAL_DENYLIST',ROOT/'config'/'personal-denylist.local.txt'):
        try:out.append(re.compile(entry[3:]) if entry.startswith('re:') else re.compile(re.escape(entry),re.I))
        except re.error:pass
    return out

def account_id(line,allow):
    spans=[m.span() for r in (HEX,UUID) for m in r.finditer(line)]
    for m in DIGITS.finditer(line):
        s,e=m.span()
        if s>=2 and line[s-1]=='.' and line[s-2].isdigit():continue
        if line[e:e+1]=='.' and line[e+1:e+2].isdigit():continue
        if any(a<=s and e<=b for a,b in spans) or m.group() in allow:continue
        return True
    return False

def scan_lines(text,key,allow,deny):
    persona=key.startswith(CORE)
    for no,line in enumerate(text.split('\n'),1):
        if OK_MARK in line:continue
        if account_id(line,allow):yield no,'account_id'
        if any(m.group() not in allow for m in PRIVATE.finditer(line)):yield no,'private_address'
        if any(p.search(line) for p in deny):yield no,'denylist'
        if any(m.group() not in allow for m in TZ.finditer(line)):yield no,'timezone'
        if persona and PERSONA.search(line):yield no,'persona_name'

def personal_sources(args):
    """Yield (shown path, repo-relative key or base name, raw bytes)."""
    if args.paths:
        for p in args.paths:
            path=Path(p)
            try:key=path.resolve().relative_to(ROOT).as_posix()
            except ValueError:key=path.name
            yield p,key,path.read_bytes()
    elif args.all:
        for name in filter(None,subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf-8').split('\0')):
            if SKIP.search(name):continue
            try:yield name,name,(ROOT/name).read_bytes()
            except OSError:continue  # deleted in the working tree, or a submodule directory
    else:
        for name,raw in staged_blobs(ROOT):yield name,name,raw

def personal_scan(argv):
    ap=argparse.ArgumentParser(prog='check_staged_secrets.py --personal')
    ap.add_argument('--personal',action='store_true')
    g=ap.add_mutually_exclusive_group();g.add_argument('--all',action='store_true');g.add_argument('--paths',nargs='+')
    args=ap.parse_args(argv)
    sys.stdout.reconfigure(errors='backslashreplace')
    allow=set(load_list('ASUNA_PERSONAL_ALLOWLIST',ROOT/'tools'/'personal_scan_allow.txt'));deny=denylist();n=0
    for shown,key,raw in personal_sources(args):
        if SKIP.search(key):continue
        found={(0,c) for _,c in scan_lines(key,key,allow,deny)}
        if key.rsplit('/',1)[-1] not in LOCKFILES and b'\0' not in raw:
            try:found|=set(scan_lines(raw.decode('utf-8'),key,allow,deny))
            except UnicodeDecodeError:pass
        prefix='report-only:' if report_only(key) else ''
        for no,c in sorted(found):
            print(f'{prefix}{shown}:{no}:{c}')
            n+=not prefix
    print(f'personal-scan: {n} hit(s)')
    return 0

def main(argv=None):
    argv=sys.argv[1:] if argv is None else list(argv)
    if '--personal' in argv:return personal_scan(argv)
    secret_scan()

if __name__=='__main__':raise SystemExit(main())

#!/usr/bin/env python3
"""asuna-dsh-failure-scan 的离线自检：不连库、不发消息，只判这一枚技能装得对不对。

形状照 ADR-118 L2：依赖缺席就判红，不 stub、不塞替身模块。
退出码：0 = 全绿；1 = 有红；2 = 判不了（技能目录本身读不到）。

    python3 skills/asuna-dsh-failure-scan/check_skill.py
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_MD = os.path.join(HERE, 'SKILL.md')
SCAN = os.path.join(HERE, 'dsh_failure_scan.py')
CHANGELOG = os.path.join(HERE, 'CHANGELOG.md')
FILES = {'SKILL.md': SKILL_MD, 'dsh_failure_scan.py': SCAN, 'CHANGELOG.md': CHANGELOG}
DESCRIPTION_MAX = 1024

SECTIONS = ('## 何时用', '## 一条命令', '## 三组怎么分', '## 输出怎么读', '## 11 个读数面',
            '## 追得多久、什么时候会数少', '## 还没核实的', '## 相关')
DOC_RULES = (
    ('不相加：伴生句', 'attend.fallback'),
    ('不相加：伴生句口径', '不许相加'),
    ('不相加：note 是子集', 'note.refused'),
    ('静默那一类点名 missed_looks', 'missed_looks'),
    ('静默那一类点名无响应', 'provider.request 无响应'),
    ('代码级：traceback 面', 'provider.error'),
    ('代码级：非零退出', 'worker 非零退出'),
    ('代码级：崩溃', 'crashed'),
    ('代码级：任务没回执', '没回执'),
    ('全零形状', '只输出一行 `0`'),
    ('没读到不许冒充没有', '没读到'),
    ('偏移现读配对', '现读'),
    ('退出码 2 的读法', '判不了'),
    ('历史不进正文的指路', 'CHANGELOG'),
)
# 正文里不许出现「什么时候加的／为什么加的」那一类流水（这些是 CHANGELOG.md 的活）
HISTORY_MARKERS = ('当年', '来路', '历史形状', '现读实测', '刚过期的文字', '20 分钟')
DATE_STAMP = re.compile(r'\b\d{2}-\d{2}\b')
CONST_NAMES = ('AUDIT_WITH_ERROR', 'AUDIT_SILENT', 'AUDIT_CONTRAST', 'REPORT_FAILURES',
               'REPORT_SILENT', 'REPORT_CONTRAST', 'MISSING_CAUSES', 'STOP_FAILURES')


def read(path):
    with open(path, 'rb') as handle:
        return handle.read()


def frontmatter(text):
    """SKILL.md 头里的 YAML（只取顶层 key: value，够用不引库）。"""
    if not text.startswith('---'):
        return {}
    end = text.find('\n---', 3)
    block = text[3:end] if end > 0 else ''
    head = {}
    for line in block.splitlines():
        got = re.match(r'^([A-Za-z_][\w-]*):\s*(.*)$', line)
        if got:
            head[got.group(1)] = got.group(2).strip()
    return head


def module_constants(path):
    """不 import 就取脚本里的分组常量（import 要连库环境，自检不能依赖它）：ast 读字面量。"""
    tree = ast.parse(read(path).decode('utf-8'))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in CONST_NAMES:
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                out[node.targets[0].id] = None
    return out


def asuna_import_is_bare(path):
    """顶级 `from asuna import …` 必须存在、且不在 try 里、脚本也不动 sys.modules。"""
    tree = ast.parse(read(path).decode('utf-8'))
    top, inside_try = [], []
    for node in tree.body:
        for sub in ast.walk(node) if isinstance(node, (ast.Try,)) else ():
            if isinstance(sub, (ast.ImportFrom,)) and (sub.module or '').split('.')[0] == 'asuna':
                inside_try.append(sub.module)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] == 'asuna':
            top.append(node.module)
    code = read(path).decode('utf-8')
    return top, inside_try, ('sys.modules[' in code)


def private_words():
    """私人词表：现读现用（名字照 asuna-offline-selfchecks 的口径），拿不到就报 None。"""
    path = os.environ.get('ASUNA_PRIVATE_WORDS')
    if not path:
        try:
            from asuna import config as asuna_config
            path = os.path.join(str(asuna_config.DATA), 'private', 'personal-words.txt')
        except Exception as exc:                       # noqa: BLE001 读不到照实报，不假装扫过
            return None, None, '%s: %s' % (type(exc).__name__, exc)
    if not path or not os.path.isfile(path):
        return None, None, '读不到 %s' % path
    words = [line.strip() for line in open(path, encoding='utf-8', errors='replace')
             if line.strip() and not line.startswith('#')]
    return path, words, ''


def run(argv, env=None, timeout=120):
    got = subprocess.run(argv, capture_output=True, env=env, timeout=timeout)
    return (got.returncode, got.stdout.decode('utf-8', 'replace'), got.stderr.decode('utf-8', 'replace'))


def main():
    if not os.path.isdir(HERE):
        print('判不了：读不到技能目录 %s' % HERE)
        return 2
    results = []

    def check(name, ok, detail=''):
        results.append((name, bool(ok), str(detail)[:220]))

    for label, path in FILES.items():
        check('文件在：%s' % label, os.path.isfile(path), path)
    if not all(os.path.isfile(p) for p in FILES.values()):
        report(results)
        return 1

    texts = {label: read(path).decode('utf-8') for label, path in FILES.items()}
    for label, text in texts.items():
        check('%s 不带 CR（LF 唯一）' % label, '\r' not in text, 'CR %d 个' % text.count('\r'))

    head = frontmatter(texts['SKILL.md'])
    check('头里有 name', head.get('name') == os.path.basename(HERE), head.get('name', ''))
    check('头里有 description', bool(head.get('description')))
    check('description 不超长', len(head.get('description', '')) <= DESCRIPTION_MAX,
          '现 %d 字，上限 %d' % (len(head.get('description', '')), DESCRIPTION_MAX))
    check('家限定：头里没写 scene_kinds', 'scene_kinds' not in head, str(sorted(head)))

    body = texts['SKILL.md']
    for section in SECTIONS:
        check('正文有节：%s' % section, section in body)
    for label, literal in DOC_RULES:
        check('正文写了：%s' % label, literal in body, literal)
    # 历史尺只看散文：命令行样例里的 ISO 日期不算「什么时候加的」那一类流水
    prose = re.sub(r'```.*?```', '', body, flags=re.S)
    prose = re.sub(r'\d{4}-\d{2}-\d{2}', '某日', prose)
    hits = [marker for marker in HISTORY_MARKERS if marker in prose] + DATE_STAMP.findall(prose)
    check('正文不夹历史流水', not hits, '命中 ' + ', '.join(sorted(set(hits))[:6]))

    try:
        compile(texts['dsh_failure_scan.py'], SCAN, 'exec')
        check('脚本编译得过（内存里编，不落 .pyc）', True)
    except SyntaxError as exc:
        check('脚本编译得过（内存里编，不落 .pyc）', False, '%s 第 %s 行' % (exc.msg, exc.lineno))
    check('不写 .pyc 进技能目录', not any('__pycache__' in name for name in os.listdir(HERE)))

    constants = module_constants(SCAN)
    check('分组常量都取得到', all(name in constants and constants[name] for name in CONST_NAMES),
          str(sorted(constants)))
    missing = []
    for name in ('AUDIT_WITH_ERROR', 'AUDIT_SILENT', 'AUDIT_CONTRAST'):
        table = constants.get(name) or {}
        missing += ['%s（%s 组没进正文）' % (key, name) for key in table if str(key) not in body]
    for name in ('REPORT_FAILURES', 'REPORT_SILENT'):
        for key in (constants.get(name) or {}):
            short = str(key).split('（')[0]
            if short not in body and str(key) not in body:
                missing.append('%s（%s 没进正文）' % (key, name))
    check('每个失败型在正文点过名', not missing, '；'.join(missing[:6]))
    causes = set(constants.get('MISSING_CAUSES') or {})
    check('missed_looks 的 cause 五档正文都有', {'clash', 'timeout', 'unanswered', 'cut', 'error'} <= causes
          and all(cause in body for cause in causes), str(sorted(causes)))
    stops = set(constants.get('STOP_FAILURES') or {})
    check('非计划停机三样正文都有', {'killed', 'crashed', 'worker_down'} <= stops
          and all(word in body for word in stops), str(sorted(stops)))

    top, inside_try, touches_modules = asuna_import_is_bare(SCAN)
    check('依赖是真的：顶级 from asuna import', bool(top), str(top))
    check('依赖没被 try 包起来', not inside_try, str(inside_try))
    check('不塞替身模块（不动 sys.modules）', not touches_modules)

    env = dict(os.environ)
    probe = ("import sys; sys.modules['asuna'] = None; import runpy; "
             "runpy.run_path(r'%s', run_name='__main__')" % SCAN)
    code, out, err = run([sys.executable, '-c', probe], env=env)
    # ModuleNotFoundError 是 ImportError 的子类：两条字样都算「缺席就是红」，只认字面不认猜。
    check('依赖缺席时判红（不 stub 变绿）',
          code != 0 and ('ImportError' in err or 'ModuleNotFoundError' in err),
          'rc=%s %s' % (code, (err.strip().splitlines() or [''])[0]))

    code, out, err = run([sys.executable, SCAN, '--selfcheck'], env=env)
    check('脚本纯逻辑自检绿', code == 0 and '通过' in out, 'rc=%s %s' % (code, (out + err).strip()[:120]))

    cp = dict(env)
    cp['PYTHONIOENCODING'] = 'cp1252'
    code, out, err = run([sys.executable, SCAN, '--selfcheck'], env=cp)
    check('旧编码（cp1252）也能打中文', code == 0 and 'UnicodeEncodeError' not in err,
          'rc=%s %s' % (code, (err.strip().splitlines() or [''])[0]))

    path, words, why = private_words()
    check('私人词表可达', bool(words), why or path or '')
    if words:
        leaked = []
        for label, text in texts.items():
            leaked += ['%s 含表内词' % label for word in words if len(word) > 1 and word in text]
        check('技能文件不撞私人词表', not leaked, '；'.join(leaked[:4]))
        bare = []
        for label, text in texts.items():
            bare += ['%s 有孤立长数字 %s' % (label, got.group())
                     for got in re.finditer(r'(?<![\d.,])\d{7,11}(?![\d.,])', text)]
        check('没有裸长数字（号码类）', not bare, '；'.join(bare[:4]))
    else:
        check('技能文件不撞私人词表', False, '词表不可达就不算扫过')
        check('没有裸长数字（号码类）', False, '词表不可达就不算扫过')

    root = ''
    try:
        from asuna import config as asuna_config
        root = str(asuna_config.DATA)
    except Exception:                                   # noqa: BLE001 没装 asuna 时这格跳过取根
        pass
    inroot = [label for label, text in texts.items() if root and root in text]
    check('不写死本机数据根路径', not inroot, '；'.join(inroot))

    return report(results)


def report(results):
    failed = [name for name, ok, detail in results if not ok]
    for name, ok, detail in results:
        if not ok:
            print('FAIL %s  <- %s' % (name, detail))
    print('%d/%d 通过' % (len(results) - len(failed), len(results))
          + ('，失败：' + '、'.join(failed) if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, 'reconfigure'):
            _stream.reconfigure(encoding='utf-8')
    sys.exit(main())

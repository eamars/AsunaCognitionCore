"""The action brain's tasks: `TaskService` claims, leases, cancels and hands each result back to her, `ToolBroker`
checks and runs every tool call a task makes, and `Executor` runs one task in its workspace.

A hand-back shows her the report's first page (`report_pages`); she reads the rest with `task` op `page`.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import threading
import traceback
import uuid
from contextlib import contextmanager,nullcontext
import jsonschema
from . import clock
from .config import DATA,prompt_path,redact_text,excerpt
from .render import action_values
from . import answers, handover, machine_words, sandbox_backend, visibility
from .evidence import canonical,sha
from .ingress import program_group_context
from .sandbox import Sandbox, run_seconds
from .state import Store,Denied,Conflict,now
from .queue import database_effects_lock,RuntimeLease
from .integration import INTEGRATION_TOOLS, INTEGRATION_TOOL_BY_PROFILE, agent_home_profile, owner_profile
from .integration_import import IMPORT_TOOL_NAME, integration_gated
from . import outbound_media   # 导入图片时顺手登记成这一轮可引用的 image artifact（B7）
from . import outbound_files   # offer_file: a file of the task folder registered to send (ADR-092)
from .history_query import HISTORY_TOOL, HISTORY_TOOL_NAME
from .discussion_digest import DIGEST_TOOL, DIGEST_TOOL_NAME
from .development import DEVELOPMENT_TOOLS, DEVELOPMENT_NAMES, PERSONA_JOB_TOOLS
from .vision import (READ_IMAGE_TOOL, READ_IMAGE_TOOL_NAME, inline_summary as read_image_receipt,
                     route_filtered_tool_names, task_attachment_context)
from .records import episodes as episode_records
from .records import tasks as task_records
from .records import artifacts as artifact_records

# How many extra rounds one run takes for her words its turn ended before reading.
MESSAGE_ROUNDS = 3
TERMINAL={'DONE','RETURNED','PARTIAL','BLOCKED','CANCELLED','STALE','NEEDS_CHARACTER_DECISION','UNKNOWN'}


# The action brain's report as pages: a short first page, which the hand-back carries (her answer, 2026-10-21: the
# result leads, the rest is paged), then pages of REPORT_CHARS. Cuts are marked; the full records stay in the task.
REPORT_CHARS = 6000
FIRST_PAGE_CHARS = 2000          # the first page's usual length
FIRST_PAGE_MOST = 3000           # ... stretched to here so its section or a table is not cut in half
OBSERVATION_CHARS = 600
# Tool records on the first page: only for a task that changed or published something, the receipts that say whether
# it took (her answer: the risk is "it says it changed, and did not"); every record is on the report's last pages.
KEY_OBSERVATIONS = 2
CHANGING_TOOLS = ('write_file', 'offer_file', 'development_write', 'development_publish', 'integration_start', 'integration_stop',
                  'import_integration_artifact', 'generate_image', 'persona_job_run')
KEY_TOOLS = ('development_publish', 'integration_start', 'integration_stop', 'development_run', 'integration_test',
             'sandbox_run')
RECORDS_TITLE = '工具记录'
TITLE_CHARS = 24


# A line that starts a section of a report: a Markdown heading, a line that is all bold, 【…】, or 一、/1. numbering.
SECTION_START = re.compile(r'\n(?=#{1,6} |\*\*[^*\n]+\*\*[：:]?[ \t]*\n|【[^】\n]+】|[一二三四五六七八九十]+[、.．]|\d+[.、．] )')


def _row(text, pos):
    """Whether the line starting at `pos` is a Markdown table row."""
    end = text.find('\n', pos)
    return (text[pos:] if end < 0 else text[pos:end]).lstrip().startswith('|')


def _outside_table(text, cut, most):
    """A cut between two rows of a Markdown table moves to the table's end when that is within `most`, else to the
    table's start (a table cut in half costs more than a longer page, her answer 2026-10-21)."""
    if not 0 < cut < len(text) or text[cut - 1] != '\n':
        return cut
    before = text.rfind('\n', 0, cut - 1) + 1          # the line before the cut
    if not (_row(text, cut) and _row(text, before)):
        return cut
    end = cut
    while end < len(text) and _row(text, end):
        newline = text.find('\n', end)
        end = len(text) if newline < 0 else newline + 1
    if end <= most:
        return end
    start = before
    while start > 0:
        above = text.rfind('\n', 0, start - 1) + 1
        if not _row(text, above):
            break
        start = above
    return start or cut


def _cut(text, size, most):
    """Where a page of at most `size` (stretched to `most`) ends: before the last section that starts in its second
    half; else, when stretching is allowed, at the next section start before `most`; else at the last blank line, else
    the last line break, in its last fifth. Never in the middle of a table that fits."""
    window = text[:size]
    sections = [m.start() + 1 for m in SECTION_START.finditer(window, size // 2)]
    later = [m.start() + 1 for m in SECTION_START.finditer(text[:most], size)] if most > size else []
    if sections:
        cut = sections[-1]
    elif later:
        cut = later[0]
    else:
        blank, line = window.rfind('\n\n', int(size * 0.8)), window.rfind('\n', int(size * 0.8))
        cut = blank + 2 if blank > 0 else line + 1 if line > 0 else size
    return _outside_table(text, cut, most)


def report_pages(text, size=REPORT_CHARS, first=FIRST_PAGE_CHARS, most=FIRST_PAGE_MOST):
    """The action brain's report as pages: the first about `first` characters (up to `most` so a section or a table is
    not split), the others at most `size`. A section (her reason to read on) is not split where a page can end before
    it. The hand-back gives her the first page; task op page reads the others."""
    text, pages = str(text or ''), []
    limit, cap = first, most
    while len(text) > cap:
        cut = _cut(text, limit, cap)
        pages.append(text[:cut])
        text = text[cut:]
        limit = cap = size
    return pages + [text]


def page_title(page):
    """A page's first line as its title, without its Markdown marks."""
    line = next((row.strip() for row in str(page).splitlines() if row.strip()), '')
    line = re.sub(r'^#{1,6}\s+', '', line).strip().strip('*【】').strip().rstrip('：:').strip()
    return line if len(line) <= TITLE_CHARS else line[:TITLE_CHARS] + '…'


def page_note(task_id, page, pages, chars, titles=()):
    """What the end of a page says: where she is, how long the report is, what the pages after it are called, and how
    to turn the page. `titles`: the titles of the pages after this one."""
    if page >= pages:
        return '（第 %d/%d 页，报告到这里完了）' % (page, pages)
    after = '；后面：%s' % '、'.join('第 %d 页「%s」' % (page + 1 + i, title) for i, title in enumerate(titles)) if titles else ''
    return ('…（第 %d/%d 页，原文 %d 字%s；接着读用 task 的 page：task 写 %s，page=%d）'
            % (page, pages, chars, after, task_id, page + 1))


def key_observations(observations):
    """The tool records the first page keeps: none for a task that changed nothing; for one that did, the latest
    publish or start/stop receipt and the latest run (its test), else its latest changes."""
    if not any(item['tool'] in CHANGING_TOOLS for item in observations):
        return []
    picked = []
    for tool in KEY_TOOLS:
        hits = [item for item in observations if item['tool'] == tool]
        if hits and len(picked) < KEY_OBSERVATIONS:
            picked.append(hits[-1])
    return picked or [item for item in observations if item['tool'] in CHANGING_TOOLS][-KEY_OBSERVATIONS:]


def records_pages(observations, size=REPORT_CHARS):
    """Every tool record of the task as the report's last pages, each at most `size` characters like the report's own
    (a task makes up to a hundred and more calls: one page of them all ran past what a tool result carries inline);
    none when it made no call."""
    lines = ['- %s：%s\n' % (item['tool'], item['result_excerpt']) for item in observations]
    head = lambda first, last: RECORDS_TITLE + (
        '（共 %d 条，每条截到 %d 字）\n' % (len(lines), OBSERVATION_CHARS) if (first, last) == (1, len(lines)) else
        '（第 %d–%d 条，共 %d 条，每条截到 %d 字）\n' % (first, last, len(lines), OBSERVATION_CHARS))
    pages, first = [], 1
    for n in range(1, len(lines) + 1):
        if n == len(lines) or len(head(first, n + 1)) + sum(map(len, lines[first - 1:n + 1])) > size:
            pages.append(head(first, n) + ''.join(lines[first - 1:n]))
            first = n + 1
    return pages


def observations_of(store, task, shown=lambda value: value):
    """The task's finished tool calls, each as its tool and an excerpt of its result (a failed one: its error)."""
    return [{'source': item['_id'], 'tool': item['tool'],
             'result_excerpt': excerpt(item['error'] if item['state'] == 'FAILED' else
                                       json.dumps(shown(item['result']), ensure_ascii=False), OBSERVATION_CHARS)}
            for item in artifact_records.of_task(store, task['_id'], task.get('intent_revision'),
                                                 states=['DONE', 'FAILED']).rows()]


def task_pages(store, task, shown=lambda value: value):
    """The pages task op page reads: the report's, then its tool records."""
    pages = report_pages(((task.get('result') or {}).get('text')) or '')
    return pages + records_pages(observations_of(store, task, shown))


def bounded_result(result, records=()):
    if isinstance(result, dict) and isinstance(result.get('text'), str):
        # The ids of its tool records are audit, not something she reads: a count says how much was done. `facts`
        # repeats the report with every record's id (the stored result keeps it). `records`: the pages of tool records
        # that follow the report (records_pages).
        refs = result.get('artifact_refs')
        value = {key: item for key, item in result.items() if key not in ('artifact_refs', 'facts')}
        pages = report_pages(result['text'])
        titles = [page_title(page) for page in [*pages[1:], *records]]
        count = len(pages) + len(records)
        text = pages[0] if count == 1 else pages[0] + page_note(result.get('task_id'), 1, count, len(result['text']),
                                                                titles)
        return {**value, 'text': text, **({'report_pages': count} if count > 1 else {}),
                **({'tool_records': len(refs)} if isinstance(refs, list) else {})}
    return result



def _why_then(store,task):
    """Her thought when she handed the task over, as she wrote it (reasons.py, ADR-043); {} without one."""
    from . import reasons
    then=reasons.for_call(store,task.get('episode_id'),'task',task['_id'])
    return {'your_thought_then':then} if then else {}

class FeedbackStale(Denied):
    """The action result no longer authorizes a pending role continuation."""


def require_current_feedback(store, episode):
    if episode.get('episode_kind') != 'task_feedback':
        return
    # episode.task_id changes when feedback delegates another action. The
    # durable input remains the identity of the result being considered.
    source = message_records.get(store, 'in-' + episode['_id'])
    event = (source or {}).get('event', {})
    task = task_records.get(store, event.get('task_id'))
    scene = scene_records.get(store, episode['scene_id'])
    if (not task or not scene or task['state'] in ('CANCELLED', 'STALE', 'PAUSED')
            or task['intent_revision'] != event.get('intent_revision')
            or (task['scene_id'], task['requester_id'], task['scope_key'], task['policy_epoch']) !=
               (episode['scene_id'], episode['person_id'], episode['scope_key'], episode['policy_epoch'])
            or scene['policy_epoch'] != episode['policy_epoch']):
        raise FeedbackStale('FEEDBACK_TASK_STALE: 这回合依据的那件事已经变了（被叫停、暂停或改过交代），不是你出错；重试也一样：'
                            '把现在的情况照实说给对方')

# ADR-011 §4: the action brain's two ways to reach her. ask_character waits for her answer; report_progress
# only leaves a note she reads on her next turn (and it shows in their thread).
ASK_TOOL = {'name':'ask_character',
    'description':'Ask your talking half, where this task was given, for its judgment (what the brief meant, what you prefer there, a decision that belongs to it), and wait for the answer. Not a public reply, new task or permission grant. Ordinary implementation details and errors are yours to handle; do not ask before every step.',
    'parameters':{'question':{'type':'string','required':True}, 'context':{'type':'string','description':'Material it needs to judge, briefly'}}}
NOTE_IDEA_TOOL = {'name':'note_idea',
    'description':'Note an idea for improving yourself (a capability, a skill, a way of working) in your improvement notebook, in your own words, with why. Use it when something you see while working (including on the web) could be better: do not change it now. You review ideas in your self-improvement time. No one else\'s personal data.',
    'parameters':{'idea':{'type':'string','required':True},'why':{'type':'string','required':True}}}
PROGRESS_TOOL = {'name':'report_progress',
    'description':'Leave your talking half a short progress note on a long task, without waiting: it reads it on its next turn and decides whether to tell anyone. Use sparingly; the final report is your last message.',
    'parameters':{'note':{'type':'string','required':True}}}

def workspace_file(root, protected, op, args):
    """list_files / read_file / write_file inside the task folder; protected sources stay read-only. A refused or
    failed operation is a result she reads (TASK_OPERATION_FAILED with the reason), not an exception."""
    import traceback
    root = Path(root).resolve()
    given = str((args or {}).get('path', ''))[:200]

    def path(name):
        target = (root / str(name)).resolve()
        if not target.is_relative_to(root):
            raise PermissionError('PATH_DENIED: path %r 在任务文件夹外；写 /task 里的相对路径，例如 notes.txt 或 '
                                  'out/result.json（不带 /task/ 前缀，不用 ..）' % given)
        return target
    try:
        if op == 'list_files':
            return {'files': [{'path': p.relative_to(root).as_posix(), 'size': p.stat().st_size}
                              for p in sorted(root.rglob('*')) if p.is_file()]}
        target = path(args['path'])
        if op == 'read_file':
            if target.stat().st_size > 32768:
                raise ValueError('READ_LIMIT: %s 有 %d 字节，read_file 一次最多 32768 字节（32 KiB）；用 sandbox_run 跑 '
                                 'python3 脚本只打印要的那一段（文件路径作为单独的参数 /task/… 传入）'
                                 % (given, target.stat().st_size))
            return {'path': target.relative_to(root).as_posix(), 'text': target.read_text(encoding='utf-8')}
        if any(target == p or target.is_relative_to(p) for p in protected):
            raise PermissionError('PROTECTED_PATH: %s 是只读的原始资料，不能写；写到别的路径，例如 out/%s'
                                  % (target.relative_to(root).as_posix(), target.name))
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('w' if args.get('overwrite', False) else 'x', encoding='utf-8', newline='') as handle:   # her text as given
            handle.write(args['text'])
        return {'path': target.relative_to(root).as_posix(), 'text': target.read_text(encoding='utf-8'), 'written': True}
    except Exception as exc:
        return {'error': 'TASK_OPERATION_FAILED: ' + workspace_reason(exc, op, given),
                'execution': {'exit_code': 1, 'stderr': traceback.format_exc(limit=1)}}


class ToolFailed(RuntimeError):
    """A tool call that did not happen, for the reason its tool named: the call's error, in the words its FAILED
    artifact keeps."""


# A tool that answers {'error': …} (the workspace files, generate_image, render_svg, import_integration_artifact) says
# the operation did not happen. A picture still being drawn has not failed: calling again with its job fetches it.
NOT_FAILED = frozenset({'IMAGE_JOB_STILL_RUNNING'})
FAILURE_WORDS = ('error', 'note', 'generated', 'rendered', 'execution')


def failure_words(result):
    """The words of a definite failure a tool answered with, or None: its code, its note, then what else it named."""
    error = result.get('error') if isinstance(result, dict) else None
    if not isinstance(error, str) or not error or error in NOT_FAILED:
        return None
    named = {key: value for key, value in result.items() if key not in FAILURE_WORDS and value is not None}
    words = ([result['note']] if isinstance(result.get('note'), str) and result['note'] else []) + (
        [json.dumps(named, ensure_ascii=False)] if named else [])
    return error + (': ' + ' '.join(words) if words else '')


def workspace_reason(exc, op, given):
    """Why a file operation failed and what to do, in her words (the traceback stays in stderr)."""
    if isinstance(exc, KeyError):
        return '%s 缺参数 %s；照工具说明补上' % (op, exc.args[0] if exc.args else '')
    if isinstance(exc, FileExistsError):
        return '%s 已经存在；要替换就加 overwrite=true，要保留就换个文件名' % given
    if isinstance(exc, FileNotFoundError):
        return '没有 %s；先用 list_files 看 /task 里有哪些文件，path 照抄' % given
    if isinstance(exc, IsADirectoryError) or isinstance(exc, PermissionError) and getattr(exc, 'errno', None):
        return '%s 是文件夹或打不开的文件；path 要指向一个文件，用 list_files 看有哪些' % given
    if isinstance(exc, UnicodeDecodeError):
        return '%s 不是 UTF-8 文本，read_file 读不了；用 sandbox_run 跑 python3 脚本按二进制处理' % given
    if isinstance(exc, TypeError) and op == 'write_file':
        return 'text 要是字符串；把内容写成一段字符串（JSON 先自己序列化）'
    message = str(exc)
    if message[:1].isupper() and '_' in message.split(':', 1)[0]:
        return message
    return '%s（%s: %s）；换个做法，或把这一步没做成写进结果' % (op, type(exc).__name__, message[:200])


def home_env(store):
    """What a home task's commands are given besides the sandbox's own: her name on commits, and the database and her
    time zone for asuna.dbread."""
    from . import dbread
    from .persona_model import timezone as persona_timezone
    from .render import model_and_policy
    persona=(store.config.get('chat') or {}).get('persona')
    try:
        zone=persona_timezone(*model_and_policy(store,persona),store.config)[0] if persona else None
    except Exception:
        zone=None
    return {**sandbox_backend.git_identity(store.config),**dbread.environment(store.config,zone)}


SANDBOX_TOOL={'name':'sandbox_run','description':'Run argv in the task folder under the Host sandbox: it may write only there. Commands are native to the machine the Host runs on (on Windows there is no sh or Linux tools: write the work as a python3 script; python3 is Python 3.12, with httpx, websockets, paramiko, pymongo, PyYAML and PIL (Pillow) importable; read the database with asuna.dbread, skill asuna-database). An argument /task or /task/… names the task folder. git and ssh work with the keys and logins of the user the Host runs as; what you commit carries your own name. 30 s (timeout: up to 600), 256 KiB output; a stopped command returns its output so far. credentials: names from the program notes\' credentials; their environment variables are set for this one command only (a script reads os.environ). Values are never shown: output containing one comes back hidden. Never write a credential value into a script, file, brief or report.', 'parameters':{'argv':{'oneOf':[{'type':'array','items':{'type':'string'}},{'type':'string'}],'required':True},'credentials':{'oneOf':[{'type':'array','items':{'type':'string'}},{'type':'string'}],'description':'credential names for this command (home tasks only)'},'timeout':{'type':'integer','description':'seconds, up to 600'}}}

WORKSPACE_TOOLS = [
    {'name': 'list_files', 'description': 'List files inside the authorized workspace /task.', 'parameters': {}},
    {'name': 'read_file', 'description': 'Read a UTF-8 file inside /task (up to 32 KiB), or page this action session’s native tool spill using byte offset/limit.', 'parameters': {'path': {'type': 'string', 'required': True}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}}},
    {'name': 'write_file', 'description': 'Create a UTF-8 file inside /task. Existing files require explicit overwrite=true. Protected paths are read-only.', 'parameters': {'path': {'type': 'string', 'required': True}, 'text': {'type': 'string', 'required': True}, 'overwrite': {'type': 'boolean'}}},
    outbound_files.OFFER_FILE_TOOL,
    SANDBOX_TOOL,
]

# These are DSH-owned action-agent tools, not ToolBroker capabilities. The
# names are persisted with each task grant so native session visibility follows
# the same task boundary as the existing host tools.
ACTION_DSH_CAPABILITIES = ('skill', 'todo_write', 'web_search', 'web_fetch')
IDLE_MINUTES = 30          # the action route's idleMinutes when empty (ADR-053)
FRESH_REPORT_CHARS = 20000


def idle_minutes(config, tier=None):
    """After this long unused, a task's continuation starts a fresh action context (ADR-053): a cost setting of the
    action route, following how long its provider keeps a cached prefix; a job that ran at 高 uses 高's own (ADR-075)."""
    key = 'action_high_idle_minutes' if tier == '高' else 'action_idle_minutes'
    return int((config or {}).get(key) or IDLE_MINUTES)


def last_used(task):
    """When the action context of a finished task was last used."""
    from datetime import datetime
    return datetime.fromisoformat(task.get('finished_at') or task.get('started_at') or task['created_at'])


def opening_text(store, task):
    """The action brain's first words for a task: her brief; a continuation's new words; after the idle limit
    (ADR-053) a fresh context told so, with the last report."""
    brief=task.get('brief') or task['goal']
    text=('你接着交代：\n' if task.get('continues_task_id') else '')+brief
    fresh=task.get('fresh_context')
    if task.get('continues_task_id') and fresh:
        prev=task_records.get(store, fresh['report_of'], fields=['result.text']) or {}
        report=((prev.get('result') or {}).get('text') or '').strip()
        shown=report[:FRESH_REPORT_CHARS]
        text=('这是一份新开的上下文：这件事上一趟已经闲了约 %d 分钟，之前的工具输出都不在这里了。下面是上一趟交回的报告'
              '%s；要用到的东西重新取，不要凭报告的印象补。\n\n—— 上一趟的报告 ——\n%s\n\n你接着交代：\n'
              % (fresh['after_minutes'], '' if len(report)<=len(shown) else '（共 %d 字，这里是前 %d 字）'%(len(report),len(shown)),
                 shown or '（上一趟没有留下报告）'))+brief
    return text

def place_words(store, scene_id):
    """Where a queued task came from, coarse: never a group's or a person's name."""
    from . import channel_kinds
    if scene_id == (store.config.get('chat') or {}).get('scene_id'):
        return '家里'
    if channel_kinds.home(scene_id):
        return '家里的另一条线'
    scene = scene_records.get(store, scene_id, fields=['kind']) or {}
    return '一个群' if scene.get('kind') == 'group' else '一个私聊'


def queue_words(store, task_id):
    """What is ahead of this task for the one action worker (ADR-053), always said, an empty queue too."""
    from datetime import datetime
    mine = task_records.get(store, task_id, fields=['created_at']) or {}
    ahead = [row for row in task_records.in_states(store, ['RUNNING', 'READY'], besides=task_id).rows(
                 fields=['state', 'scene_id', 'started_at', 'created_at'])
             if row['state'] == 'RUNNING' or (row.get('created_at') or '') < (mine.get('created_at') or '~')]
    if not ahead:
        return '前面没有排着的，马上开始。'
    parts = []
    for row in ahead:
        if row['state'] == 'RUNNING':
            started = row.get('started_at') or row.get('created_at')
            minutes = int((clock.now() - datetime.fromisoformat(started)).total_seconds() // 60) if started else 0
            parts.append('正在跑的一件来自%s，已经跑了约 %d 分钟' % (place_words(store, row['scene_id']), minutes))
    waiting = [row for row in ahead if row['state'] == 'READY']
    if waiting:
        parts.append('还有 %d 件在排（来自%s）' % (len(waiting), '、'.join(dict.fromkeys(place_words(store, row['scene_id'])
                                                                          for row in waiting))))
    return '前面有 %d 件：%s。行动脑一次只做一件，轮到它才开始。' % (len(ahead), '；'.join(parts))

WORKSPACE_TOOLS.append(HISTORY_TOOL)
# P1-c：按需群整理与历史查询共用同一只读入口规则（场景来自任务绑定，参数不换范围）。
WORKSPACE_TOOLS.append(DIGEST_TOOL)
WORKSPACE_TOOLS.append(ASK_TOOL)
WORKSPACE_TOOLS.append(PROGRESS_TOOL)
WORKSPACE_TOOLS.append(NOTE_IDEA_TOOL)
# 看图（Pull 模式）：定义与实现同处注册；是否进入某个任务的能力清单，取决于那条行动路由
# 是否声明了图片输入（见 route_filtered_tool_names），不按模型名字猜。
WORKSPACE_TOOLS.append(READ_IMAGE_TOOL)
from .received_files import RECEIVED_FILE_TASK_TOOL, TOOL_NAME as RECEIVED_FILE_TOOL_NAME
from .records import scenes as scene_records
from .records import messages as message_records
WORKSPACE_TOOLS.append(RECEIVED_FILE_TASK_TOOL)


def stale_reason(task,current,scene):
    """Why a call's task no longer holds its authority, as the program sees it."""
    if not current:return '这个任务已经不在了'
    if current['state']=='CANCELLED':return '这个任务已经被取消了'
    if current['state']=='PAUSED':return '这个任务因宿主重启暂停了'
    if current['intent_revision']!=task['intent_revision']:return '这个任务的交代改了（新的交代取代了这一版）'
    if scene and scene['policy_epoch']!=task['policy_epoch']:return '这个对话的权限换了一版'
    if current['state']!='RUNNING':return '这个任务已经结束了（%s）'%current['state']
    return '这个任务已经由另一次执行接手'


class TaskService:
    def __init__(self,store:Store,crash=lambda point:None):
        self.store,self.crash=store,crash
        self.lock=database_effects_lock(store.name)
        self.on_fenced=None
        self.on_collab=None

    def collab(self, task, kind, data, entry_id):
        """One entry of the two brains' thread in her conversation (coordinator.collab); a view only."""
        if self.on_collab:
            try:
                self.on_collab(task,{'id':entry_id,'kind':kind,'at':now(),**data})
            except Exception as exc:
                self.store.audit(task['_id'],'collab.failed',{'error':str(exc)[:300]},task['scope_key'])

    def _notify_fenced(self, task, reason):
        if self.on_fenced:
            self.on_fenced(task, reason)
        return task

    def claim(self,task_id):
        with self.lock:
            task=task_records.get(self.store, task_id)
            if task['state']!='READY':raise Conflict('TASK_NOT_READY')
            task=task_records.save(self.store, {**task,'state':'RUNNING','lease_owner':str(uuid.uuid4()),'fencing_token':task['fencing_token']+1,'lease_expires_at':__import__('time').time()+600,
                'started_at':now()},expected=task['revision'],stream=task_id)
            return task

    def valid(self,task,*,state='RUNNING'):
        current=task_records.get(self.store, task['_id'])
        scene=scene_records.get(self.store, task['scene_id'])
        if not current or current['state']!=state or current['intent_revision']!=task['intent_revision'] or current['fencing_token']!=task['fencing_token'] or scene['policy_epoch']!=task['policy_epoch']:
            raise Denied('STALE_TASK_FENCE: '+stale_reason(task,current,scene)+'，这次调用不算数，也没有执行；不是你出错，重试也一样：'
                         '停下，不再调工具，在报告里写做到了哪里')
        if state=='RUNNING' and current.get('lease_expires_at',0)<=__import__('time').time():
            raise Denied('TASK_LEASE_EXPIRED: 这个任务的执行租约过期了（10 分钟没有续上），这次调用没有执行；不是参数的问题，'
                         '重试也一样：停下，在报告里写做到了哪里')
        return current

    def cancel(self,task_id,reason='user_cancelled',*,person_id=None,operator=False):
        with self.lock:
            task=task_records.get(self.store, task_id)
            if not task or not(operator or person_id==task['requester_id']):raise Denied('TASK_CANCEL_NOT_AUTHORIZED')
            if not task.get('execution_binding'):
                task={**task,'execution_binding':f"task:{task['_id']}:{task['scope_key']}:{task['policy_epoch']}:{task['intent_revision']}"}
            cancelled=task_records.save(self.store, {**task,'state':'CANCELLED','intent_revision':task['intent_revision']+1,'fencing_token':task['fencing_token']+1,'cancel_reason':reason,'feedback_state':'SUPPRESSED'},expected=task['revision'],stream=task_id)
        self.collab(cancelled,'status',{'state':'stopped','reason':reason},'status:'+task_id+':cancelled')
        return self._notify_fenced(cancelled, 'task_cancelled')

    def pause_for_restart(self, task_id):
        """Preserve old work and receipts; only a new local request can resume."""
        with self.lock:
            task = task_records.get(self.store, task_id)
            if not task or task['state'] in ('CANCELLED', 'STALE', 'PAUSED'):
                return task
            paused = task_records.save(self.store, {**task, 'state': 'PAUSED', 'pause_reason': 'host_restart',
                'paused_at': now(), 'paused_state': task['state'], 'paused_feedback_state': task.get('feedback_state'),
                'feedback_state': 'PAUSED', 'fencing_token': task['fencing_token'] + 1,
                'execution_binding': task.get('execution_binding') or
                    f"task:{task['_id']}:{task['scope_key']}:{task['policy_epoch']}:{task['intent_revision']}"},
                expected=task['revision'], stream=task_id)
        # Without it the thread would still read as queued or running (ADR-011 §7.1).
        self.collab(paused,'status',{'state':'paused','reason':'host_restart'},'status:'+task_id+':paused:'+str(paused['fencing_token']))
        return paused

    @contextmanager
    def keepalive(self,task,interval=30):
        """Renew only this live worker's fenced lease while it waits on a model."""
        stopped=threading.Event();errors=[]
        def renew():
            while not stopped.wait(interval):
                try:
                    with self.lock:
                        current=self.valid(task)
                        task_records.save(self.store, {**current,'lease_expires_at':__import__('time').time()+600},expected=current['revision'],stream=task['_id'])
                except Exception as exc:errors.append(exc);return
        worker=threading.Thread(target=renew,daemon=True);worker.start()
        def check():
            if errors:raise RuntimeError('TASK_LEASE_RENEWAL_FAILED') from errors[0]
        try:yield check
        finally:stopped.set();worker.join(5)

    def feedback(self,task,coordinator,short=False,again=False):
        """Hand a finished task's result back to her in a turn of her own. `again`: the watchdog hands back a result
        whose earlier hand-back was lost; `short`: only her brief, the report's words and when it finished (ADR-030)."""
        current=task_records.get(self.store, task['_id'])
        scene=scene_records.get(self.store, task['scene_id'])
        handed=current.get('feedback_state')
        if current['state'] not in TERMINAL or handed in (*handover.TAKEN,None) or handed!='READY' and not again:return None
        if current['state'] in ('CANCELLED','STALE') or current['intent_revision']!=task['intent_revision'] or scene['policy_epoch']!=task['policy_epoch']:
            if current['state'] in handover.FINISHED:
                # Its scene changed under it: this result can never be handed back, so nothing waits for it.
                with self.lock:
                    latest=task_records.get(self.store, task['_id'])
                    task_records.save(self.store, {**latest,'feedback_state':'SUPPRESSED'},expected=latest['revision'],stream=latest['_id'])
            return None
        original=episode_records.get(self.store, task['episode_id'])
        # Outside home what she reads of the result holds nothing of the machine (ADR-050, machine_words); home and
        # the stored result keep it as it is.
        outside=visibility.session_class(self.store.config,self.store,scene,task['requester_id'])!=visibility.OWNER_PRIVATE
        shown=machine_words.clean if outside else (lambda value:value)
        ep=None
        if not short and current.get('feedback_episode'):
            ep=episode_records.get(self.store, current['feedback_episode'])
        if not ep:
            ep=episode_records.of_source(self.store,handover.result_event_id(task,short),kind='task_feedback',
                                         scene=task['scene_id'])
        continuing=bool(ep)
        if ep:
            if (ep.get('episode_kind')!='task_feedback' or ep.get('task_id')!=task['_id']
                    or ep.get('intent_revision')!=task['intent_revision'] or ep['scene_id']!=task['scene_id']
                    or ep['person_id']!=task['requester_id'] or ep['policy_epoch']!=task['policy_epoch']):
                raise Denied('FEEDBACK_EPISODE_MISMATCH')
        else:
            depth=original.get('delegation_depth',0)+1
            observations=[] if short else observations_of(self.store,task,shown)
            event={'event_id':handover.result_event_id(task),'scene_id':task['scene_id'],'person_id':task['requester_id'],'text':'你交给行动脑的「'+(task.get('title') or task['goal'])+'」有了结果。它的报告是自然语言；工具记录才是执行事实。任务返回不等于目标完成，也不规定你的感受或要说什么；要接着做就用 task 的 message。','episode_kind':'task_feedback','task_id':task['_id'],'intent_revision':task['intent_revision'],'delegation_depth':depth,'trusted_context_events':[{'kind':'task_result','task':task['_id'],'title':task.get('title') or task['goal'],**_why_then(self.store,task),'value':shown(bounded_result(task.get('result'),records_pages(observations))) or {'state':current['state'],'error':current.get('failure_type'),'uncertainties':['上次操作结果未确定；可继续核实，不能盲目重做。']}}]}
            source=message_records.get(self.store,task['raw_input_refs'][0],scope=task['scope_key'],epoch=task['policy_epoch'])
            # The session the task belongs to (home's own for one begun on an errand or in a reflection).
            if task.get('native_session_id') or original.get('native_session_id'):
                event['native_session_id']=task.get('native_session_id') or original['native_session_id']
            if task.get('errand_place'):
                event['text']+='这件是差事带出来的，托话的那边是 %s（errand 的 place 照抄它）。'%task['errand_place']
            if group := program_group_context(source):
                event['group_context'] = group
            # 原样回传那个值：窄授权任务的反馈回合也要拿得到它，否则 task 的 message 会被判成授权不一致。
            if task.get('integration_profile'): event['integration_profile'] = task['integration_profile']
            if short:
                event.update(self._short_event(task,current,shown,source))
            else:
                # When it ran (a result handed back late describes that time); stored UTC, her turn shows it local.
                # Tool records on the first page only where the task changed something (key_observations); all of
                # them are on the report's last pages.
                event['trusted_context_events'][0].update(original_input=(source or {}).get('text'),
                    original_input_id=(source or {}).get('_id'),brief=task.get('brief') or task['goal'],
                    **({'observations':key} if (key:=key_observations(observations)) else {}),
                    observations_total=len(observations),finished_at=current.get('finished_at'))
            self.handback(task,'handing',short=short)
            ep=coordinator.ingest(event,persona=original['persona'])
        if ep['state'] in (('FAILED_PROTOCOL',) if continuing else ()) or ep['state'] in ('PREPARED','TURN','SPEAK_ACCEPTED','INTERRUPTED'):
            ep=coordinator.advance(ep['_id'])
        with self.lock:
            latest = task_records.get(self.store, task['_id'])
            if (latest['state'] in ('CANCELLED', 'STALE', 'PAUSED')
                    or latest['intent_revision'] != task['intent_revision']):
                return ep  # Never overwrite a cancellation/revision while inference was in flight.
            task_records.save(self.store, {**latest,'feedback_state':'READY' if ep['state']=='FAILED_PROTOCOL' else 'DELIVERED' if ep['state']=='COMMITTED' else ep['state'],'feedback_episode':ep['_id']},expected=latest['revision'],stream=latest['_id'])
        if ep['state']=='COMMITTED':
            self.handback(task,'taken',short=short)
        if ep['state']=='COMMITTED' and original['state']=='WAITING_TASK':
            episode_records.save(self.store, {**original,'state':'COMMITTED','feedback_episode':ep['_id']},expected=original['revision'],stream=original['_id'])
        return ep

    def _short_event(self,task,current,shown=lambda value:value,source=None):
        """The short hand-back (ADR-030 D4): her brief, the request it answers, the report's words (a cut says so) and
        when the run finished, without the tool records."""
        result=current.get('result') or {}
        text=result.get('text') or ''
        pages=task_pages(self.store,task)
        report=shown(report_pages(text)[0])
        if len(pages)>1:
            report+=('…（只给了第一页，原文 %d 字共 %d 页；接着读用 task 的 page：task 写 %s，page=2）'
                     % (len(text),len(pages),task['_id']))
        value={'kind':'task_result','task':task['_id'],'title':task.get('title') or task['goal'],'short':True,
               **_why_then(self.store,task),'brief':task.get('brief') or task['goal'],
               'original_input':(source or {}).get('text'),'original_input_id':(source or {}).get('_id'),'report':report,
               **({'report_pages':len(pages)} if len(pages)>1 else {}),
               'finished_at':current.get('finished_at'),'uncertainties':shown(result.get('uncertainties') or [])}
        return {'event_id':handover.result_event_id(task,True),
                'text':'你交给行动脑的「'+(task.get('title') or task['goal'])+'」早就有了结果，但之前没能交到你手上；这是补交的短版：'
                       '只有托付那句、你的交代、它的报告原文和跑完的时间，没有工具记录。报告写的是跑完那时的情况，不一定是现在；工具记录才是执行事实，'
                       '要核实或接着做就用 task 的 message。',
                'trusted_context_events':[value]}

    def handback(self,task,state,cause=None,error=None,short=False,final=False):
        """Where the task's result stands on its way back to her character brain, for the thread's view: handing,
        taken (her turn on it finished) or missed (cause: report, turn or restart; final once the watchdog stops)."""
        current=task_records.get(self.store, task['_id'], fields=['handback', 'state']) or {}
        record=current.get('handback') or {}
        # The run's outcome travels with it: her conversation may have moved to a new session since the run's status.
        outcome='failed' if current.get('state') in ('BLOCKED','UNKNOWN') else 'done'
        data={'state':state,'outcome':outcome,**({'cause':cause} if cause else {}),**({'error':error} if error else {}),
              **({'short':True} if short else {}),**({'final':True} if final else {})}
        attempt='%s%s' % (record.get('failures',0),':short' if short else '')
        self.collab(task,'handback',data,'handback:%s:%s:%s:%s' % (task['_id'],task['intent_revision'],state,attempt))

    def record_handback_failure(self,task_id,short):
        """A hand-back failed before her turn (ADR-030 D4): counted, so the watchdog knows what to try next."""
        with self.lock:
            current=task_records.get(self.store, task_id)
            record=dict(current.get('handback') or {})
            if short:record['short_failed']=True
            else:record['failures']=record.get('failures',0)+1
            return task_records.save(self.store, {**current,'handback':record},expected=current['revision'],stream=task_id)

    def give_up_handback(self,task):
        """Nothing more is tried: the result stays stored, she sees it could not be handed over, the developer is told."""
        from . import developer_inbox
        with self.lock:
            current=task_records.get(self.store, task['_id'])
            if current.get('feedback_state') in handover.TAKEN:
                return current
            given=task_records.save(self.store, {**current,'feedback_state':'UNDELIVERABLE'},expected=current['revision'],stream=task['_id'])
        cause=handover.cause(self.store,given)
        try:
            developer_inbox.leave(self.store,self.store.config['chat']['persona'],developer_inbox.NOTE,
                ('[程序] 行动结果交不回给她：任务 %s（%s），原因 %s；全文和短版都试过了。报告还存在任务里。'
                 % (task['_id'],task.get('title') or task['goal'],cause))[:developer_inbox.TEXT_CHARS],
                key=['handback-undeliverable',task['_id'],task['intent_revision']],source={'by':'program','task_id':task['_id']})
        except ValueError as exc:
            self.store.audit(task['_id'],'handback.developer_note_refused',{'error':str(exc)[:300]},task['scope_key'])
        self.handback(given,'missed',cause,final=True)
        return given

    def close_orphan(self,task):
        """A run whose lease expired while no one runs it (ADR-030 D2): closed as not finished, handed back as such."""
        with self.lock:
            current=task_records.get(self.store, task['_id'])
            if not current or current['state']!='RUNNING' or current['fencing_token']!=task['fencing_token']:
                return None
            refs=[row['_id'] for row in artifact_records.of_task(self.store,task['_id'],current['intent_revision'],state='DONE').rows(fields=['_id'])]
            result={'task_id':task['_id'],'intent_revision':current['intent_revision'],'artifact_refs':refs,
                    'text':'行动脑这次执行中断了：它的进程不在了，没有交回报告。工具记录是它中断前做到的。',
                    'facts':[],'uncertainties':['中断前已发起而没有回执的操作须先核实，不可盲目重做。']}
            closed=task_records.save(self.store, {**current,'state':'BLOCKED','failure_type':'ORPHANED','result':result,
                'finished_at':now(),'feedback_state':'READY','fencing_token':current['fencing_token']+1},
                expected=current['revision'],stream=task['_id'])
        self.collab(closed,'status',{'state':'failed'},'status:'+task['_id']+':orphaned')
        return closed


# Which tasks are given which tools (ADR-053): the one table both refusing layers (the plugin's guard and this
# broker) read their words from, so neither brain gets two versions to guess a motive from.
GIVEN_TO = (
    (lambda tool: tool == 'sandbox_run', '只给家里的对话（家里·私聊、主人私聊、agent 线、peer 线）交的任务'),
    (lambda tool: tool.startswith('development_') or tool.startswith('persona_job'),
     '只给家里的对话里这几种回合交的任务：有人说话叫起来的、你的自我改进、你自己的计划到点、家里另一条线的便条叫起来的'
     '（自我开发要开着）'),
    (lambda tool: tool.startswith('integration') or tool == 'import_integration_artifact',
     '只给主人在家里交的任务（集成要开着）；agent 线交的只有 integration_start 和 integration_status'),
    (lambda tool: tool == 'generate_image', '生图服务开着时，每个任务都有'),
)


def capability_refusal(store, task, tool):
    """The one sentence for a tool this task was not given: who gets it, where this task came from, retrying won't help."""
    given = next((words for match, words in GIVEN_TO if match(str(tool))), '这件任务交的时候没给它')
    return ('CAPABILITY_DENIED: 这个任务没有 %s：它%s；这件是%s交的。不是参数的问题，重试也一样：'
            '要用它就在报告里写明，让说话的那一半在给它的地方另交一件。' % (str(tool)[:60], given, place_words(store, task['scene_id'])))


DEVELOPMENT_GRANT=('DEVELOPMENT_GRANT_REQUIRED: 这个任务没有自我开发授权，development_* 和 persona_job_run 用不了；'
                   '重试也一样，需要改代码就在报告里说明')
UNAVAILABLE='不是参数的问题，重试也一样：不用它能做的先做，没做成的写进报告'


def given_text(value):
    if isinstance(value,str):return '给的是 %d 字' % len(value) if value.strip() else '给的是空的'
    return '没给' if value is None else '给的是 %s' % type(value).__name__


class ToolBroker:
    """Trusted host process; no DB/publication credentials enter model or child tools."""
    def __init__(self, service:TaskService, evidence):
        # Native Host tools use the private worker connection; there is no HTTP broker.
        self.service,self.store=service,service.store
        self.evidence=evidence          # the worker's: the data child's records are kept here (data_children.py)
        self.bindings={}

    @property
    def specs(self):
        return ToolBroker.catalogue()

    @staticmethod
    def catalogue():
        """Every tool the action brain can be given."""
        from .image_generation import GENERATE_IMAGE_TOOL
        from .svg_render import RENDER_SVG_TOOL
        from .private_words import PRIVATE_WORDS_TOOL
        from . import param_names
        tools = [*WORKSPACE_TOOLS, GENERATE_IMAGE_TOOL, RENDER_SVG_TOOL, PRIVATE_WORDS_TOOL, *INTEGRATION_TOOLS, *DEVELOPMENT_TOOLS,
                 *PERSONA_JOB_TOOLS]
        # Shown by their new names (ADR-060); a call is mapped back before the tool reads it (call below).
        return [{**tool, 'parameters': param_names.shown(tool['name'], tool['parameters'])} for tool in tools]

    def bind(self,session,task,workspace):
        from .grants import workspace_grant
        grant=workspace_grant(self.store.config,task['scene_id'],task['requester_id'])
        if Path(workspace).resolve()!=Path(grant['workspace']).resolve():raise Denied('WORKSPACE_GRANT_MISMATCH')
        protected=[Path(workspace)/p for p in grant.get('read_only_paths',[])]
        self.bindings[session]=(task,Sandbox(workspace,protected,allowed_root=Path(grant['workspace']),config=self.store.config))

    def call(self,session,call_id,tool,args):
        from .tool_args import normalize
        from . import param_names
        args,old_names=param_names.inbound(tool,args)  # the new names mapped to what the tool reads (ADR-060)
        args,adjusted=normalize(tool,args)          # what she plainly meant; said back in the result (tool_args.py)
        adjusted=[*old_names,*adjusted]
        with self.service.lock:
            if session not in self.bindings:
                raise Denied('UNBOUND_EXECUTOR: 这个行动会话没有绑定到任务（任务已结束或宿主重启过）；不是参数的问题，'
                             '重试也一样：停下，在报告里写做到了哪里')
            task,sandbox=self.bindings[session]
            current=self.service.valid(task)
            if tool not in current['allowed_capabilities'] or (tool in DEVELOPMENT_NAMES and not current.get('development_grant')):
                raise Denied(capability_refusal(self.store,current,tool))
            if integration_gated(tool):
                # 值在允许集内，而且这个工具在该 profile 的白名单里。每次调用都从任务行重算这个场景这会儿
                # 还配不配（照 native_worker 重算 session_class 的思路），写入那一刻的结论不算数。
                profile = current.get('integration_profile')
                allowed = INTEGRATION_TOOL_BY_PROFILE.get(profile)
                if not allowed:
                    raise Denied('INTEGRATION_TASK_GRANT_REQUIRED: %s 只给继承集成授权（owner 或 agent_home）的'
                                 '任务用，这个任务没有；重试也一样，在报告里写明需要它' % tool)
                if tool not in allowed:
                    raise Denied('INTEGRATION_TASK_GRANT_REQUIRED: %s 不在 %s 授权的集成工具里（这个授权用得上的是 '
                                 '%s）；重试也一样，在报告里写明需要它' % (tool, profile, '、'.join(allowed)))
                # owner 照旧走 owner_profile；agent_home 走场景复核（kind==agent + 集成开着 + 绑定本机聊天）。
                (owner_profile if profile == 'owner' else agent_home_profile)(
                    self.store.config, current['scene_id'], current['requester_id'])
                if not getattr(self, 'integration', None):
                    raise Denied('INTEGRATION_RUNNER_UNAVAILABLE: 集成运行器这会儿没启动（宿主没有沙箱或没装配它）；'+UNAVAILABLE)
            key='tool-'+sha(canonical([task['_id'],task['intent_revision'],call_id]))
            input_hash=sha(canonical([tool,args]))
            old=artifact_records.get(self.store,key)
            if old:
                if old['input_hash']!=input_hash:
                    raise Denied('CALL_ID_REUSED: 这个调用编号已经用在另一组参数的 %s 调用上；不是参数写错，'
                                 '重新发起一次调用（会换新编号）' % old.get('tool'))
                if old['state']=='FAILED':
                    raise ToolFailed(old['error'])
                if old['state']!='DONE':
                    raise Denied('TOOL_DELIVERY_UNKNOWN: 同一个调用之前开始过但还没有回执（可能还在进行，或中途断过），不知道做没做成；'
                                 '不要盲目重做：先查看它该留下的结果（list_files、读文件等）再决定')
                return old['result']
            task_records.save(self.store, {**current,'tool_steps':current['tool_steps']+1,'lease_expires_at':__import__('time').time()+600},expected=current['revision'],stream=task['_id'])
            artifact=artifact_records.save(self.store,{'_id':key,'scope_key':task['scope_key'],'task_id':task['_id'],'intent_revision':task['intent_revision'],'tool':tool,'args':args,'input_hash':input_hash,'state':'INTENT'},stream=task['_id'])
            self.service.crash('before_tool')
        # Integration callbacks, role consultations and commands can wait on things outside this process.
        # Never hold the effects lock across such a wait: every outbox claim (her words to QQ, the agent lines)
        # and every cancellation needs it. A later cancellation still fences new calls; recording this accepted
        # call cannot revive the task.
        with (nullcontext() if integration_gated(tool) or tool in DEVELOPMENT_NAMES or tool=='ask_character'
                  or tool in ('generate_image','render_svg','private_words','sandbox_run','offer_file') or tool==HISTORY_TOOL_NAME or tool==DIGEST_TOOL_NAME or tool==READ_IMAGE_TOOL_NAME or tool==RECEIVED_FILE_TOOL_NAME else self.service.lock):
            if not integration_gated(tool):self.service.valid(task)
            if tool=='persona_job_run':
                if not task.get('development_grant'):raise Denied(capability_refusal(self.store,task,tool))
                result=self.persona_jobs(task,args)
                with self.service.lock:self.service.valid(task)
            elif tool in DEVELOPMENT_NAMES:
                if not getattr(self,'development',None):raise Denied('DEVELOPMENT_UNAVAILABLE: 自我开发服务这会儿没接上；'+UNAVAILABLE)
                result=self.development.call(task,tool,args)
                with self.service.lock:self.service.valid(task)
            elif tool=='ask_character':
                if not getattr(self, 'consult_character', None):
                    raise RuntimeError('CHARACTER_CONSULT_UNAVAILABLE: 这会儿问不了你说话的那一半（角色脑没接上）；不是参数的问题，重试也一样：'
                                       '按你的判断做，把要那一半定的事写进报告')
                result=self.consult_character(task,key,args)
                # A reply is advice, never a renewal of cancelled/revised authority.
                with self.service.lock:self.service.valid(task)
            elif tool=='note_idea':
                from .role_tools import note_idea, IDEA_CHARS
                for field in ('idea','why'):
                    if not isinstance(args.get(field),str) or not args[field].strip() or len(args[field])>IDEA_CHARS:
                        raise ValueError('NOTE_IDEA_%s_REQUIRED: %s 要写一段 1..%d 字的文字，%s；改好再记'
                                         % (field.upper(),field,IDEA_CHARS,given_text(args.get(field))))
                row=note_idea(self.store,self.store.config['chat']['persona'],args['idea'].strip(),args['why'].strip(),
                    key=[task['_id'],key],source={'by':'action','task_id':task['_id'],'scene_id':task['scene_id']})
                result={'noted':row['_id'],'note':'记下了；自我改进时你再决定做不做。'}
            elif tool=='report_progress':
                note=args.get('note')
                if not isinstance(note,str) or not note.strip() or len(note)>4000:
                    raise ValueError('PROGRESS_NOTE_REQUIRED: note 要写一段 1..4000 字的文字，%s；改好再留' % given_text(note))
                if not task_records.thread_message(self.store, 'progress-'+key):
                    task_records.save_message(self.store, {'_id':'progress-'+key,'task_id':task['_id'],
                        'thread':task.get('thread') or task['_id'],'from':'action','text':note.strip(),
                        'scope_key':task['scope_key'],'created_at':now()},stream=task['_id'])
                self.service.collab(task,'progress',{'from':'action','text':note.strip()},'progress:'+key)
                result={'noted':True,'note':'说话的那一半下一回合会看到；要不要转告别人由那一半决定。'}
            elif tool in (HISTORY_TOOL_NAME,DIGEST_TOOL_NAME):
                # Read-only scoped history and the discussion digest: the scene comes from the task binding, never
                # from arguments. They run in the data child (data_children.py), with a deadline, and the effects
                # lock stays released meanwhile, so a cancellation or lease renewal cannot queue behind them.
                from . import data_children
                result=data_children.run(tool,task,args,self.store.config,self.store.name,self.evidence)
                with self.service.lock:self.service.valid(task)
            elif tool==READ_IMAGE_TOOL_NAME:
                # Pull 模式看图：场景仍由任务绑定，参数换不了范围；拉取期间不持副作用锁，
                # 取消与租约续期不被这次网络等待挡住。字节只上本机回路一次。
                # 按路径读盘上的图只在家里：会话类别按任务绑定现算（同 credentials.home_task 那条算法），
                # /task/ 指向这个任务自己的工作区。
                if not getattr(self, 'vision', None):raise Denied('VISION_SERVICE_UNAVAILABLE: 看图服务这会儿没接上；'+UNAVAILABLE)
                scene_row=scene_records.get(self.service.store, task['scene_id']) or {'_id':task['scene_id']}
                result=self.vision.read_image(task,args,session_class=visibility.session_class(self.service.store.config,self.service.store,scene_row,task['requester_id']),task_dir=sandbox.task_dir)
                with self.service.lock:self.service.valid(task)
            elif tool==RECEIVED_FILE_TOOL_NAME:
                # A file someone sent (ADR-102): the scene is the task's binding, as for read_image; the fetch waits
                # without the effects lock.
                from . import received_files
                scene_row=scene_records.get(self.service.store, task['scene_id']) or {'_id':task['scene_id']}
                result=received_files.run(self.service.store,task,self.service.store.config,args,
                                          persona=self.service.store.config['chat']['persona'],
                                          session_class=visibility.session_class(self.service.store.config,self.service.store,scene_row,task['requester_id']),
                                          task_dir=sandbox.task_dir)
                with self.service.lock:self.service.valid(task)
            elif tool=='generate_image':
                # 本机生图：任何任务都可以画，但只走 image 端点的固定流程；等待期间不持副作用锁。
                # 图登记到任务绑定的 scope，来源是 integration:image:…，算她自己做的图。
                if not getattr(self,'integration',None):raise Denied('IMAGE_SERVICE_UNAVAILABLE: 本机生图服务这会儿没接上（集成运行器没启动）；'+UNAVAILABLE)
                from .image_generation import generate
                def source(ref):
                    # The picture to edit: only one this task may look at (read_image's fence, this task's class).
                    if not getattr(self,'vision',None):raise ValueError('VISION_SERVICE_UNAVAILABLE: 看图服务这会儿没接上；'+UNAVAILABLE)
                    scene_row=scene_records.get(self.service.store, task['scene_id']) or {'_id':task['scene_id']}
                    picture=self.vision.picture_to_edit(task,ref,task_dir=sandbox.task_dir,
                        session_class=visibility.session_class(self.service.store.config,self.service.store,scene_row,task['requester_id']))
                    # Her own drawing edited stays hers; anyone else's goes back where it came from.
                    return {'data':picture['data'],'register':None if picture['own'] else
                            outbound_media.edit_register(self.store,task,picture['back_to'])}
                result=generate(args,runner=self.integration,workspace=sandbox.task_dir,source=source,
                                protected=sandbox.protected_paths,register=outbound_media.import_register(self.store,task))
                with self.service.lock:self.service.valid(task)
            elif tool=='private_words':
                # Her list lives with the deployment's data, outside the task folder (private_words.py).
                from . import private_words
                from . import credentials
                try:result=private_words.run(args,home=credentials.home_task(self.store,task))
                except private_words.PrivateWordsError as exc:raise Denied('PRIVATE_WORDS_REFUSED: '+str(exc)) from exc
            elif tool=='render_svg':
                # The Host renders; this side reads the SVG, drops links to outside pictures and keeps the PNG as hers.
                from . import svg_render
                result=svg_render.render(args,workspace=sandbox.task_dir,register=outbound_media.import_register(self.store,task))
                with self.service.lock:self.service.valid(task)
            elif integration_gated(tool):
                # 导入产物：端点白名单、工作区边界、默认不覆盖与大小上限都在
                # integration_import 里算；字节由本宿主进程写进这次绑定的工作区，不经过模型。
                # 登记用的 scope 取自任务绑定（task['scope_key']），不是参数：工具参数面没有 scope 这一项。
                result=(self.integration.import_artifact(args, workspace=sandbox.task_dir,
                            protected=sandbox.protected_paths,
                            register=outbound_media.import_register(self.store, task)) if tool==IMPORT_TOOL_NAME
                        else self.integration.call(tool,args))
            elif tool in ('list_files','read_file','write_file'):
                # Fixed file operations need no sandbox: the worker does them, inside the task folder only.
                result=workspace_file(sandbox.task_dir,sandbox.protected_paths,tool,args)
            elif tool=='offer_file':
                # The bytes stream into storage in the task's own scope (its binding, not a parameter); a large file
                # takes a while, so no lock is held across the copy.
                result=outbound_files.register(self.store,task,sandbox.task_dir,args)
                with self.service.lock:self.service.valid(task)
            elif tool=='sandbox_run':
                if args.get('credentials'):
                    # Owner 2026-10-07: a credential's variables reach one sandboxed command of a home task, nothing else.
                    from . import credentials
                    if not credentials.home_task(self.store,task):
                        raise Denied('CREDENTIALS_HOME_ONLY: credentials 只能用在 owner 私聊里交代的任务，这个任务不是；'
                                     '去掉 credentials 再跑，需要凭据的那一步写进报告')
                    result=sandbox.run(args['argv'],timeout=run_seconds(args.get('timeout')),
                                       env={**home_env(self.store),**credentials.environment(args['credentials'])})
                else:
                    result=sandbox.run(args['argv'],timeout=run_seconds(args.get('timeout')),env=home_env(self.store))
                with self.service.lock:self.service.valid(task)
            else:
                raise Denied('UNKNOWN_TOOL: %s 不是这里能执行的工具；重试也一样，换用工具清单里的工具' % str(tool)[:60])
            if tool!=READ_IMAGE_TOOL_NAME:
                from . import credentials
                result=credentials.scrub(result)          # no stored credential value reaches her or a receipt
            # A result is JSON data: the receipt and her character brain's view of it are JSON, and a raw database row
            # can hold other values (an archived message's original ObjectId).
            result=json.loads(json.dumps(result,ensure_ascii=False,default=str))
            self.service.crash('after_tool_before_receipt')
            # A definite failure is an error on both layers: the artifact is FAILED and the call's error says the same.
            failed=failure_words({**result,**({'adjusted':adjusted} if adjusted else {})})
            if failed:
                failed=redact_text(failed,self.store.config)
                artifact_records.save(self.store,{**artifact,'state':'FAILED','error':failed,'result':result},expected=artifact['revision'],stream=task['_id'])
                raise ToolFailed(failed)
            result['evidence_ref']=key
            result['artifact_ref']=key
            if adjusted:result['adjusted']=adjusted
            # read_image 的 base64 只交给调用方，不进回执：一张图就能顶破普通 BSON 行的 1 MiB 上限，
            # 字节本身已经在 GridFS 里，回执留 blob 引用与内联摘要。
            stored_result=read_image_receipt(result) if tool==READ_IMAGE_TOOL_NAME else result
            artifact_records.save(self.store,{**artifact,'state':'DONE','result':stored_result},expected=artifact['revision'],stream=task['_id'])
            return result

    def close(self):
        self.bindings.clear()


# A stopped task's receipt names what it left in its folder (her ask, 2026-10-22: twice a report already on disk read
# as "not done", and only her memory of its file name saved a rerun).
LEFT_SHOWN, LEFT_SCAN, LEFT_HASH_BYTES = 20, 20000, 64 * 1024 * 1024
LEFT_SKIP = frozenset(('.git', 'node_modules', '__pycache__', '.venv'))
FILE_CLOCK_SLACK_SECONDS = 1.0
STAGE_TIMEOUT = 'NATIVE_STAGE_TIMEOUT'
STOPPED_AT_LIMIT = ('行动这一段跑到了时间上限（%d 分钟），还没交报告就停了；原目标有没有做完没有确认。'
                    '它在 /task 里留下的文件列在 files，先看这些再决定要不要重做。')
LEFT_NOTE = '它在 /task 里改过的文件列在 files。'


def files_left(workspace, since):
    """The files in a task's folder changed since it started, newest first, as she reads them: path under /task, size,
    the first 16 hex digits of the sha256. At most LEFT_SHOWN, the rest counted; the walk stops after LEFT_SCAN files."""
    from datetime import datetime
    try:
        # A file's time comes from the file system's coarser clock (on Windows it moves in steps of up to 15.6 ms), so
        # a file written just after the start can carry a time a little before it: a second's slack counts it in.
        start = datetime.fromisoformat(str(since).replace('Z', '+00:00')).timestamp() - FILE_CLOCK_SLACK_SECONDS
    except ValueError:
        return []
    found, seen = [], 0
    for root, dirs, names in os.walk(workspace):
        dirs[:] = [name for name in dirs if name not in LEFT_SKIP]
        for name in names:
            seen += 1
            path = os.path.join(root, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            if stat.st_mtime >= start:
                found.append((stat.st_mtime, path, stat.st_size))
        if seen >= LEFT_SCAN:
            break
    found.sort(reverse=True)
    out = []
    for _, path, size in found[:LEFT_SHOWN]:
        where = '/task/' + Path(os.path.relpath(path, workspace)).as_posix()
        out.append('%s，%s 字节，%s' % (where, format(size, ','), _sha16(path) if size <= LEFT_HASH_BYTES else '太大，没算 sha'))
    if len(found) > LEFT_SHOWN:
        out.append('另有 %d 个更早改的没列出' % (len(found) - LEFT_SHOWN))
    return out


def _sha16(path):
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
    except OSError:
        return '读不了'
    return 'sha256 ' + digest.hexdigest()[:16]


def workspace_lock_path(workspace):
    """The lease file that keeps two task workers out of one workspace."""
    return DATA/'locks'/('workspace-'+sha(str(Path(workspace).resolve()).casefold().encode())+'.lock')


class Executor:
    def __init__(self,service,lane,broker):self.service,self.lane,self.broker=service,lane,broker

    def run(self,task_id,workspace):
        # Two task workers must not share a mutable project concurrently.
        # Take the lease before claiming: a busy workspace leaves the task READY.
        with RuntimeLease(workspace_lock_path(workspace)):
            return self._run_owned(task_id,workspace)

    def _run_owned(self,task_id,workspace):
        task=self.service.claim(task_id)
        try:
            with self.service.keepalive(task) as healthy:
                return self._run_claimed(task,workspace,healthy)
        except Exception as exc:
            left=files_left(workspace,task.get('started_at')) if task.get('started_at') else []   # walked before the lock
            with self.service.lock:
                current=task_records.get(self.service.store, task_id)
                if current and current['state']=='RUNNING' and current['intent_revision']==task['intent_revision'] and current['fencing_token']==task['fencing_token']:
                    error=redact_text(traceback.format_exc(),self.service.store.config)
                    if isinstance(exc,TimeoutError) and STAGE_TIMEOUT in str(exc):
                        text=STOPPED_AT_LIMIT%(self.service.store.config['workflow_timeout_seconds']//60)
                    else:
                        text='行动运行失败，原目标仍未完成。'+(LEFT_NOTE if left else '')
                    result={'status':'blocked','text':text,'error':error,'uncertainties':['已发起而没有回执的操作须先核实，不可盲目重做。'],
                            **({'files':left} if left else {})}
                    return task_records.save(self.service.store, {**current,'state':'BLOCKED','failure_type':type(exc).__name__,'result':result,'feedback_state':'READY'},expected=current['revision'],stream=task_id)
            raise

    def _run_claimed(self,task,workspace,healthy):
        binding=task.get('execution_binding') or f"task:{task['_id']}:{task['scope_key']}:{task['policy_epoch']}:{task['intent_revision']}"
        self.broker.bind('s-'+sha(binding.encode())[:40],task,workspace)
        source=message_records.get(self.service.store, task['raw_input_refs'][0])
        return self._run_workspace(task,binding,source,healthy)

    def _run_workspace(self,task,binding,source,healthy):
        from .grants import workspace_grant
        grant=workspace_grant(self.service.store.config,task['scene_id'],task['requester_id'])
        store=self.service.store
        # Who she is, at the class of the conversation the task came from (render.action_persona).
        scene=scene_records.get(store, task['scene_id']) or {'_id':task['scene_id']}
        cls=visibility.session_class(store.config,store,scene,task['requester_id'])
        system=(prompt_path(store.config,'executor.md').read_text(encoding='utf-8')
                +action_values(store,cls=cls,place=visibility.place_of(store.config,scene,cls)))
        # ADR-011 §4: her brief is the first message (a continuation: her new words in the same session);
        # the program's facts follow it, marked as the program's.
        text=opening_text(store,task)
        facts={'original_input':(source or {}).get('text'),'workspace':'/task','read_only_paths':grant.get('read_only_paths',[])}
        if task.get('constraints'):facts['constraints']=task['constraints']
        # Pull 模式：只告诉她有什么图、ref 是什么、能不能拉；图片正文不进输入。
        attachments=task_attachment_context(self.service.store,task,self.service.store.config,source) if source else None
        if attachments:facts['attachments']=attachments
        if cls==visibility.OWNER_PRIVATE and 'sandbox_run' in task.get('allowed_capabilities',()):
            from . import credentials
            vault=credentials.listing()
            if vault:facts['credentials']={'items':vault,'how':'sandbox_run 写 credentials（名字照抄），这些环境变量只在那一条命令里有；脚本用 os.environ 读，值不要写进文件、脚本、报告。'}
        from . import local_time                     # the action brain reads times on the local clock
        facts=local_time.for_model(facts,local_time.zone_of(self.service.store,task['scene_id']))
        text+='\n\n—— 程序附注（不是你交代的话）——\n'+json.dumps(facts,ensure_ascii=False)
        if task.get('integration_profile') == 'owner':
            text+='\n本任务继承本机 owner 工作域的集成能力。适配器代码在通道包里，只用 development_* 工具（project 填通道包）修改。integration_test 把候选里的适配器目录冻结成一份（argv 里写 /app）来试跑；integration_start 只启用已发布（development_publish 之后）的适配器版本，宿主重启后也恢复已发布的版本。/data 可写，test 与启用数据分开。/integration/config.json 是端点与 adapter 配置。运行直接连配置里的端点，用的是真实配置：试跑也能真的对平台做动作，试跑只做读，发消息留给出站队列和已发布的适配器。integration_test 最长60秒；integration_start 持续到明确停止并可随宿主恢复；未要求持续运行就不要 start。integration_status/stop 可观察/停止。失败回本会话自行修复；不能把进程 RUNNING 当平台连接或发送成功。import_integration_artifact 只能按配置里已有的端点别名取一个产物（不是任意 URL 下载器），字节由平台写进本次任务工作区的相对路径，默认不覆盖、有大小上限，失败会给出真实原因（端点未知、URL 被拒、路径越界、目标已存在、超限、HTTP 状态）。'
        if task.get('integration_profile') == 'agent_home':
            text+='\n本任务继承 agent 线家里回合的窄集成授权（agent_home）：只有 integration_start 与 integration_status。'
            text+='start 只启用已发布（development_publish 之后）的适配器版本，宿主重启后恢复的也是当时已发布的版本；'
            text+='status 只读，回的是真实进程状态与日志。RUNNING 不等于平台连上或发送成功。'
            text+='没有 integration_test（试跑）、integration_stop（停止）和产物导入：那些要交回本机 owner 工作域的任务。'
        if 'render_svg' in task.get('allowed_capabilities',()):
            text+='\n要把 SVG 变成图（截图、预览、发出去）：write_file 写好 .svg，再用 render_svg；PNG 落进 /task/images 并登记成你自己的图，用 read_image 传 artifact_id 亲眼看过再交。SVG 链接的外部图片不会加载，要用就内嵌成 data: URI。'
        if 'generate_image' in task.get('allowed_capabilities',()):
            text+='\n要画图先用 generate_image：本机的生图服务，图直接落进 /task 并登记成你自己的图，之后能随消息发出去（群里只发全年龄的图）。先用 list_routes=yes 看有哪些路线、各要什么样的提示词；画完用 read_image 传 artifact_id 亲眼看，不对就改了再画。外部公开的生图服务也可以用，但那样的图进不了工作区，只能给链接。'
        if task.get('development_grant'):
            text+='\n你可使用 development_* 工具直接编辑可发布的 Asuna 项目候选。development_files/read/write 返回真实文件；development_run 在候选目录里运行命令（宿主沙箱：只能写候选目录；命令是本机原生的，Windows 上没有 sh，用 python3 写脚本）并返回 stdout/stderr/退出码；development_database_read 只读同一个真实数据库中的原始记录（没有另一个测试库）。失败检查只提供诊断，可继续修复。development_publish 冻结候选、运行不消费消息的最低启动探针并应用通过的改动，实际宿主重启后结果再进入同一角色场景；无需 Codex 审查。普通 /task 仍是原持久工作区，不是这个候选。技能也在候选里（角色包 skills/<kebab-case-name>/SKILL.md），同样只用 development_* 修改、经 development_publish 生效；原生 skill 工具读取的是已发布的版本。修改认知核需显式 project="core"。发布与否由你判断。'
        # Her words that arrived before this run started belong to its first message.
        early=self.pending_messages(task)
        if early:
            text+='\n\n你后来又补充：\n'+'\n'.join(row['text'] for row in early)
            self.delivered(early)
        operation=task['_id']+':execute:'+str(task['intent_revision'])
        self.service.collab(task,'status',{'state':'running'},'status:'+task['_id']+':running')
        def rejected(attempt,issue,value):
            self.service.store.audit(task['_id'],'execution.rejected',{'attempt':attempt,'problem':issue,'request_refs':value.request_refs},task['scope_key'])
        for round_no in range(MESSAGE_ROUNDS+1):
            current_op=operation if not round_no else operation+':more:'+str(round_no)
            def generate(attempt,note,current_op=current_op,text=text):
                value=self.lane.generate(binding,current_op if not attempt else current_op+':fix-'+str(attempt),'execution',note or text,system,
                                         trigger='follow-up' if round_no or task.get('continues_task_id') else 'brief')
                healthy()
                self.service.store.audit(task['_id'],'execution.output',{'request_refs':value.request_refs,'content':value.content,'reasoning':value.reasoning,'finish_reason':value.finish_reason,'attempt':attempt},task['scope_key'])
                return value
            # The report is what the character hears; an empty or unfinished one goes back to the action brain (answers.py).
            unusable=None
            try:
                value,_=answers.ask(generate,'给角色的行动报告：做了什么、结果怎样、还有什么没确定，写在正文里',tools=True,rejected=rejected)
            except answers.Rejected as exc:
                value,unusable=exc.value,exc.problem
            # Words she sent while it worked but that its turn ended before reading: one more round in the same session.
            late=self.pending_messages(task) if value.finish_reason=='stop' and not unusable else []
            if not late or round_no==MESSAGE_ROUNDS:
                break
            text='你在对话里又补充了（做事这边可能还没看到）：\n'+'\n'.join(row['text'] for row in late)
            self.delivered(late)
        artifacts=artifact_records.of_task(self.service.store,task['_id'],task['intent_revision'],state='DONE').rows()
        observations=artifacts
        # The model reports in natural language; identities and actual receipts
        # are attached by the program, never recopied or invented by the model.
        from . import credentials
        content=credentials.scrub(value.content)
        result={'task_id':task['_id'],'intent_revision':task['intent_revision'],'text':content,
                'finish_reason':value.finish_reason,'artifact_refs':[a['_id'] for a in observations],
                'diagnostic':value.diagnostic,
                'facts':[{'text':content,'evidence_refs':[a['_id'] for a in observations]}],
                'uncertainties':(['行动脑没有给出可用的报告（'+unusable+'）；保留已产生的工具事实，不宣称目标完成。'] if unusable
                    else [] if value.finish_reason=='stop' else ['原生回合未正常结束；保留已产生的工具事实，不宣称目标完成。'])}
        returned=value.finish_reason=='stop' and not unusable
        with self.service.lock:
            current=self.service.valid(task)
            finished=task_records.save(self.service.store, {**current,'state':'RETURNED' if returned else 'BLOCKED',
                'result':result,'finished_at':now(),'feedback_state':'READY'},expected=current['revision'],stream=task['_id'])
        self.service.collab(finished,'status',{'state':'done' if returned else 'failed'},'status:'+task['_id']+':finished')
        return finished

    def pending_messages(self,task):
        return task_records.thread(self.service.store,task['_id'],sender='character',delivered=False).rows()

    def delivered(self,rows):
        store=self.service.store
        for row in rows:
            current=task_records.thread_message(store, row['_id'])
            if current and not current.get('delivered'):
                task_records.save_message(store, {**current,'delivered':True,'delivered_at':now()},expected=current['revision'],stream=current['task_id'])

from __future__ import annotations
import json
from pathlib import Path
import secrets
import shutil
import threading
import traceback
import uuid
from contextlib import contextmanager,nullcontext
import jsonschema
from .config import DATA,prompt_path,redact_text,excerpt
from .render import action_values
from . import answers, visibility
from .evidence import canonical,sha
from .sandbox import Sandbox
from .state import Store,Denied,Conflict,now
from .queue import database_effects_lock,RuntimeLease
from .integration import INTEGRATION_TOOLS, owner_profile
from .integration_import import IMPORT_TOOL_NAME, integration_gated
from . import outbound_media   # 导入图片时顺手登记成这一轮可引用的 image artifact（B7）
from .history_query import HISTORY_TOOL, HISTORY_TOOL_NAME
from .discussion_digest import DIGEST_TOOL, DIGEST_TOOL_NAME
from .development import DEVELOPMENT_TOOLS, DEVELOPMENT_NAMES, PERSONA_JOB_TOOLS
from .vision import (READ_IMAGE_TOOL, READ_IMAGE_TOOL_NAME, inline_summary as read_image_receipt,
                     route_filtered_tool_names, task_attachment_context)

# How many extra rounds one run takes for her words its turn ended before reading.
MESSAGE_ROUNDS = 3
TERMINAL={'DONE','RETURNED','PARTIAL','BLOCKED','CANCELLED','STALE','NEEDS_CHARACTER_DECISION','UNKNOWN'}


# Per-turn budget for task feedback (the largest context block): the action brain's report and the
# last few tool observations as evidence. Cuts are marked; the full records stay in the task.
REPORT_CHARS = 6000
OBSERVATIONS = 4
OBSERVATION_CHARS = 600


def bounded_result(result):
    if isinstance(result, dict) and isinstance(result.get('text'), str):
        # The ids of its tool records are audit, not something she reads: a count says how much was done.
        refs = result.get('artifact_refs')
        value = {key: item for key, item in result.items() if key != 'artifact_refs'}
        return {**value, 'text': excerpt(result['text'], REPORT_CHARS),
                **({'tool_records': len(refs)} if isinstance(refs, list) else {})}
    return result


class FeedbackStale(Denied):
    """The action result no longer authorizes a pending role continuation."""


def require_current_feedback(store, episode):
    if episode.get('episode_kind') != 'task_feedback':
        return
    # episode.task_id changes when feedback delegates another action. The
    # durable input remains the identity of the result being considered.
    source = store.db.messages.find_one({'_id': 'in-' + episode['_id']})
    event = (source or {}).get('event', {})
    task = store.db.tasks.find_one({'_id': event.get('task_id')})
    scene = store.db.scenes.find_one({'_id': episode['scene_id']})
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
    'description':'Ask the character who gave you this task for her judgment (what she meant, what she prefers, a decision that is hers), and wait for her answer. Not a public reply, new task or permission grant. Ordinary implementation details and errors are yours to handle; do not ask before every step.',
    'parameters':{'question':{'type':'string','required':True}, 'context':{'type':'string','description':'Material she needs to judge, briefly'}}}
NOTE_IDEA_TOOL = {'name':'note_idea',
    'description':'Note an idea for improving her (a capability, a skill, a way of working) in her improvement notebook, in your own words, with why. Use it when something you see while working (including on the web) could be better: do not change it now. She reviews ideas in her self-improvement time. No one else\'s personal data.',
    'parameters':{'idea':{'type':'string','required':True},'why':{'type':'string','required':True}}}
PROGRESS_TOOL = {'name':'report_progress',
    'description':'Leave her a short progress note on a long task, without waiting: she reads it on her next turn and decides whether to tell anyone. Use sparingly; the final report is your last message.',
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
        with target.open('w' if args.get('overwrite', False) else 'x', encoding='utf-8') as handle:
            handle.write(args['text'])
        return {'path': target.relative_to(root).as_posix(), 'text': target.read_text(encoding='utf-8'), 'written': True}
    except Exception as exc:
        return {'error': 'TASK_OPERATION_FAILED: ' + workspace_reason(exc, op, given),
                'execution': {'exit_code': 1, 'stderr': traceback.format_exc(limit=1)}}


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


SANDBOX_TOOL={'name':'sandbox_run','description':'Run argv in the task folder under the Host sandbox: it may write only there. Commands are native to the machine the Host runs on (on Windows there is no sh or Linux tools: write the work as a python3 script; python3 is Python 3.12, with httpx, websockets, paramiko, pymongo, PyYAML and PIL (Pillow) importable). An argument /task or /task/… names the task folder. Max 30 seconds, 256 KiB output. credentials: names from the program notes\' credentials; their environment variables are set for this one command only (a script reads os.environ). Values are never shown: output containing one comes back hidden. Never write a credential value into a script, file, brief or report.', 'parameters':{'argv':{'oneOf':[{'type':'array','items':{'type':'string'}},{'type':'string'}],'required':True},'credentials':{'oneOf':[{'type':'array','items':{'type':'string'}},{'type':'string'}],'description':'credential names for this command (home tasks only)'}}}

WORKSPACE_TOOLS = [
    {'name': 'list_files', 'description': 'List files inside the authorized workspace /task.', 'parameters': {}},
    {'name': 'read_file', 'description': 'Read a UTF-8 file inside /task (up to 32 KiB), or page this action session’s native tool spill using byte offset/limit.', 'parameters': {'path': {'type': 'string', 'required': True}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}}},
    {'name': 'write_file', 'description': 'Create a UTF-8 file inside /task. Existing files require explicit overwrite=true. Protected paths are read-only.', 'parameters': {'path': {'type': 'string', 'required': True}, 'text': {'type': 'string', 'required': True}, 'overwrite': {'type': 'boolean'}}},
    SANDBOX_TOOL,
]

# These are DSH-owned action-agent tools, not ToolBroker capabilities. The
# names are persisted with each task grant so native session visibility follows
# the same task boundary as the existing host tools.
ACTION_DSH_CAPABILITIES = ('skill', 'todo_write', 'web_search', 'web_fetch')

WORKSPACE_TOOLS.append(HISTORY_TOOL)
# P1-c：按需群整理与历史查询共用同一只读入口规则（场景来自任务绑定，参数不换范围）。
WORKSPACE_TOOLS.append(DIGEST_TOOL)
WORKSPACE_TOOLS.append(ASK_TOOL)
WORKSPACE_TOOLS.append(PROGRESS_TOOL)
WORKSPACE_TOOLS.append(NOTE_IDEA_TOOL)
# 看图（Pull 模式）：定义与实现同处注册；是否进入某个任务的能力清单，取决于那条行动路由
# 是否声明了图片输入（见 route_filtered_tool_names），不按模型名字猜。
WORKSPACE_TOOLS.append(READ_IMAGE_TOOL)


def stale_reason(task,current,scene):
    """Why a call's task no longer holds its authority, as the program sees it."""
    if not current:return '这个任务已经不在了'
    if current['state']=='CANCELLED':return '这个任务已经被取消了'
    if current['state']=='PAUSED':return '这个任务因宿主重启暂停了'
    if current['intent_revision']!=task['intent_revision']:return '她改了这个任务的交代（新的交代取代了这一版）'
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
            task=self.store.db.tasks.find_one({'_id':task_id})
            if task['state']!='READY':raise Conflict('TASK_NOT_READY')
            task=self.store.put('tasks',{**task,'state':'RUNNING','lease_owner':str(uuid.uuid4()),'fencing_token':task['fencing_token']+1,'lease_expires_at':__import__('time').time()+600},expected=task['revision'],stream=task_id)
            return task

    def valid(self,task,*,state='RUNNING'):
        current=self.store.db.tasks.find_one({'_id':task['_id']})
        scene=self.store.db.scenes.find_one({'_id':task['scene_id']})
        if not current or current['state']!=state or current['intent_revision']!=task['intent_revision'] or current['fencing_token']!=task['fencing_token'] or scene['policy_epoch']!=task['policy_epoch']:
            raise Denied('STALE_TASK_FENCE: '+stale_reason(task,current,scene)+'，这次调用不算数，也没有执行；不是你出错，重试也一样：'
                         '停下，不再调工具，在报告里写做到了哪里')
        if state=='RUNNING' and current.get('lease_expires_at',0)<=__import__('time').time():
            raise Denied('TASK_LEASE_EXPIRED: 这个任务的执行租约过期了（10 分钟没有续上），这次调用没有执行；不是参数的问题，'
                         '重试也一样：停下，在报告里写做到了哪里')
        return current

    def cancel(self,task_id,reason='user_cancelled',*,person_id=None,operator=False):
        with self.lock:
            task=self.store.db.tasks.find_one({'_id':task_id})
            if not task or not(operator or person_id==task['requester_id']):raise Denied('TASK_CANCEL_NOT_AUTHORIZED')
            if not task.get('execution_binding'):
                task={**task,'execution_binding':f"task:{task['_id']}:{task['scope_key']}:{task['policy_epoch']}:{task['intent_revision']}"}
            cancelled=self.store.put('tasks',{**task,'state':'CANCELLED','intent_revision':task['intent_revision']+1,'fencing_token':task['fencing_token']+1,'cancel_reason':reason,'feedback_state':'SUPPRESSED'},expected=task['revision'],stream=task_id)
        self.collab(cancelled,'status',{'state':'stopped','reason':reason},'status:'+task_id+':cancelled')
        return self._notify_fenced(cancelled, 'task_cancelled')

    def pause_for_restart(self, task_id):
        """Preserve old work and receipts; only a new local request can resume."""
        with self.lock:
            task = self.store.db.tasks.find_one({'_id': task_id})
            if not task or task['state'] in ('CANCELLED', 'STALE', 'PAUSED'):
                return task
            paused = self.store.put('tasks', {**task, 'state': 'PAUSED', 'pause_reason': 'host_restart',
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
                        self.store.put('tasks',{**current,'lease_expires_at':__import__('time').time()+600},expected=current['revision'],stream=task['_id'])
                except Exception as exc:errors.append(exc);return
        worker=threading.Thread(target=renew,daemon=True);worker.start()
        def check():
            if errors:raise RuntimeError('TASK_LEASE_RENEWAL_FAILED') from errors[0]
        try:yield check
        finally:stopped.set();worker.join(5)

    def feedback(self,task,coordinator):
        current=self.store.db.tasks.find_one({'_id':task['_id']})
        scene=self.store.db.scenes.find_one({'_id':task['scene_id']})
        if current['state'] not in TERMINAL or current.get('feedback_state')!='READY':return None
        if current['state'] in ('CANCELLED','STALE') or current['intent_revision']!=task['intent_revision'] or scene['policy_epoch']!=task['policy_epoch']:return None
        original=self.store.db.episodes.find_one({'_id':task['episode_id']})
        ep=self.store.db.episodes.find_one({'_id':current.get('feedback_episode')}) if current.get('feedback_episode') else None
        if not ep:
            ep=self.store.db.episodes.find_one({'scene_id':task['scene_id'],
                'source_event_id':task['_id']+':result:'+str(task['intent_revision']),
                'episode_kind':'task_feedback'})
        continuing=bool(ep)
        if ep:
            if (ep.get('episode_kind')!='task_feedback' or ep.get('task_id')!=task['_id']
                    or ep.get('intent_revision')!=task['intent_revision'] or ep['scene_id']!=task['scene_id']
                    or ep['person_id']!=task['requester_id'] or ep['policy_epoch']!=task['policy_epoch']):
                raise Denied('FEEDBACK_EPISODE_MISMATCH')
        else:
            depth=original.get('delegation_depth',0)+1
            event={'event_id':task['_id']+':result:'+str(task['intent_revision']),'scene_id':task['scene_id'],'person_id':task['requester_id'],'text':'你交给行动脑的「'+(task.get('title') or task['goal'])+'」有了结果。它的报告是自然语言；工具记录才是执行事实。任务返回不等于目标完成，也不规定你的感受或要说什么；要接着做就用 message_action。','episode_kind':'task_feedback','task_id':task['_id'],'intent_revision':task['intent_revision'],'delegation_depth':depth,'trusted_context_events':[{'kind':'task_result','task':task['_id'],'title':task.get('title') or task['goal'],'value':bounded_result(task.get('result')) or {'state':current['state'],'error':current.get('failure_type'),'uncertainties':['上次操作结果未确定；可继续核实，不能盲目重做。']}}]}
            source=self.store.db.messages.find_one({'_id':task['raw_input_refs'][0], 'scope_key':task['scope_key'], 'policy_epoch':task['policy_epoch']})
            if original.get('native_session_id'):
                event['native_session_id']=original['native_session_id']
            if source and source.get('event', {}).get('group_context'):
                event['group_context'] = source['event']['group_context']
            if task.get('integration_profile') == 'owner': event['integration_profile'] = 'owner'
            observations=[]
            for item in self.store.db.artifacts.find({'task_id':task['_id'],'intent_revision':task['intent_revision'],'state':'DONE'}):
                observations.append({'source':item['_id'],'tool':item['tool'],
                                     'result_excerpt':excerpt(json.dumps(item['result'],ensure_ascii=False),OBSERVATION_CHARS)})
            event['trusted_context_events'][0].update(original_input=(source or {}).get('text'),brief=task.get('brief') or task['goal'],
                observations=observations[-OBSERVATIONS:],observations_total=len(observations))
            ep=coordinator.ingest(event,persona=original['persona'])
        if ep['state'] in (('FAILED_PROTOCOL',) if continuing else ()) or ep['state'] in ('PREPARED','TURN','SPEAK_ACCEPTED','INTERRUPTED'):
            ep=coordinator.advance(ep['_id'])
        with self.lock:
            latest = self.store.db.tasks.find_one({'_id': task['_id']})
            if (latest['state'] in ('CANCELLED', 'STALE', 'PAUSED')
                    or latest['intent_revision'] != task['intent_revision']):
                return ep  # Never overwrite a cancellation/revision while inference was in flight.
            self.store.put('tasks',{**latest,'feedback_state':'READY' if ep['state']=='FAILED_PROTOCOL' else 'DELIVERED' if ep['state']=='COMMITTED' else ep['state'],'feedback_episode':ep['_id']},expected=latest['revision'],stream=latest['_id'])
        if ep['state']=='COMMITTED' and original['state']=='WAITING_TASK':
            self.store.put('episodes',{**original,'state':'COMMITTED','feedback_episode':ep['_id']},expected=original['revision'],stream=original['_id'])
        return ep


DEVELOPMENT_GRANT=('DEVELOPMENT_GRANT_REQUIRED: 这个任务没有自我开发授权，development_* 和 persona_job_run 用不了；'
                   '重试也一样，需要改代码就在报告里说明')
UNAVAILABLE='不是参数的问题，重试也一样：不用它能做的先做，没做成的写进报告'


def given_text(value):
    if isinstance(value,str):return '给的是 %d 字' % len(value) if value.strip() else '给的是空的'
    return '没给' if value is None else '给的是 %s' % type(value).__name__


class ToolBroker:
    """Trusted host process; no DB/publication credentials enter model or child tools."""
    def __init__(self, service:TaskService):
        # Native Host tools use the private worker connection; there is no HTTP broker.
        self.service,self.store=service,service.store
        self.bindings={}

    @property
    def specs(self):
        from .image_generation import GENERATE_IMAGE_TOOL
        from .svg_render import RENDER_SVG_TOOL
        return [*WORKSPACE_TOOLS, GENERATE_IMAGE_TOOL, RENDER_SVG_TOOL, *INTEGRATION_TOOLS, *DEVELOPMENT_TOOLS, *PERSONA_JOB_TOOLS]

    def bind(self,session,task,workspace):
        from .grants import workspace_grant
        grant=workspace_grant(self.store.config,task['scene_id'],task['requester_id'])
        if Path(workspace).resolve()!=Path(grant['workspace']).resolve():raise Denied('WORKSPACE_GRANT_MISMATCH')
        protected=[Path(workspace)/p for p in grant.get('read_only_paths',[])]
        self.bindings[session]=(task,Sandbox(workspace,protected,allowed_root=Path(grant['workspace']),config=self.store.config))

    def call(self,session,call_id,tool,args):
        from .tool_args import normalize
        args,adjusted=normalize(tool,args)          # what she plainly meant; said back in the result (tool_args.py)
        with self.service.lock:
            if session not in self.bindings:
                raise Denied('UNBOUND_EXECUTOR: 这个行动会话没有绑定到任务（任务已结束或宿主重启过）；不是参数的问题，'
                             '重试也一样：停下，在报告里写做到了哪里')
            task,sandbox=self.bindings[session]
            current=self.service.valid(task)
            if tool not in current['allowed_capabilities']:
                raise Denied('CAPABILITY_DENIED: 这个任务没有 %s 这个工具；能用的是 %s'
                             % (str(tool)[:60],'、'.join(current['allowed_capabilities'])))
            if tool in DEVELOPMENT_NAMES and not current.get('development_grant'):
                raise Denied(DEVELOPMENT_GRANT)
            if integration_gated(tool):
                if current.get('integration_profile') != 'owner':
                    raise Denied('INTEGRATION_TASK_GRANT_REQUIRED: %s 只给继承 owner 工作域的任务用，这个任务不是；'
                                 '重试也一样，在报告里写明需要它' % tool)
                owner_profile(self.store.config, current['scene_id'], current['requester_id'])
                if not getattr(self, 'integration', None):
                    raise Denied('INTEGRATION_RUNNER_UNAVAILABLE: 集成运行器这会儿没启动（宿主没有沙箱或没装配它）；'+UNAVAILABLE)
            key='tool-'+sha(canonical([task['_id'],task['intent_revision'],call_id]))
            input_hash=sha(canonical([tool,args]))
            old=self.store.db.artifacts.find_one({'_id':key})
            if old:
                if old['input_hash']!=input_hash:
                    raise Denied('CALL_ID_REUSED: 这个调用编号已经用在另一组参数的 %s 调用上；不是参数写错，'
                                 '重新发起一次调用（会换新编号）' % old.get('tool'))
                if old['state']!='DONE':
                    raise Denied('TOOL_DELIVERY_UNKNOWN: 同一个调用之前开始过但还没有回执（可能还在进行，或中途断过），不知道做没做成；'
                                 '不要盲目重做：先查看它该留下的结果（list_files、读文件等）再决定')
                return old['result']
            self.store.put('tasks',{**current,'tool_steps':current['tool_steps']+1,'lease_expires_at':__import__('time').time()+600},expected=current['revision'],stream=task['_id'])
            artifact=self.store.put('artifacts',{'_id':key,'scope_key':task['scope_key'],'task_id':task['_id'],'intent_revision':task['intent_revision'],'tool':tool,'args':args,'input_hash':input_hash,'state':'INTENT'},stream=task['_id'])
            self.service.crash('before_tool')
        # Integration callbacks and role consultations can need host resources.
        # Never hold the effects lock across either wait; leases and cancellation
        # must remain available. A later cancellation still
        # fences new calls; recording this accepted call cannot revive the task.
        with (nullcontext() if integration_gated(tool) or tool in DEVELOPMENT_NAMES or tool=='ask_character'
                  or tool in ('generate_image','render_svg') or tool==HISTORY_TOOL_NAME or tool==DIGEST_TOOL_NAME or tool==READ_IMAGE_TOOL_NAME else self.service.lock):
            if not integration_gated(tool):self.service.valid(task)
            if tool=='persona_job_run':
                if not task.get('development_grant'):raise Denied(DEVELOPMENT_GRANT)
                result=self.persona_jobs(task,args)
                with self.service.lock:self.service.valid(task)
            elif tool in DEVELOPMENT_NAMES:
                if not getattr(self,'development',None):raise Denied('DEVELOPMENT_UNAVAILABLE: 自我开发服务这会儿没接上；'+UNAVAILABLE)
                result=self.development.call(task,tool,args)
                with self.service.lock:self.service.valid(task)
            elif tool=='ask_character':
                if not getattr(self, 'consult_character', None):
                    raise RuntimeError('CHARACTER_CONSULT_UNAVAILABLE: 这会儿问不了她（角色脑没接上）；不是参数的问题，重试也一样：'
                                       '按你的判断做，把要她定的事写进报告')
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
                result={'noted':row['_id'],'note':'记下了；她会在自我改进时间里决定做不做。'}
            elif tool=='report_progress':
                note=args.get('note')
                if not isinstance(note,str) or not note.strip() or len(note)>4000:
                    raise ValueError('PROGRESS_NOTE_REQUIRED: note 要写一段 1..4000 字的文字，%s；改好再留' % given_text(note))
                if not self.store.db.task_messages.find_one({'_id':'progress-'+key}):
                    self.store.put('task_messages',{'_id':'progress-'+key,'task_id':task['_id'],
                        'thread':task.get('thread') or task['_id'],'from':'action','text':note.strip(),
                        'scope_key':task['scope_key'],'created_at':now()},stream=task['_id'])
                self.service.collab(task,'progress',{'from':'action','text':note.strip()},'progress:'+key)
                result={'noted':True,'note':'她下一回合会看到；要不要转告别人由她决定。'}
            elif tool==HISTORY_TOOL_NAME:
                # Read-only scoped history: the scene comes from the task binding, never
                # from arguments. The effects lock stays released during the query so a
                # cancellation or lease renewal cannot queue behind a Mongo read.
                if not getattr(self, 'history', None):raise Denied('HISTORY_QUERY_UNAVAILABLE: 历史查询服务这会儿没接上；'+UNAVAILABLE)
                result=self.history.query_for_task(task,args)
                with self.service.lock:self.service.valid(task)
            elif tool==DIGEST_TOOL_NAME:
                # P1-c read-only discussion digest: same rule as history — scene from the
                # task binding, no effects lock held across the Mongo reads.
                if not getattr(self, 'digest', None):raise Denied('DISCUSSION_DIGEST_UNAVAILABLE: 群讨论整理服务这会儿没接上；'+UNAVAILABLE)
                result=self.digest.digest_for_task(task,args)
                with self.service.lock:self.service.valid(task)
            elif tool==READ_IMAGE_TOOL_NAME:
                # Pull 模式看图：场景仍由任务绑定，参数换不了范围；拉取期间不持副作用锁，
                # 取消与租约续期不被这次网络等待挡住。字节只上本机回路一次。
                if not getattr(self, 'vision', None):raise Denied('VISION_SERVICE_UNAVAILABLE: 看图服务这会儿没接上；'+UNAVAILABLE)
                result=self.vision.read_image(task,args)
                with self.service.lock:self.service.valid(task)
            elif tool=='generate_image':
                # 本机生图：任何任务都可以画，但只走 image 端点的固定流程；等待期间不持副作用锁。
                # 图登记到任务绑定的 scope，来源是 integration:image:…，算她自己做的图。
                if not getattr(self,'integration',None):raise Denied('IMAGE_SERVICE_UNAVAILABLE: 本机生图服务这会儿没接上（集成运行器没启动）；'+UNAVAILABLE)
                from .image_generation import generate
                result=generate(args,runner=self.integration,workspace=sandbox.task_dir,
                                protected=sandbox.protected_paths,register=outbound_media.import_register(self.store,task))
                with self.service.lock:self.service.valid(task)
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
            elif tool=='sandbox_run':
                if args.get('credentials'):
                    # Owner 2026-10-07: a credential's variables reach one sandboxed command of a home task, nothing else.
                    from . import credentials
                    if not credentials.home_task(self.store,task):
                        raise Denied('CREDENTIALS_HOME_ONLY: credentials 只能用在 owner 私聊里交代的任务，这个任务不是；'
                                     '去掉 credentials 再跑，需要凭据的那一步写进报告')
                    result=sandbox.run(args['argv'],env=credentials.environment(args['credentials']))
                else:
                    result=sandbox.run(args['argv'])
            else:
                raise Denied('UNKNOWN_TOOL: %s 不是这里能执行的工具；重试也一样，换用工具清单里的工具' % str(tool)[:60])
            if tool!=READ_IMAGE_TOOL_NAME:
                from . import credentials
                result=credentials.scrub(result)          # no stored credential value reaches her or a receipt
            self.service.crash('after_tool_before_receipt')
            result['evidence_ref']=key
            result['artifact_ref']=key
            if adjusted:result['adjusted']=adjusted
            # read_image 的 base64 只交给调用方，不进回执：一张图就能顶破普通 BSON 行的 1 MiB 上限，
            # 字节本身已经在 GridFS 里，回执留 blob 引用与内联摘要。
            stored_result=read_image_receipt(result) if tool==READ_IMAGE_TOOL_NAME else result
            self.store.put('artifacts',{**artifact,'state':'DONE','result':stored_result},expected=artifact['revision'],stream=task['_id'])
            return result

    def close(self):
        self.bindings.clear()


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
            with self.service.lock:
                current=self.service.store.db.tasks.find_one({'_id':task_id})
                if current and current['state']=='RUNNING' and current['intent_revision']==task['intent_revision'] and current['fencing_token']==task['fencing_token']:
                    error=redact_text(traceback.format_exc(),self.service.store.config)
                    result={'status':'blocked','text':'行动运行失败，原目标仍未完成。','error':error,'uncertainties':['已发起而没有回执的操作须先核实，不可盲目重做。']}
                    return self.service.store.put('tasks',{**current,'state':'BLOCKED','failure_type':type(exc).__name__,'result':result,'feedback_state':'READY'},expected=current['revision'],stream=task_id)
            raise

    def _run_claimed(self,task,workspace,healthy):
        binding=task.get('execution_binding') or f"task:{task['_id']}:{task['scope_key']}:{task['policy_epoch']}:{task['intent_revision']}"
        self.broker.bind('s-'+sha(binding.encode())[:40],task,workspace)
        source=self.service.store.db.messages.find_one({'_id':task['raw_input_refs'][0]})
        return self._run_workspace(task,binding,source,healthy)

    def _run_workspace(self,task,binding,source,healthy):
        from .grants import workspace_grant
        grant=workspace_grant(self.service.store.config,task['scene_id'],task['requester_id'])
        store=self.service.store
        # Who she is, at the class of the conversation the task came from (render.action_persona).
        cls=visibility.session_class(store.config,store.db,store.db.scenes.find_one({'_id':task['scene_id']}) or {'_id':task['scene_id']},task['requester_id'])
        system=prompt_path(store.config,'executor.md').read_text(encoding='utf-8')+action_values(store,cls=cls)
        # ADR-011 §4: her brief is the first message (a continuation: her new words in the same session);
        # the program's facts follow it, marked as the program's.
        brief=task.get('brief') or task['goal']
        text=('她接着交代：\n' if task.get('continues_task_id') else '')+brief
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
        text+='\n\n—— 程序附注（不是她说的话）——\n'+json.dumps(facts,ensure_ascii=False)
        if task.get('integration_profile') == 'owner':
            text+='\n本任务继承本机 owner 工作域的集成能力。适配器代码在通道包里，只用 development_* 工具（project 填通道包）修改。integration_test 把候选里的适配器目录冻结成一份（argv 里写 /app）来试跑；integration_start 只启用已发布（development_publish 之后）的适配器版本，宿主重启后也恢复已发布的版本。/data 可写，test 与启用数据分开。/integration/config.json 是端点与 adapter 配置。运行直接连配置里的端点，用的是真实配置：试跑也能真的对平台做动作，试跑只做读，发消息留给出站队列和已发布的适配器。integration_test 最长60秒；integration_start 持续到明确停止并可随宿主恢复；未要求持续运行就不要 start。integration_status/stop 可观察/停止。失败回本会话自行修复；不能把进程 RUNNING 当平台连接或发送成功。import_integration_artifact 只能按配置里已有的端点别名取一个产物（不是任意 URL 下载器），字节由平台写进本次任务工作区的相对路径，默认不覆盖、有大小上限，失败会给出真实原因（端点未知、URL 被拒、路径越界、目标已存在、超限、HTTP 状态）。'
        if 'render_svg' in task.get('allowed_capabilities',()):
            text+='\n要把 SVG 变成图（截图、预览、发出去）：write_file 写好 .svg，再用 render_svg；PNG 落进 /task/images 并登记成她自己的图，用 read_image 传 artifact_id 亲眼看过再交。SVG 链接的外部图片不会加载，要用就内嵌成 data: URI。'
        if 'generate_image' in task.get('allowed_capabilities',()):
            text+='\n要画图先用 generate_image：本机的生图服务，图直接落进 /task 并登记成她自己的图，之后能随消息发出去（群里只发全年龄的图）。先用 workflows=true 看有哪些路线、各要什么样的提示词；画完用 read_image 传 artifact_id 亲眼看，不对就改了再画。外部公开的生图服务也可以用，但那样的图进不了工作区，只能给链接。'
        if task.get('development_grant'):
            text+='\n你可使用 development_* 工具直接编辑可发布的 Asuna 项目候选。development_files/read/write 返回真实文件；development_run 在候选目录里运行命令（宿主沙箱：只能写候选目录；命令是本机原生的，Windows 上没有 sh，用 python3 写脚本）并返回 stdout/stderr/退出码；development_database_read 只读同一个真实数据库中的原始记录（没有另一个测试库）。失败检查只提供诊断，可继续修复。development_publish 冻结候选、运行不消费消息的最低启动探针并应用通过的改动，实际宿主重启后结果再进入同一角色场景；无需 Codex 审查。普通 /task 仍是原持久工作区，不是这个候选。技能也在候选里（角色包 skills/<kebab-case-name>/SKILL.md），同样只用 development_* 修改、经 development_publish 生效；原生 skill 工具读取的是已发布的版本。修改认知核需显式 project="core"。发布与否由你判断。'
        # Her words that arrived before this run started belong to its first message.
        early=self.pending_messages(task)
        if early:
            text+='\n\n她后来又补充：\n'+'\n'.join(row['text'] for row in early)
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
            text='她在你做事时补充了（你可能还没看到）：\n'+'\n'.join(row['text'] for row in late)
            self.delivered(late)
        artifacts=list(self.service.store.db.artifacts.find({'task_id':task['_id'],'intent_revision':task['intent_revision'],'state':'DONE'}))
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
            finished=self.service.store.put('tasks',{**current,'state':'RETURNED' if returned else 'BLOCKED',
                'result':result,'finished_at':now(),'feedback_state':'READY'},expected=current['revision'],stream=task['_id'])
        self.service.collab(finished,'status',{'state':'done' if returned else 'failed'},'status:'+task['_id']+':finished')
        return finished

    def pending_messages(self,task):
        return list(self.service.store.db.task_messages.find({'task_id':task['_id'],'from':'character','delivered':False}).sort('created_at',1))

    def delivered(self,rows):
        store=self.service.store
        for row in rows:
            current=store.db.task_messages.find_one({'_id':row['_id']})
            if current and not current.get('delivered'):
                store.put('task_messages',{**current,'delivered':True,'delivered_at':now()},expected=current['revision'],stream=current['task_id'])

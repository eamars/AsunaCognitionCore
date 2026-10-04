from contextlib import ExitStack
from .state import Store
from .context import ContextBuilder
from .coordinator import Coordinator
from .retrieval import Retrieval
from .history_query import HistoryQueryService
from .discussion_digest import DiscussionDigestService
from .tasks import TaskService,ToolBroker,Executor
from .router import Router


class Application:
    """Core services owned by RuntimeHost; also used by explicit debug diagnostics."""
    def __init__(self,config,evidence,database=None,*,lane_factory=None,broker_http=False,development_factory=None):
        self.config,self.evidence=config,evidence
        if lane_factory is None:
            raise ValueError('NATIVE_HOST_LANE_REQUIRED: start Asuna through the DSH Web profile')
        self.lane_factory=lane_factory
        self.broker_http=broker_http
        self.development_factory=development_factory
        self.store=Store(config,database);self.stack=ExitStack()
    def __enter__(self):
        try:
            self.store.migrate();self.stack.callback(self.store.client.close)
            self.retrieval=Retrieval(self.store,self.evidence);self.stack.callback(self.retrieval.close)
            self.service=TaskService(self.store)
            self.broker=ToolBroker(self.service,serve_http=self.broker_http);self.stack.callback(self.broker.close)
            def persona_jobs(task,args):
                from .persona_jobs import JobRunner
                result=JobRunner(self.store,self.config['chat']['persona'],retrieval=self.retrieval).run(
                    args['job'],dry_run=bool(args.get('dry_run',True)),args=args.get('args') or {})
                from .persona_jobs import tool_result
                return tool_result(result)          # status, counts and artifact ids only (§7.4)
            self.broker.persona_jobs=persona_jobs
            if self.development_factory:
                self.broker.development=self.development_factory(self.config,self.store)
            # P1-b: the trusted read-only history entry reuses this store and retrieval;
            # the broker binds every call to the calling task's own scene and epoch.
            self.history=HistoryQueryService(self.store,self.retrieval);self.broker.history=self.history
            # P1-c: on-demand group discussion digest reads the very same store/retrieval;
            # no new service, port or collection, and nothing is ever sent to QQ.
            self.digest=DiscussionDigestService(self.store,self.retrieval);self.broker.digest=self.digest
            # 看图（Pull）：同一个 store 与既有 GridFS BlobStore；不新建集合、不新建端口、不另起视觉服务。
            from .vision import VisionService
            self.vision=VisionService(self.store);self.broker.vision=self.vision
            self.lanes=ExitStack();self.stack.callback(self.lanes.close)
            self.models_ready=False
            self._start_lanes(self.config)
            return self
        except BaseException:self.stack.close();raise
    def __exit__(self,*args):self.stack.close()

    def _start_lanes(self, config):
        try:
            self.evidence.record('lane.character.start', {})
            self.character=self.lanes.enter_context(self.lane_factory(config,self.store,self.evidence))
            self.evidence.record('lane.character.ready', {})
            self.evidence.record('lane.executor.start', {})
            self.executor_lane=self.lanes.enter_context(self.lane_factory(config,self.store,self.evidence,'executor'))
            self.evidence.record('lane.executor.ready', {})
            # Same configured action model, separate tool-free native session
            # for low-priority dialogue summaries; no third model deployment.
            self.evidence.record('lane.summary.start', {})
            self.summary_lane=self.lanes.enter_context(self.lane_factory(config,self.store,self.evidence,'summary'))
            self.evidence.record('lane.summary.ready', {})
            self.coordinator=Coordinator(self.store,self.character,context=ContextBuilder(self.store,self.retrieval))
            if ((config.get('_native_routes') or {}).get('appraiser') or {}).get('provider'):
                # Optional third responsibility route: proposes affect events only (ADR-009 §6.7).
                from .affect import Appraiser
                self.appraiser_lane=self.lanes.enter_context(self.lane_factory(config,self.store,self.evidence,'appraiser'))
                self.coordinator.appraiser=Appraiser(self.store,self.appraiser_lane)
            self.broker.consult_character=self.coordinator.consult
            self.executor=Executor(self.service,self.executor_lane,self.broker)
            self.router=Router(self.store,self.coordinator,self.executor,self.service)
            self.models_ready=True
        except BaseException:
            self.lanes.close()
            self.models_ready=False
            raise

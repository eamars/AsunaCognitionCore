from contextlib import ExitStack
from .state import Store
from .context import ContextBuilder
from .coordinator import Coordinator
from .dsh_lane import DshLane
from .retrieval import Retrieval
from .tasks import TaskService,ToolBroker,Executor
from .router import Router


class Application:
    """Core services owned by RuntimeHost; also used by explicit debug diagnostics."""
    def __init__(self,config,evidence,database=None):
        self.config,self.evidence=config,evidence
        self.store=Store(config,database);self.stack=ExitStack()
    def __enter__(self):
        try:
            self.store.migrate();self.stack.callback(self.store.client.close)
            self.retrieval=Retrieval(self.store,self.evidence);self.stack.callback(self.retrieval.close)
            self.service=TaskService(self.store)
            self.broker=ToolBroker(self.service);self.stack.callback(self.broker.close)
            self.lanes=ExitStack();self.stack.callback(self.lanes.close)
            self.models_ready=False
            self._start_lanes(self.config)
            return self
        except BaseException:self.stack.close();raise
    def __exit__(self,*args):self.stack.close()

    def _start_lanes(self, config):
        try:
            self.character=self.lanes.enter_context(DshLane(config,self.store,self.evidence))
            self.executor_lane=self.lanes.enter_context(DshLane(config,self.store,self.evidence,'executor',self.broker.rows,self.broker.token))
            self.coordinator=Coordinator(self.store,self.character,context=ContextBuilder(self.store,self.retrieval,self.executor_lane.skill_catalog))
            self.broker.consult_character=self.coordinator.consult
            self.executor=Executor(self.service,self.executor_lane,self.broker)
            self.router=Router(self.store,self.coordinator,self.executor,self.service)
            self.models_ready=True
        except BaseException:
            self.lanes.close()
            self.models_ready=False
            raise

    def replace_models(self, config):
        """Only the idle Web controller may call this; preserve both lane identities."""
        previous=self.config
        self.models_ready=False
        self.lanes.close()
        try:
            self._start_lanes(config)
        except Exception:
            self._start_lanes(previous)
            raise
        self.config=config
        self.store.config=config

from contextlib import ExitStack
from .state import Store
from .context import ContextBuilder
from .coordinator import Coordinator
from .dsh_lane import DshLane
from .retrieval import Retrieval
from .tasks import TaskService,ToolBroker,Executor
from .router import Router


class Application:
    """One production route shared by CLI, scene simulator and evaluations."""
    def __init__(self,config,evidence,database=None):
        self.config,self.evidence=config,evidence
        self.store=Store(config,database);self.stack=ExitStack()
    def __enter__(self):
        try:
            self.store.migrate();self.stack.callback(self.store.client.close)
            self.retrieval=Retrieval(self.store,self.evidence);self.stack.callback(self.retrieval.close)
            self.service=TaskService(self.store)
            self.broker=ToolBroker(self.service);self.stack.callback(self.broker.close)
            self.character=self.stack.enter_context(DshLane(self.config,self.store,self.evidence))
            self.executor_lane=self.stack.enter_context(DshLane(self.config,self.store,self.evidence,'executor',self.broker.rows,self.broker.token))
            self.coordinator=Coordinator(self.store,self.character,context=ContextBuilder(self.store,self.retrieval))
            self.executor=Executor(self.service,self.executor_lane,self.broker)
            self.router=Router(self.store,self.coordinator,self.executor,self.service)
            return self
        except BaseException:self.stack.close();raise
    def __exit__(self,*args):self.stack.close()

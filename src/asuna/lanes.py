from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol
from .state import Store, Conflict
from .evidence import sha, canonical


@dataclass
class LaneResult:
    content: str
    finish_reason: str='stop'
    reasoning: str | None=None
    tool_calls: list=field(default_factory=list)
    request_refs: list=field(default_factory=list)
    receipt: str | None=None


class Lane(Protocol):
    def generate(self, session: str, operation: str, phase: str, text: str, system: str, *, scope_key=None,policy_epoch=None) -> LaneResult: ...


class FakeLane:
    """Deterministic engineering test double only; never selected for live runs."""
    def __init__(self, store: Store, outputs: list[LaneResult]):
        self.store,self.outputs,self.calls,self.histories = store,iter(outputs),[],{}

    def generate(self, session, operation, phase, text, system, *, scope_key=None,policy_epoch=None):
        existing=self.store.db.lane_receipts.find_one({'_id':operation})
        if existing:
            return LaneResult(**existing['result'])
        history=self.histories.setdefault(session,[])
        request={'messages':[{'role':'system','content':system},*history,{'role':'user','content':text}],'tools':[],'mode':'fake','phase':phase}
        self.calls.append(request)
        self.store.audit(operation,'fake.request',request)
        value=next(self.outputs)
        value.receipt=operation
        self.store.put('lane_receipts',{'_id':operation,'result':vars(value),'request':request,'scope_key':'operator'},stream=operation)
        history.extend([{'role':'user','content':text},{'role':'assistant','content':value.content}])
        return value

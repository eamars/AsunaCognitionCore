"""The model-lane contract: `LaneResult` is what one turn returns (its text, tool calls and everything she said),
and `FakeLane` is the scripted stand-in tests use instead of a model.

The live lane is `NativeLane` in native_worker.py, which runs each turn in a native DSH session.
"""
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
    diagnostic: dict | None=None
    delivery: dict | None=None     # what a native role notice left out because the session still shows it
    said: list | None=None         # every text she wrote in the turn, in order (beside a tool call too)
    seen_inputs: list | None=None  # platform lines in her view for the first time this turn (by input id)


class Lane(Protocol):
    def generate(self, session: str, operation: str, phase: str, text: str, system: str, *, scope_key=None,policy_epoch=None) -> LaneResult: ...


@dataclass
class FakeTurn:
    """A scripted character turn for FakeLane: tool calls in order, then the final text."""
    calls: list = field(default_factory=list)      # [(tool name, args)]
    content: str = ''
    finish_reason: str = 'stop'
    said: list = field(default_factory=list)       # texts she wrote beside her tool calls, before the final one
    seen: list = field(default_factory=list)       # platform input ids that came into her view during the turn


class FakeLane:
    """Deterministic engineering test double only; never selected for live runs."""
    def __init__(self, store: Store, outputs: list):
        self.store,self.outputs,self.calls,self.histories = store,iter(outputs),[],{}
        self.tool_results=[]          # (operation, call_id, tool, args, result | refusal text, ok)

    def generate(self, session, operation, phase, text, system, *, scope_key=None,policy_epoch=None,
                 tools=None, handler=None, **_delivery):
        existing=self.store.db.lane_receipts.find_one({'_id':operation})
        if existing:
            return LaneResult(**existing['result'])
        history=self.histories.setdefault(session,[])
        request={'messages':[{'role':'system','content':system},*history,{'role':'user','content':text}],
                 'tools':list(tools or []),'mode':'fake','phase':phase}
        self.calls.append(request)
        self.store.audit(operation,'fake.request',request)
        value=next(self.outputs)
        if isinstance(value,FakeTurn):
            value=self._run_turn(operation,value,tools,handler)
        value.receipt=operation
        self.store.put('lane_receipts',{'_id':operation,'result':vars(value),'request':request,'scope_key':'operator'},stream=operation)
        history.extend([{'role':'user','content':text},{'role':'assistant','content':value.content}])
        return value

    def _run_turn(self, operation, turn, tools, handler):
        """Each scripted call reaches the coordinator's handler, as a native turn's calls do."""
        from .role_tools import Refused
        made=[]
        for index,(name,args) in enumerate(turn.calls):
            call_id=operation+'#'+str(index)
            made.append({'type':'tool-call','name':name,'id':call_id})
            if name not in (tools or ()):
                self.tool_results.append((operation,call_id,name,args,'NOT_EXPOSED',False))
                continue
            try:
                result,conclude=handler(call_id,name,args)
            except Refused as exc:
                self.tool_results.append((operation,call_id,name,args,str(exc),False))
                continue
            self.tool_results.append((operation,call_id,name,args,result,True))
            if conclude:
                return LaneResult(content='',finish_reason=turn.finish_reason,tool_calls=made,
                                  said=list(turn.said) or None,seen_inputs=list(turn.seen) or None)
        return LaneResult(content=turn.content,finish_reason=turn.finish_reason,
                          said=[*turn.said,turn.content] if turn.said else None,seen_inputs=list(turn.seen) or None)

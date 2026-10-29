"""The core's answer to "may this sender speak in this conversation?" (ADR-107).

This adapter holds no admission policy: no list of people, groups or senders, no block list, and no idea whether the
deployment is open or closed. It asks the core (`POST …/admission`) and reuses an answer for the time the core names
(`ttl_seconds`). The core decides again when it takes a line, so a reused answer can cost one refused post and never
an admission; a post the core refuses drops the answer it was sent on (`forget`).

A conversation is `("group", id)` or `("dm", id)`. Asking never blocks the WebSocket reader: the reader only consults
the cache (`cached`); the lanes and the platform-work threads ask.
"""
from collections import OrderedDict
import threading
import time

CAPACITY = 4096          # answers kept; the oldest is dropped first
BATCH = 200              # asks in one request (the core takes this many)
ROUTES_PAGE = 500        # routes in one page of the core's list
PAGES = 400              # pages read at most (200,000 routes)


class AdmissionAway(Exception):
    """The core did not answer, or is not taking requests now (no answer, 5xx, its key not taken): wait and ask again."""

    def __init__(self, res=None):
        super().__init__(getattr(res, "error", None) or getattr(res, "code", None) or "away")
        self.res = res


class AdmissionUnsupported(Exception):
    """The core predates the admission endpoint (404): lines wait, nothing is posted without a verdict."""

    def __init__(self, res=None):
        super().__init__("unsupported")
        self.res = res


class AdmissionRejected(Exception):
    """The core refused the request itself (a 4xx other than the two above): a bug in this adapter's ask."""

    def __init__(self, res=None):
        super().__init__("rejected")
        self.res = res


class Answer:
    __slots__ = ("verdict", "route_id", "conversation", "known", "code", "scope", "expires")

    def __init__(self, verdict, conversation, route_id=None, known=False, code=None, scope=None, expires=0.0):
        self.verdict, self.conversation, self.route_id = verdict, conversation, route_id
        self.known, self.code, self.scope, self.expires = known, code, scope, expires

    @property
    def admitted(self):
        return self.verdict == "admitted"

    def __repr__(self):
        return "Answer(%s %s:%s route=%s scope=%s)" % (self.verdict, self.conversation[0], self.conversation[1],
                                                       self.route_id, self.scope)


def lane_key(conversation):
    """The name a conversation's lines share, whether or not their route is known: order is a property of it."""
    return "%s:%s" % conversation


def conversation_of(envelope):
    """The conversation an envelope (or a spooled line) belongs to."""
    group = envelope.get("group_id")
    return ("group", str(group)) if group else ("dm", str(envelope.get("sender_id")))


def _ask_body(conversation, sender=None):
    body = {"conversation": {"type": conversation[0], "id": conversation[1]}}
    if sender and conversation[0] == "group":
        body["sender_id"] = sender
    return body


class Admission:
    def __init__(self, host, account, counters, clock=time.monotonic):
        self.host, self.account, self.counters, self.clock = host, str(account), counters, clock
        self._cache = OrderedDict()
        self._lock = threading.Lock()
        self._epoch = None          # the core's start the answers kept belong to

    # ---- the cache (any thread, no I/O) ---------------------------------
    def cached(self, conversation, sender=None):
        """The answer still good for this sender in this conversation, or None. An answer for the conversation alone
        that admits says nothing about a sender; one that refuses or blocks says it of everyone there."""
        now = self.clock()
        kind, target = conversation
        keys = [(kind, target, None)] + ([(kind, target, sender)] if sender and kind == "group" else [])
        with self._lock:
            for key in keys:
                answer = self._cache.get(key)
                if answer is None or answer.expires <= now:
                    continue
                if key[2] is None and kind == "group" and sender and answer.admitted:
                    continue                  # the group is admitted: that says nothing yet about this sender
                self.counters.inc("admission_cache_hits")
                return answer
        return None

    def forget(self, conversation, sender=None):
        kind, target = conversation
        with self._lock:
            for key in ((kind, target, None), (kind, target, sender)):
                self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def _epoch_of(self, res):
        """The core says which start of it answered; settings are applied by a new start, so answers kept from
        another one are dropped."""
        epoch = res.obj.get("epoch") if isinstance(res.obj, dict) else None
        if epoch is not None and epoch != self._epoch:
            if self._epoch is not None:
                self.clear()
            self._epoch = epoch

    def _remember(self, conversation, sender, answer):
        if answer.expires <= self.clock():
            return
        kind, target = conversation
        key = (kind, target, None if kind == "dm" or answer.scope == "conversation" or sender is None else sender)
        with self._lock:
            self._cache[key] = answer
            self._cache.move_to_end(key)
            while len(self._cache) > CAPACITY:
                self._cache.popitem(last=False)

    # ---- asking the core (a lane or a platform-work thread) -------------
    def ask(self, conversation, sender=None):
        """The core's answer for one sender in one conversation (or for the conversation alone)."""
        return self._ask([(conversation, sender)])[0]

    def ask_many(self, conversations):
        """The answers for conversations alone, in order (the groups a member-list round may fetch)."""
        out = []
        for index in range(0, len(conversations), BATCH):
            out += self._ask([(conversation, None) for conversation in conversations[index:index + BATCH]])
        return out

    def ask_routes(self, route_ids):
        """{route id: its answer} for route ids the core named (catch-up's cursors and the settings' names)."""
        route_ids = list(route_ids)
        found = {}
        for index in range(0, len(route_ids), BATCH):
            chunk = route_ids[index:index + BATCH]
            answers = self._post([{"route_id": route_id} for route_id in chunk])
            for route_id, raw in zip(chunk, answers):
                answer = self._parse(raw, None)
                if answer.admitted:
                    self._remember(answer.conversation, None, answer)
                found[route_id] = answer
        return found

    def routes(self):
        """[(route id, conversation)] the core serves and no block list stops (catch-up's `all`), read a page at a time."""
        out, after = [], ""
        for _page in range(PAGES):
            res = self.host.get_routes(after, ROUTES_PAGE)
            self._settle(res)
            self._epoch_of(res)
            for row in res.obj["routes"]:
                conversation = row.get("conversation") if isinstance(row, dict) else None
                if isinstance(conversation, dict) and isinstance(row.get("route_id"), str):
                    out.append((row["route_id"], (str(conversation.get("type")), str(conversation.get("id")))))
            after = res.obj.get("next")
            if not after:
                return out
        return out

    def observe(self, res):
        """Any answer of the core's outbox poll: it carries the core's start, and a poll that gets no answer means the
        core is going away, so what was kept is dropped before a refusal given by the last start can outlive it."""
        if res.kind == "retry":
            self.clear()
        elif isinstance(res.obj, dict):
            self._epoch_of(res)

    def _ask(self, pairs):
        answers = self._post([_ask_body(conversation, sender) for conversation, sender in pairs])
        out = []
        for (conversation, sender), raw in zip(pairs, answers):
            answer = self._parse(raw, conversation)
            self._remember(conversation, sender, answer)
            out.append(answer)
        return out

    def _post(self, asks):
        self.counters.inc("admission_asked", len(asks))
        res = self.host.post_admission({"account_id": self.account, "asks": asks})
        self._settle(res)
        self._epoch_of(res)
        answers = res.obj["answers"]
        if len(answers) != len(asks):
            self.counters.inc("admission_rejected")
            raise AdmissionRejected(res)
        return answers

    def _settle(self, res):
        """Raise what a request that did not give an answer means; return when it did."""
        if res.kind == "accepted":
            return
        error = res.obj.get("error") if isinstance(res.obj, dict) else None
        if res.kind == "retry" or (res.kind == "reject" and res.code == 403 and error == "CHANNEL_AUTH_REQUIRED"):
            self.counters.inc("admission_away")
            self.clear()                  # the core is restarting or its settings are being applied: ask afresh after
            raise AdmissionAway(res)
        if res.kind == "reject" and res.code == 404 and error == "UNKNOWN_CHANNEL_ENDPOINT":
            self.counters.inc("admission_unsupported")
            raise AdmissionUnsupported(res)
        self.counters.inc("admission_rejected")
        raise AdmissionRejected(res)

    def _parse(self, raw, conversation):
        verdict = raw.get("verdict") if isinstance(raw, dict) else None
        if verdict not in ("admitted", "refused", "blocked"):
            self.counters.inc("admission_rejected")
            raise AdmissionRejected()
        ttl = raw.get("ttl_seconds")
        ttl = ttl if isinstance(ttl, (int, float)) and not isinstance(ttl, bool) and 0 < ttl <= 3600 else 0
        said = raw.get("conversation") if isinstance(raw.get("conversation"), dict) else None
        if said is not None:
            conversation = (str(said.get("type")), str(said.get("id")))
        return Answer(verdict, conversation, route_id=raw.get("route_id") if verdict == "admitted" else None,
                      known=raw.get("known") is True, code=raw.get("code"), scope=raw.get("scope"),
                      expires=self.clock() + ttl)

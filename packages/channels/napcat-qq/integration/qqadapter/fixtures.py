"""Built-in placeholder fixtures for the offline self checks.

Every id here is a placeholder in the `9000000xx` block: it is not a real QQ
account, group or member, and no adapter behaviour depends on the specific
digits -- only on their *shape* (one DM the owner listed, four listed groups whose
member snapshots overlap so cross-group isolation is observable, one group and one
sender nobody listed).

Who may speak is the core's to say (ADR-107), so the deployment's policy is a
double of the core here: `FakeCore` answers the adapter's questions the way the
fixture deployment would be answered (closed or open, with block lists). The
core's own rules are tested in tests/test_channel_admission.py, not here.

Nothing here opens a socket: `raw_config()` returns a plain dict that goes
through the real `Config` parser, so the fixtures exercise the same validation
a deployment config does.
"""

# --- placeholder identities (9000000xx block, never a real QQ id) ----------
ACCOUNT = "900000000"          # the logged-in adapter account
OWNER_DM = "900000010"         # the private-chat peer the DM route is bound to

GROUPS = ("900000001", "900000002", "900000003", "900000004")

# Member snapshots overlap on purpose: OWNER_DM and 900000102 are in more than
# one group, 900000101 is in the first group only, so "member of another group"
# and "member of this group" are different answers here, as they are in QQ.
MEMBERS = {
    GROUPS[0]: (OWNER_DM, "900000101", "900000102", "900000103"),
    GROUPS[1]: ("900000102", "900000104", "900000105"),
    GROUPS[2]: ("900000103", "900000106"),
    GROUPS[3]: ("900000107", "900000108", "900000109"),
}

# The negative cases, also placeholders:
OUTSIDER = "900000199"          # on no member snapshot anywhere
UNKNOWN_SENDER = "900000013"    # a DM peer with no route
UNKNOWN_GROUP = "900000012"     # neither allowlisted nor routed
UNROUTED_GROUP = GROUPS[1]      # allowlisted but its route is removed by _loose_cfg
BLOCKED_SENDER = "900000101"    # a member of the first group that policy can block
BLOCKED_GROUP = GROUPS[3]       # a fixture group that policy can block

DM_ROUTE = "owner-dm"

# --- placeholder endpoints and secrets ------------------------------------
NAPCAT_HOST = "127.0.0.1"
NAPCAT_PORT = 30001
HOST_HOST = "127.0.0.1"
HOST_PORT = 8766
NAPCAT_TOKEN = "placeholder-napcat-token"
# The digit run below is filler to reach the host token's minimum length; it is a
# placeholder credential, not anyone's QQ number.
HOST_TOKEN = "placeholder-host-token-0123456789abcdef"      # >= 24 chars, not a secret; personal-scan: ok
CHANNEL_ID = "qq"


def raw_config(media_mode=None, account=ACCOUNT, catchup=None):
    """A complete config document with placeholder ids, valid for `Config`."""
    adapter = {
        "napcat": {"transport": "websocket_forward",
                   "url": "ws://%s:%d" % (NAPCAT_HOST, NAPCAT_PORT),
                   "token": NAPCAT_TOKEN, "account_id": account},
        "host": {"base_url": "http://%s:%d" % (HOST_HOST, HOST_PORT),
                 "token": HOST_TOKEN, "channel_id": CHANNEL_ID},
    }
    if media_mode:
        adapter["media_mode"] = media_mode
    if catchup is not None:
        adapter["catchup"] = catchup
    return {"endpoints": {"napcat": {"host": NAPCAT_HOST, "port": NAPCAT_PORT},
                          "host": {"host": HOST_HOST, "port": HOST_PORT}},
            "adapter": adapter}


class Policy:
    """What the fixture deployment's core would decide: the owner's DM and the four groups listed (with their member
    snapshots) when closed; anyone not blocked when open. A double of the core's rules, enough for the adapter's
    checks; the real ones are the core's own tests."""

    def __init__(self, admission="explicit", blocked_senders=(), blocked_groups=()):
        self.admission = admission
        self.blocked_senders, self.blocked_groups = set(blocked_senders), set(blocked_groups)

    def listed(self):
        """{route id: ("dm" or "group", id)} of the routes the owner listed."""
        return {DM_ROUTE: ("dm", OWNER_DM), **{"group-%s" % gid: ("group", gid) for gid in GROUPS}}

    def judge(self, ask):
        listed = self.listed()
        if "route_id" in ask:
            name = ask["route_id"]
            if name in listed:
                kind, target = listed[name]
            elif self.admission == "automatic" and name.startswith(("auto-dm-", "auto-group-")):
                kind, target = name.split("-", 2)[1:]
            else:
                return {"verdict": "refused", "code": "CHANNEL_ROUTE_NOT_AUTHORIZED", "scope": "conversation", "ttl_seconds": 60}
            sender = None
        else:
            kind, target = ask["conversation"]["type"], ask["conversation"]["id"]
            sender = ask.get("sender_id")
        conversation = {"type": kind, "id": target}
        if kind == "dm":
            sender = target
        scope = "conversation" if kind == "dm" or sender is None else "sender"
        refuse = lambda code, where, verdict="refused": {"verdict": verdict, "code": code, "scope": where, "ttl_seconds": 60}
        if kind == "group" and target in self.blocked_groups:
            return refuse("CHANNEL_BLOCKED", "conversation", "blocked")
        if sender is not None and sender in self.blocked_senders:
            return refuse("CHANNEL_BLOCKED", scope, "blocked")
        route_id = next((name for name, where in listed.items() if where == (kind, target)), None)
        known = route_id is not None and (sender is None or kind == "dm" or sender in MEMBERS.get(target, ()))
        if known:
            return {"verdict": "admitted", "route_id": route_id, "conversation": conversation, "known": True,
                    "ttl_seconds": 300}
        if self.admission != "automatic":
            return refuse("CHANNEL_IDENTITY_DENIED", "sender" if route_id else "conversation")
        return {"verdict": "admitted", "route_id": route_id or "auto-%s-%s" % (kind, target),
                "conversation": conversation, "known": False, "ttl_seconds": 60}


class FakeCore:
    """SUBSTITUTE for the core's admission and departure endpoints: answers from a `Policy`, keeps every question
    it was asked, and can be made to fail the three ways a core can (`down`: away, unsupported or rejected)."""

    def __init__(self, policy=None):
        from .hostapi import Result
        self._result = Result
        self.policy = policy or Policy()
        self.asked, self.departures, self.down, self.epoch = [], [], None, "start-1"

    def _failed(self):
        Result = self._result
        if self.down == "away":
            return Result("retry", None, None, error="URLError")
        if self.down == "unsupported":
            return Result("reject", 404, {"error": "UNKNOWN_CHANNEL_ENDPOINT"})
        if self.down == "rejected":
            return Result("reject", 400, {"error": "INVALID_ADMISSION_ASK"})
        return None

    def post_admission(self, body):
        self.asked.append(body)
        return self._failed() or self._result("accepted", 200, {"answers": [self.policy.judge(ask) for ask in body["asks"]],
                                                                "epoch": self.epoch})

    def get_routes(self, after="", limit=500):
        rows = sorted(({"route_id": name, "conversation": {"type": kind, "id": target}}
                       for name, (kind, target) in self.policy.listed().items()
                       if target not in (self.policy.blocked_groups if kind == "group" else self.policy.blocked_senders)
                       and name > after), key=lambda row: row["route_id"])
        page = rows[:limit]
        return self._failed() or self._result("accepted", 200, {
            "routes": page, "next": page[-1]["route_id"] if len(rows) > limit else None, "epoch": self.epoch})

    def post_departure(self, body):
        self.departures.append(body)
        return self._failed() or self._result("accepted", 200, {"status": "ended"})


def load_config(admission="explicit", blocked_senders=(), blocked_groups=(), **kwargs):
    """The same document through the real parser, so fixtures are validated exactly like a deployment config. The
    policy the fixture core would apply rides on the object as `fixture_policy` (the checks' own, not the adapter's)."""
    from .config import Config
    cfg = Config(raw_config(**kwargs), "fixture:placeholder")
    cfg.fixture_policy = Policy(admission, blocked_senders, blocked_groups)
    return cfg


def raw_of(cfg):
    """A deep copy of a loaded config's raw document, for mutation cases."""
    import json
    return json.loads(json.dumps(cfg.raw))


def members_of(group_id):
    return set(MEMBERS[group_id])


def first_member(group_id):
    return sorted(MEMBERS[group_id])[0]


def describe():
    """One line saying what the fixture deployment looks like (no secrets)."""
    return "account=%s dm=%s groups=%s members=%s" % (
        ACCOUNT, OWNER_DM, ",".join(GROUPS),
        ",".join("%s:%d" % (gid, len(MEMBERS[gid])) for gid in GROUPS))

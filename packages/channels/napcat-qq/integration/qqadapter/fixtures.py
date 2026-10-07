"""Built-in placeholder fixtures for the offline self checks.

Every id here is a placeholder in the `9000000xx` block: it is not a real QQ
account, group or member, and no adapter behaviour depends on the specific
digits -- only on their *shape* (one DM route, four group routes whose member
snapshots overlap so cross-group isolation is observable, one allowlisted group
without a route, one sender and one group nobody authorized).

Before this module the group coverage came from a machine-local route dump with
real group numbers in it, so a clean checkout could not run those checks at all
and the result changed with whatever the machine under test was authorized for.
The self checks now always run against these placeholders and give the same
answer everywhere; the real configuration is only *cross-checked* for shape and
bounds (see `selftest._check_live_config`), which is a separate, optional step.

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


def group_route(group_id):
    """The route blob the real parser expects for one authorized group."""
    return {"message_type": "group",
            "target": {"type": "group", "id": group_id},
            "allowed_sender_ids": list(MEMBERS[group_id])}


def group_routes(group_ids=GROUPS):
    return {"group-%s" % gid: group_route(gid) for gid in group_ids}


def dm_route():
    return {"message_type": "private", "sender_id": OWNER_DM,
            "target": {"type": "dm", "id": OWNER_DM}}


def preview():
    """The built-in stand-in for the old machine-local group-route dump:
    every allowed group has a route, every route is allowed."""
    return {"allowed_group_ids": list(GROUPS), "routes": group_routes()}


def raw_config(admission="explicit", routes="default", media_mode=None,
               blocked_senders=(), blocked_groups=(), account=ACCOUNT,
               allowed_group_ids=GROUPS, allowed_private=(OWNER_DM,)):
    """A complete config document with placeholder ids, valid for `Config`.

    `routes` is "default" (one DM route + the four group routes), "none" (no
    routes at all, which only `admission=automatic` may load) or a dict to use
    verbatim.
    """
    if routes == "default":
        route_map = {DM_ROUTE: dm_route()}
        route_map.update(group_routes())
    elif routes == "none":
        route_map = {}
    else:
        route_map = {key: dict(blob) for key, blob in routes.items()}
    adapter = {
        "napcat": {"transport": "websocket_forward",
                   "url": "ws://%s:%d" % (NAPCAT_HOST, NAPCAT_PORT),
                   "token": NAPCAT_TOKEN, "account_id": account},
        "host": {"base_url": "http://%s:%d" % (HOST_HOST, HOST_PORT),
                 "token": HOST_TOKEN, "channel_id": CHANNEL_ID},
        "admission": admission,
        "allowed_private_user_ids": list(allowed_private),
        "allowed_group_ids": list(allowed_group_ids),
        "routes": route_map,
    }
    if blocked_senders:
        adapter["blocked_senders"] = list(blocked_senders)
    if blocked_groups:
        adapter["blocked_groups"] = list(blocked_groups)
    if media_mode:
        adapter["media_mode"] = media_mode
    return {"endpoints": {"napcat": {"host": NAPCAT_HOST, "port": NAPCAT_PORT},
                          "host": {"host": HOST_HOST, "port": HOST_PORT}},
            "adapter": adapter}


def load_config(**kwargs):
    """The same document through the real parser, so fixtures are validated
    exactly like a deployment config."""
    from .config import Config
    return Config(raw_config(**kwargs), "fixture:placeholder")


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

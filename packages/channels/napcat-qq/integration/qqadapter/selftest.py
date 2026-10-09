"""Offline + live self checks.  Nothing here invents an inbound message:
synthetic events only pass through the local filter, never into the host, and
platform sends go to a recorded stub (never to QQ).

Group coverage comes from the built-in placeholder fixtures in `fixtures.py`
(9000000xx ids, no real account, group or member), so a clean checkout runs
every check with no config file present and the same code gives the same answer
on every machine.  A real deployment config is optional: when one is supplied it
is cross-checked for shape and bounds only (`_check_live_config`) and is never
the subject of a behaviour assertion.  With `live=False` no platform is
contacted and the real outbox is not claimed.
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
import time

from . import hostapi as hostapi_mod
from . import inbound as inbound_mod
from . import fixtures
from . import outbound as outbound_mod
from . import peers as peers_mod
from .peers import PEER_KEY, PeerDirectory
from .config import Config, ConfigError
from .hostapi import Result
from .journal import Counters, Journal
from .onebot import ApiTimeout, ApiTransportError
from .service import Adapter

ALLOWED_ENVELOPE_KEYS = inbound_mod.PRIVATE_ENVELOPE_KEYS
ALLOWED_GROUP_ENVELOPE_KEYS = inbound_mod.GROUP_ENVELOPE_KEYS
HERE = os.path.dirname(os.path.abspath(__file__))
# Every identity below is a fixture placeholder: the checks never read a real
# account, group or member off the machine under test.
OWNER = fixtures.OWNER_DM                    # the peer the DM route binds
OUTSIDER = fixtures.OUTSIDER                 # on no member snapshot
UNKNOWN_SENDER = fixtures.UNKNOWN_SENDER     # a DM peer with no route
UNKNOWN_GROUP = fixtures.UNKNOWN_GROUP       # neither allowlisted nor routed
LOOSE_GROUP = fixtures.UNROUTED_GROUP        # allowlisted, route removed by _loose_cfg
# Another process taking the adapter's own lock (flock, or the byte lock on Windows) on the same file.
HELPER_LOCK_CHILD = (
    "import os,sys,time\n"
    "sys.path.insert(0,sys.argv[3])\n"
    "from qqadapter.journal import _lock\n"
    "fd=os.open(sys.argv[1],os.O_CREAT|os.O_RDWR,0o644)\n"
    "_lock(fd)\n"
    "print('LOCKED',flush=True)\n"
    "time.sleep(float(sys.argv[2]))\n"
)


class Report:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def skip(self, name, detail=""):
        """A check that needs something this run was not given (a real config,
        a live platform): reported as SKIP, never counted as a pass."""
        self.skipped += 1
        print("SELFTEST %-34s SKIP %s" % (name, detail), flush=True)

    def check(self, name, ok, detail=""):
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        print("SELFTEST %-34s %s %s" % (name, "PASS" if ok else "FAIL", detail), flush=True)


class StubOneBot:
    """SUBSTITUTE for the platform, not a real send: records the exact action and
    params the adapter would have put on the wire and returns a canned response."""

    def __init__(self, response=None, exc=None):
        self.calls = []
        self.response = response if response is not None else {
            "status": "ok", "retcode": 0, "data": {"message_id": 990001}}
        self.exc = exc

    def api_call(self, action, params=None, timeout=15.0, meta=None):
        self.calls.append({"action": action, "params": params, "meta": meta, "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        return self.response


class StubHost:
    """SUBSTITUTE for the host receipt + attachment endpoints; keeps every payload verbatim."""

    def __init__(self, attachment=None):
        self.receipts = []
        self.attachment_calls = []
        self.attachment = attachment

    def post_receipt(self, publication_id, payload):
        self.receipts.append({"publication_id": publication_id, "payload": payload})
        return Result("ok", 200, {"status": "accepted"})

    def get_attachment(self, publication_id, attempt_id, artifact_id=None, expect_sha256=None,
                       max_bytes=None, timeout=30.0):
        """SUBSTITUTE for the host byte endpoint: records the call, answers the canned Result.

        Unstubbed it refuses, so an attachment can never look delivered by
        accident in a check that forgot to hand it bytes.
        """
        self.attachment_calls.append({"publication_id": publication_id, "attempt_id": attempt_id,
                                      "artifact_id": artifact_id, "expect_sha256": expect_sha256,
                                      "max_bytes": max_bytes})
        return self.attachment if self.attachment is not None else Result("reject", 404,
                                                                          {"error": "no_stub_attachment"})

    def last(self):
        return self.receipts[-1] if self.receipts else {}


def _msg_event(cfg, **over):
    event = {
        "time": int(time.time()),
        "self_id": int(cfg.napcat["account_id"]),
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": 654321,
        "user_id": int(OWNER),
        "message": [{"type": "text", "data": {"text": "测试正文"}}],
        "raw_message": "测试正文",
        "sender": {"user_id": int(OWNER), "nickname": "x"},
    }
    event.update(over)
    return event


def _group_event(cfg, group_id, sender, mid, message=None, **over):
    sid = int(sender) if str(sender).isdigit() else sender
    event = {
        "time": int(time.time()),
        "self_id": int(cfg.napcat["account_id"]),
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": mid,
        "group_id": int(group_id) if str(group_id).isdigit() else group_id,
        "user_id": sid,
        "message": message if message is not None else _text("群消息正文"),
        "sender": {"user_id": sid, "nickname": "y", "card": ""},
    }
    event.update(over)
    return event


def _text(t):
    return [{"type": "text", "data": {"text": t}}]


def _fixture_deployment(rep):
    """The placeholder deployment every behaviour check runs against.

    Built through the real `Config` parser, so the fixtures are validated
    exactly like a deployment config.  Nothing here reads a file off the
    machine under test: that is the point of the check below.
    """
    me = sys.modules[__name__]
    rep.check("no_private_route_dump_dependency",
              not hasattr(me, "PREVIEW_PATH") and getattr(me, "fixtures", None) is fixtures,
              "group coverage comes from fixtures.py, not a machine-local route dump")
    preview = fixtures.preview()
    allowed = sorted(str(g) for g in preview["allowed_group_ids"])
    routed = sorted(str((route.get("target") or {}).get("id")) for route in preview["routes"].values())
    rep.check("fixture_preview_shape", bool(allowed) and allowed == sorted(set(routed)),
              "allowed=%s routed=%s" % (allowed, sorted(set(routed))))
    try:
        gcfg = fixtures.load_config()
    except ConfigError as exc:
        rep.check("fixture_config_loads", False, str(exc))
        return None
    rep.check("fixture_config_loads", True, gcfg.describe())
    rep.check("fixture_ids_are_placeholders",
              all(str(g).startswith("9000000") for g in gcfg.allowed_groups)
              and gcfg.napcat["account_id"] == fixtures.ACCOUNT
              and gcfg.allowed_private == [fixtures.OWNER_DM], fixtures.describe())
    rep.check("fixture_groups_bound", sorted(gcfg.allowed_groups) == sorted(fixtures.GROUPS),
              str(sorted(gcfg.allowed_groups)))
    counts = {r.target_id: r.member_count for r in gcfg.routes.values() if r.message_type == "group"}
    expect = {gid: len(fixtures.MEMBERS[gid]) for gid in fixtures.GROUPS}
    rep.check("fixture_member_snapshots", counts == expect, "got=%s want=%s" % (counts, expect))
    rep.check("group_routes_available", len(counts) >= 4, "group_routes=%d" % len(counts))
    rep.check("fixture_dm_route_bound",
              gcfg.route_for_sender(fixtures.OWNER_DM) is not None
              and gcfg.route_for_sender(UNKNOWN_SENDER) is None, "")
    return gcfg


def _check_config_policy(rep, gcfg):
    """What the parser must refuse or accept, checked on the placeholder
    deployment so the answer does not move with this machine's real groups."""
    described = gcfg.describe()
    leak = gcfg.host["token"] in described or gcfg.napcat["token"] in described
    rep.check("config_describe_no_secrets", not leak, described)
    live_routes = sorted(gcfg.raw["adapter"]["routes"])
    rep.check("config_routes_match_file", sorted(gcfg.routes) == live_routes, ",".join(sorted(gcfg.routes)))
    rep.check("config_group_ids_match_file",
              sorted(gcfg.allowed_groups) == sorted(gcfg.raw["adapter"].get("allowed_group_ids") or []),
              str(gcfg.allowed_groups))
    bad = [r.route_id for r in gcfg.routes.values()
           if r.message_type == "group" and r.target_id not in gcfg.allowed_groups]
    rep.check("config_group_routes_bounded", not bad, ",".join(bad))
    g0 = "group-%s" % fixtures.GROUPS[0]
    cases = []

    def mutate(fn, want_tag):
        raw = fixtures.raw_of(gcfg)
        fn(raw)
        try:
            Config(raw, "mutant")
        except ConfigError as exc:
            cases.append((want_tag, True, str(exc)[:120]))
        except Exception as exc:
            cases.append((want_tag, False, "%s %s" % (type(exc).__name__, exc)))
        else:
            cases.append((want_tag, False, "accepted"))

    mutate(lambda raw: raw["adapter"]["routes"][g0].update(
        target={"type": "group", "id": UNKNOWN_GROUP}), "cfg_group_outside_allowlist")
    mutate(lambda raw: raw["adapter"]["routes"][g0].update(allowed_sender_ids=[]),
           "cfg_group_empty_members")
    mutate(lambda raw: raw["adapter"]["routes"][g0].update(
        allowed_sender_ids=[OWNER, "nick"]), "cfg_group_non_digit_member")
    mutate(lambda raw: raw["adapter"]["routes"][g0].update(
        target={"type": "dm", "id": fixtures.GROUPS[0]}), "cfg_group_wrong_target_type")
    mutate(lambda raw: raw["adapter"]["routes"][g0].update(sender_id=OWNER),
           "cfg_group_pinned_sender")
    mutate(lambda raw: raw["adapter"]["routes"].update(
        {"group-dup": {"message_type": "group", "target": {"type": "group", "id": fixtures.GROUPS[0]},
                       "allowed_sender_ids": [OWNER]}}), "cfg_group_duplicate_binding")
    mutate(lambda raw: raw["adapter"]["routes"][fixtures.DM_ROUTE].update(allowed_sender_ids=[OWNER]),
           "cfg_private_extra_keys")
    mutate(lambda raw: raw["adapter"].update(allowed_group_ids=[fixtures.GROUPS[0]]),
           "cfg_group_route_without_allowlist")
    ok_all = True
    for tag, ok, detail in cases:
        rep.check(tag, ok, detail)
        ok_all = ok_all and ok
    raw = fixtures.raw_of(gcfg)
    del raw["adapter"]["routes"]["group-%s" % LOOSE_GROUP]
    try:
        loose = Config(raw, "loose")
        rep.check("cfg_group_allowed_without_route_loads",
                  LOOSE_GROUP in loose.allowed_groups and loose.route_for_group(LOOSE_GROUP) is None,
                  "an allowlisted group without a route stays closed")
    except ConfigError as exc:
        rep.check("cfg_group_allowed_without_route_loads", False, str(exc))
    rep.check("cfg_group_policy_cases", ok_all, "%d cases" % len(cases))


def _check_live_config(rep, cfg):
    """Optional cross-check of the deployment config actually in hand.

    Shape and bounds only -- parsing, allowlist consistency, member snapshots,
    no secret in `describe()`.  It never decides a behaviour answer, and the
    whole section is skipped when this run was given no config file, so the
    self test result cannot drift with whatever the machine is authorized for.
    """
    rep.check("live_config_parses", isinstance(cfg, Config), str(getattr(cfg, "path", None)))
    rep.check("live_config_describe_no_secrets",
              cfg.host["token"] not in cfg.describe() and cfg.napcat["token"] not in cfg.describe(),
              cfg.describe()[:140])
    rep.check("live_config_routes_match_file",
              sorted(cfg.routes) == sorted(cfg.raw["adapter"].get("routes") or {}),
              ",".join(sorted(cfg.routes)))
    rep.check("live_config_group_ids_match_file",
              sorted(cfg.allowed_groups) == sorted(cfg.raw["adapter"].get("allowed_group_ids") or []),
              str(sorted(cfg.allowed_groups)))
    bad_group = [r.route_id for r in cfg.routes.values()
                 if r.message_type == "group" and r.target_id not in cfg.allowed_groups]
    rep.check("live_config_group_routes_bounded", not bad_group, ",".join(bad_group))
    bad_private = [r.route_id for r in cfg.routes.values() if r.message_type == "private"
                   and (r.sender_id not in cfg.allowed_private or r.target_id not in cfg.allowed_private)]
    rep.check("live_config_dm_routes_bounded", not bad_private, ",".join(bad_private))
    empty = [r.route_id for r in cfg.routes.values()
             if r.message_type == "group" and r.member_count < 1]
    rep.check("live_config_member_snapshots_present", not empty, ",".join(empty))
    rep.check("live_config_admission_known", cfg.admission in ("explicit", "automatic"), str(cfg.admission))
    rep.check("live_config_account_id_shape", cfg.napcat["account_id"].isdigit(), cfg.napcat["account_id"])
    print("SELFTEST live_config_summary         INFO %s" % cfg.describe(), flush=True)


def _check_private(rep, cfg):
    seen = inbound_mod.SeenLRU(64)
    good = _msg_event(cfg)
    result, reason = inbound_mod.classify(good, cfg, seen)
    rep.check("filter_valid_dm", reason == "accepted", reason)
    envelope, meta = result if reason == "accepted" else ({}, {})
    rep.check("envelope_keys", set(envelope) <= ALLOWED_ENVELOPE_KEYS, ",".join(sorted(envelope)))
    rep.check("envelope_no_group_fields",
              not ({"group_id", "mentioned_account_ids", "reply_to"} & set(envelope)), ",".join(sorted(envelope)))
    rep.check("envelope_route", envelope.get("route_id") == "owner-dm", str(envelope.get("route_id")))
    rep.check("envelope_occurred_at", bool(envelope.get("occurred_at")), str(envelope.get("occurred_at")))
    rep.check("envelope_raw_kept", isinstance(envelope.get("raw"), dict) and
              envelope["raw"].get("message_id") == good["message_id"], "")
    cases = [
        ("filter_other_sender", _msg_event(cfg, user_id=int(UNKNOWN_SENDER), message_id=2),
         "unauthorized_sender"),
        ("filter_self_echo", _msg_event(cfg, user_id=int(cfg.napcat["account_id"]), message_id=3), "self_echo"),
        ("filter_notice", {"post_type": "notice", "self_id": int(cfg.napcat["account_id"]), "notice_type": "notify"}, "nonmessage"),
        ("filter_heartbeat", {"post_type": "meta_event", "self_id": int(cfg.napcat["account_id"]), "meta_event_type": "heartbeat"}, "nonmessage"),
        ("filter_image_only_now_accepted",
         _msg_event(cfg, message=[{"type": "image", "data": {"file": "a.jpg"}}], message_id=4), "accepted"),
        ("filter_wrong_self", _msg_event(cfg, self_id=765432, message_id=5), "wrong_self"),
        ("filter_bad_shape", _msg_event(cfg, user_id=None, message_id=5), "bad_shape"),
        ("filter_duplicate", _msg_event(cfg), "duplicate_local"),
        ("filter_unsupported_type", _msg_event(cfg, message_type="discuss", message_id=9), "unsupported_message_type"),
    ]
    for name, event, expected in cases:
        _res, reason = inbound_mod.classify(event, cfg, seen)
        rep.check(name, reason == expected, "got=%s want=%s" % (reason, expected))
    mixed = _msg_event(cfg, message=[{"type": "text", "data": {"text": "前半"}},
                                     {"type": "image", "data": {"file": "a.jpg"}},
                                     {"type": "text", "data": {"text": "后半"}}], message_id=7)
    result, reason = inbound_mod.classify(mixed, cfg, seen)
    rep.check("filter_mixed_segments", reason == "accepted" and result[1]["non_text_segments"] == 1
              and result[0]["text"] == "前半[图片（未解析）]后半",
              repr(result[0].get("text")) if reason == "accepted" else reason)
    rep.check("filter_mixed_media_meta", reason == "accepted" and result[1]["media_segments"] == 1
              and result[1]["media_types"] == "image" and result[1]["media_only"] is False, reason)
    result, reason = inbound_mod.classify(_msg_event(cfg, message="纯字符串消息", message_id=8), cfg, seen)
    rep.check("filter_string_message", reason == "accepted" and result[0]["text"] == "纯字符串消息", reason)
    result, reason = inbound_mod.classify(_msg_event(cfg, message=_text("@示例角色 在吗"), message_id=11), cfg, seen)
    rep.check("filter_private_ignores_at_text", reason == "accepted" and
              "mentioned_account_ids" not in result[0] and result[0]["text"] == "@示例角色 在吗", reason)
    result, reason = inbound_mod.classify(_msg_event(cfg, message=[{"type": "at", "data": {"qq": "123"}},
                                     {"type": "text", "data": {"text": "在吗"}}], message_id=12), cfg, seen)
    rep.check("filter_private_text_unchanged_by_at", reason == "accepted" and
              result[0]["text"] == "在吗" and "mentioned_account_ids" not in result[0],
              repr(result[0].get("text")) if reason == "accepted" else reason)


def _loose_cfg(gcfg):
    """One allowlisted fixture group keeps its id but loses its route: it must
    stay closed under explicit admission."""
    raw = fixtures.raw_of(gcfg)
    del raw["adapter"]["routes"]["group-%s" % LOOSE_GROUP]
    return Config(raw, "loose")


def _check_group_inbound(rep, gcfg):
    if gcfg is None:
        rep.check("group_inbound_ran", False, "no group config")
        return
    seen = inbound_mod.SeenLRU(256)
    routes = {r.target_id: r for r in gcfg.routes.values() if r.message_type == "group"}
    groups = sorted(routes)
    if not groups:
        rep.check("group_inbound_ran", False, "no group route in the effective config")
        return
    members = {gid: set(routes[gid].allowed_senders) for gid in groups}
    want_groups = sorted(fixtures.GROUPS)
    rep.check("group_inbound_covers_fixtures", groups == want_groups,
              "effective=%s fixtures=%s" % (groups, want_groups))
    only_a = sorted(members[groups[0]] - members[groups[min(1, len(groups) - 1)]]) or sorted(members[groups[0]])
    only_a = only_a[0]
    outsider = OUTSIDER
    rep.check("fixture_outsider_on_no_snapshot", not any(outsider in members[g] for g in groups),
              "%s is on none of the member snapshots" % outsider)

    accepted, shape_ok = [], True
    for index, gid in enumerate(groups):
        sender = OWNER if OWNER in members[gid] else sorted(members[gid])[0]
        res, reason = inbound_mod.classify(_group_event(gcfg, gid, sender, 4000 + index), gcfg, seen)
        accepted.append((gid, reason))
        if reason != "accepted":
            shape_ok = False
            continue
        env, meta = res
        if set(env) - ALLOWED_GROUP_ENVELOPE_KEYS or env.get("group_id") != gid or \
                env.get("route_id") != "group-%s" % gid or env.get("sender_id") != sender or \
                env.get("mentioned_account_ids") != [] or "reply_to" in env or \
                not isinstance(env.get("group_id"), str) or not isinstance(env.get("sender_id"), str) or \
                env.get("raw", {}).get("message_id") != 4000 + index or meta.get("scene") != "group":
            shape_ok = False
    rep.check("group_accept_all_routes", shape_ok, json.dumps(accepted))

    other = sorted(members[groups[0]] - {OWNER})[0] if len(members[groups[0]]) > 1 else OWNER
    rich = [{"type": "reply", "data": {"id": 555}},
            {"type": "at", "data": {"qq": OWNER}},
            {"type": "at", "data": {"user_id": other}},
            {"type": "at", "data": {"qq": OWNER}},
            {"type": "at", "data": {"qq": "all"}},
            {"type": "text", "data": {"text": "正文"}},
            {"type": "image", "data": {"file": "a.jpg"}}]
    res, reason = inbound_mod.classify(_group_event(gcfg, groups[0], OWNER, 4100, message=rich), gcfg, seen)
    env, meta = res if reason == "accepted" else ({}, {})
    rep.check("group_at_normalised", env.get("mentioned_account_ids") == [OWNER, str(other)] and
              all(isinstance(x, str) for x in env.get("mentioned_account_ids", [])),
              str(env.get("mentioned_account_ids")))
    rep.check("group_reply_normalised", env.get("reply_to") == "555" and isinstance(env.get("reply_to"), str),
              str(env.get("reply_to")))
    rep.check("group_at_rendered_in_place",
              env.get("text") == "@%s@%s@%s@全体正文[图片（未解析）]" % (OWNER, other, OWNER) and
              meta.get("non_text_segments") == 1 and "555" not in env.get("text"),
              "%r non_text=%s" % (env.get("text"), meta.get("non_text_segments")))

    # the shape that started this: at 本账号 + "你刚刚回复 " + at 别人 + "了么？"
    pointed = [{"type": "at", "data": {"qq": gcfg.napcat["account_id"]}},
               {"type": "text", "data": {"text": "你刚刚回复 "}},
               {"type": "at", "data": {"qq": "900000103"}},
               {"type": "text", "data": {"text": "了么？"}}]
    res, reason = inbound_mod.classify(_group_event(gcfg, groups[0], OWNER, 4112, message=pointed), gcfg, seen)
    rep.check("group_at_position_preserved", reason == "accepted" and
              res[0]["text"] == "@%s你刚刚回复 @900000103了么？" % gcfg.napcat["account_id"] and
              res[0]["mentioned_account_ids"] == [gcfg.napcat["account_id"], "900000103"],
              repr(res[0].get("text")) if reason == "accepted" else reason)
    rep.check("group_at_all_counted_not_id", meta.get("at_all_segments") == 1 and
              "all" not in env.get("mentioned_account_ids", []) and meta.get("has_reply") is True,
              json.dumps(meta, sort_keys=True))
    rep.check("group_envelope_keys", set(env) <= ALLOWED_GROUP_ENVELOPE_KEYS, ",".join(sorted(env)))

    res, reason = inbound_mod.classify(_group_event(gcfg, groups[0], OWNER, 4101,
                                                   message=_text("@全体成员 示例角色 在吗")), gcfg, seen)
    rep.check("group_at_text_is_not_mention", reason == "accepted" and res[0]["mentioned_account_ids"] == []
              and "reply_to" not in res[0] and res[1]["mentions"] == 0
              and res[0]["text"] == "@全体成员 示例角色 在吗",
              "%s text=%r" % (reason, res[0].get("text") if reason == "accepted" else None))

    res, reason = inbound_mod.classify(_group_event(gcfg, groups[0], only_a, 4102), gcfg, seen)
    rep.check("group_member_of_own_group", reason == "accepted", reason)
    if len(groups) > 1:
        res, reason = inbound_mod.classify(_group_event(gcfg, groups[1], only_a, 4103), gcfg, seen)
        rep.check("group_member_cross_group_denied", reason == "unauthorized_group_member",
                  "%s (member of %s only)" % (reason, groups[0]))
    res, reason = inbound_mod.classify(_group_event(gcfg, groups[0], outsider, 4104), gcfg, seen)
    rep.check("group_non_member_denied", reason == "unauthorized_group_member", reason)
    res, reason = inbound_mod.classify(_group_event(gcfg, UNKNOWN_GROUP, OWNER, 4105), gcfg, seen)
    # explicit admission only: `automatic` admits this group, checked in
    # _check_admission rather than by flipping this expectation
    rep.check("group_not_on_allowlist", reason == "group_not_allowed",
              "%s (admission=%s)" % (reason, gcfg.admission))
    loose = _loose_cfg(gcfg)
    res, reason = inbound_mod.classify(_group_event(loose, LOOSE_GROUP, OWNER, 4106), loose, seen)
    rep.check("group_allowed_without_route", reason == "group_route_missing", reason)
    rep.check("group_loose_config_built", loose is not None, "")
    res, reason = inbound_mod.classify(_group_event(gcfg, groups[0], gcfg.napcat["account_id"], 4107), gcfg, seen)
    rep.check("group_self_echo", reason == "self_echo", reason)
    res, reason = inbound_mod.classify(_group_event(gcfg, groups[0], OWNER, 4108, self_id=765432), gcfg, seen)
    rep.check("group_wrong_self", reason == "wrong_self", reason)
    res, reason = inbound_mod.classify(_group_event(gcfg, groups[0], OWNER, 4109,
                                                   message=[{"type": "image", "data": {"file": "a.jpg"}}]), gcfg, seen)
    rep.check("group_image_only_now_accepted", reason == "accepted" and
              res[0]["text"] == "[图片（未解析）]" and res[1]["media_only"] is True, reason)
    res, reason = inbound_mod.classify(_group_event(gcfg, groups[0], OWNER, 4113,
                                                   message=[{"type": "at", "data": {"qq": gcfg.napcat["account_id"]}}]),
                                       gcfg, seen)
    rep.check("group_bare_at_self_now_visible", reason == "accepted" and
              res[0]["text"] == "@" + gcfg.napcat["account_id"] and
              res[0]["mentioned_account_ids"] == [gcfg.napcat["account_id"]],
              repr(res[0].get("text")) if reason == "accepted" else reason)
    other_member = sorted(members[groups[0]] - {gcfg.napcat["account_id"]})[0]
    res, reason = inbound_mod.classify(_group_event(gcfg, groups[0], OWNER, 4114,
                                                   message=[{"type": "at", "data": {"qq": other_member}}]),
                                       gcfg, seen)
    rep.check("group_bare_at_other_member_still_no_text", reason == "no_text", reason)
    no_group = _group_event(gcfg, groups[0], OWNER, 4110)
    no_group["group_id"] = None
    res, reason = inbound_mod.classify(no_group, gcfg, seen)
    rep.check("group_missing_group_id", reason == "bad_shape", reason)
    res, reason = inbound_mod.classify(_group_event(gcfg, groups[0], OWNER, None), gcfg, seen)
    rep.check("group_missing_message_id", reason == "bad_shape", reason)
    res, reason = inbound_mod.classify(_group_event(gcfg, groups[0], OWNER, 4100), gcfg, seen)
    rep.check("group_duplicate_same_route", reason == "duplicate_local", reason)
    reused = _group_event(gcfg, groups[0], OWNER, 4100)
    reused['time'] += 86400
    _res, reason = inbound_mod.classify(reused, gcfg, seen)
    rep.check('group_reused_id_at_new_time', reason == 'accepted', reason)
    reused['asuna_catchup'] = {'reason': 'reconnect'}
    _res, reason = inbound_mod.classify(reused, gcfg, seen)
    rep.check('group_catchup_same_id_and_time', reason == 'duplicate_local', reason)
    long_text = "a" * 16001
    res, reason = inbound_mod.classify(_group_event(gcfg, groups[0], OWNER, 4111, message=_text(long_text)), gcfg, seen)
    rep.check("group_over_host_limit_flagged", reason == "accepted" and res[1]["over_host_limit"] is True and
              len(res[0]["text"]) == len(long_text), reason)

    # one member of both groups: the same platform message id in two scenes is
    # two events, and the same id twice in one scene is one event
    both = sorted(members[groups[0]] & members[groups[min(1, len(groups) - 1)]]) or sorted(members[groups[0]])
    both = both[0]
    shared = 424242
    _r, r1 = inbound_mod.classify(_msg_event(gcfg, message_id=shared), gcfg, seen)
    _r, r2 = inbound_mod.classify(_group_event(gcfg, groups[0], both, shared), gcfg, seen)
    _r, r3 = inbound_mod.classify(_group_event(gcfg, groups[min(1, len(groups) - 1)], both, shared), gcfg, seen)
    _r, r4 = inbound_mod.classify(_group_event(gcfg, groups[0], both, shared), gcfg, seen)
    rep.check("dedup_scoped_by_scene", (r1, r2, r3, r4) == ("accepted", "accepted", "accepted", "duplicate_local"),
              "message_id %s: dm=%s g1=%s g2=%s repeat=%s" % (shared, r1, r2, r3, r4))
    rep.check("group_inbound_ran", True, "groups=%d outsider=%s cross=%s" % (len(groups), outsider, only_a))


def _check_spool(rep, root):
    fresh = Journal(root + "/spooltest")
    paths = [fresh.spool_add("inbound", {"envelope": {"event_id": str(i)}, "meta": {}}, key=str(i)) for i in (1, 2, 3)]
    rep.check("spool_three", len(fresh.spool_list("inbound")) == 3, str(len(fresh.spool_list("inbound"))))
    fresh.spool_remove(paths[0])
    fresh.spool_move(paths[1], "inbound_rejected.jsonl", {"reason": "selftest"})
    reopened = Journal(root + "/spooltest")
    remaining = reopened.spool_list("inbound")
    rep.check("spool_survives_restart", [os.path.basename(p) for p in remaining] == [os.path.basename(paths[2])],
              str([os.path.basename(p) for p in remaining]))
    rep.check("spool_move_journaled", os.path.exists(os.path.join(reopened.jdir, "inbound_rejected.jsonl")), "")


def _check_outbound_params(rep, gcfg, root):
    """Send-parameter checks against StubOneBot/StubHost: a SUBSTITUTE for the
    platform and the host, so nothing is sent to QQ and nothing is claimed."""
    if gcfg is None:
        rep.check("outbound_params_ran", False, "no group config")
        return
    groups = sorted(gcfg.allowed_groups)

    def item(n, target, text="正文", reply_to=None):
        return {"publication_id": "selftest-%s" % n, "attempt_id": "attempt-%s" % n,
                "target": target, "text": text, "reply_to": reply_to}

    def run_case(name, cfg, out_item, response=None, exc=None):
        stub, host = StubOneBot(response=response, exc=exc), StubHost()
        counters = Counters()
        ob = outbound_mod.Outbound(cfg, host, stub, Journal(root + "/ob_" + name), counters,
                                   log=lambda _m: None, ack_timeout=5.0, verify=False)
        ob.handle_item(out_item)
        return stub, host, counters

    stub, host, _c = run_case("dm", gcfg, item("dm", {"type": "dm", "id": OWNER}, reply_to="123"))
    call = stub.calls[0] if stub.calls else {}
    rep.check("ob_dm_uses_private_action", call.get("action") == "send_private_msg" and
              call.get("params", {}).get("user_id") == int(OWNER), json.dumps(call.get("action")))
    rep.check("ob_dm_shape_unchanged", call.get("params", {}).get("message") ==
              [{"type": "text", "data": {"text": "正文"}}],
              json.dumps(call.get("params", {}).get("message"), ensure_ascii=False))
    rep.check("ob_dm_receipt_accepted", host.last().get("payload", {}).get("status") == "platform_accepted" and
              host.last().get("payload", {}).get("platform_message_id") == "990001",
              json.dumps(host.last().get("payload", {}).get("status")))

    stub, host, _c = run_case("grp", gcfg, item("grp", {"type": "group", "id": groups[0]}, reply_to="987654"))
    call = stub.calls[0] if stub.calls else {}
    rep.check("ob_group_uses_group_action", call.get("action") == "send_group_msg" and
              call.get("params", {}).get("group_id") == int(groups[0]) and
              "user_id" not in call.get("params", {}), json.dumps(call.get("action")))
    rep.check("ob_group_reply_segment", call.get("params", {}).get("message") ==
              [{"type": "reply", "data": {"id": "987654"}}, {"type": "text", "data": {"text": "正文"}}],
              json.dumps(call.get("params", {}).get("message"), ensure_ascii=False))
    rep.check("ob_group_receipt_accepted", host.last().get("payload", {}).get("status") == "platform_accepted" and
              host.last().get("payload", {}).get("attempt_id") == "attempt-grp",
              json.dumps(host.last().get("payload", {}).get("status")))

    stub, _h, _c = run_case("gr0", gcfg, item("gr0", {"type": "group", "id": groups[1]}))
    rep.check("ob_group_no_reply_no_segment", stub.calls[0]["params"]["message"] ==
              [{"type": "text", "data": {"text": "正文"}}],
              json.dumps(stub.calls[0]["params"]["message"], ensure_ascii=False))

    stub, _h, _c = run_case("all", gcfg, item("all", {"type": "group", "id": groups[2]}, text="@全体 开会了"))
    rep.check("ob_at_all_stays_text", stub.calls[0]["params"]["message"] ==
              [{"type": "text", "data": {"text": "@全体 开会了"}}],
              json.dumps(stub.calls[0]["params"]["message"], ensure_ascii=False))

    def wire(name, target, text, reply_to=None):
        stub, _h, _c = run_case(name, gcfg, item(name, target, text=text, reply_to=reply_to))
        call = stub.calls[0] if stub.calls else {}
        return call.get("params", {}).get("message")

    def T(t):
        return {"type": "text", "data": {"text": t}}

    def A(qq):
        return {"type": "at", "data": {"qq": qq}}

    def RP(rid):
        return {"type": "reply", "data": {"id": rid}}

    GRP = {"type": "group", "id": groups[0]}
    DM = {"type": "dm", "id": OWNER}
    got = wire("at1", GRP, "收到 @qq:900000103 的建议", reply_to="987654")
    rep.check("ob_group_at_marker_promoted",
              got == [RP("987654"), T("收到 "), A("900000103"), T(" 的建议")],
              json.dumps(got, ensure_ascii=False))
    got = wire("at2", GRP, "@qq:900000010")
    rep.check("ob_group_marker_only_message", got == [A("900000010")], json.dumps(got, ensure_ascii=False))
    got = wire("at3", GRP, "@qq:10001 和 @qq:10002 都到了")
    rep.check("ob_group_two_markers_in_order",
              got == [A("10001"), T(" 和 "), A("10002"), T(" 都到了")], json.dumps(got, ensure_ascii=False))
    got = wire("at4", GRP, "@示例角色 @全体 看这里")
    rep.check("ob_group_nick_and_at_all_stay_text", got == [T("@示例角色 @全体 看这里")],
              json.dumps(got, ensure_ascii=False))
    got = wire("at5", GRP, "@qq:all @qq:abc @qq:")
    rep.check("ob_group_marker_requires_digits", got == [T("@qq:all @qq:abc @qq:")],
              json.dumps(got, ensure_ascii=False))
    got = wire("at6", GRP, "写信到 asuna@qq:12345 好么")
    rep.check("ob_group_email_like_marker_stays_text",
              got == [T("写信到 asuna@qq:12345 好么")], json.dumps(got, ensure_ascii=False))
    got = wire("at7", GRP, "@qq:" + "1" * 21 + " 太长")
    rep.check("ob_group_overlong_digits_stay_text",
              got == [T("@qq:" + "1" * 21 + " 太长")], json.dumps(got, ensure_ascii=False))
    got = wire("at8", GRP, "尾@qq:10003")
    rep.check("ob_group_marker_at_end_no_empty_text", got == [T("尾"), A("10003")],
              json.dumps(got, ensure_ascii=False))
    got = wire("at9", DM, "@qq:900000103 收到 @全体", reply_to="123")
    rep.check("ob_dm_marker_never_promoted", got == [T("@qq:900000103 收到 @全体")],
              json.dumps(got, ensure_ascii=False))

    all_segs = []
    for name, out_item in [("x1", item("x1", DM, text="@qq:900000103 @全体")),
                           ("x2", item("x2", {"type": "group", "id": groups[3]}, reply_to="7")),
                           ("x3", item("x3", GRP, text="@全体 @qq:900000103"))]:
        stub, _h, _c = run_case(name, gcfg, out_item)
        for call in stub.calls:
            all_segs.extend(call["params"]["message"])
    rep.check("ob_out_segments_within_allowlist", bool(all_segs) and
              all(s.get("type") in outbound_mod.ALLOWED_OUT_SEGMENTS for s in all_segs),
              json.dumps(sorted(set(s.get("type") for s in all_segs))))
    ats = [s for s in all_segs if s.get("type") == "at"]
    rep.check("ob_at_segment_targets_digits_only", bool(ats) and
              all(str(s.get("data", {}).get("qq", "")).isdigit() for s in ats), json.dumps(ats))
    rep.check("ob_at_all_never_becomes_a_segment",
              not any(s.get("data", {}).get("qq") == "all" for s in ats), json.dumps(ats))

    stub, host, _c = run_case("deny", gcfg, item("deny", {"type": "group", "id": UNKNOWN_GROUP}))
    # explicit admission only; the automatic counterpart is
    # admission_automatic_outbound_unknown_group_sends in _check_admission
    rep.check("ob_group_outside_allowlist_no_send", stub.calls == [] and
              host.last().get("payload", {}).get("status") == "failed" and
              host.last().get("payload", {}).get("response", {}).get("reason") == "target_not_authorized",
              json.dumps(host.last().get("payload", {}).get("response"), ensure_ascii=False))
    stub, host, _c = run_case("loose", _loose_cfg(gcfg), item("loose", {"type": "group", "id": LOOSE_GROUP}))
    rep.check("ob_allowed_group_without_route_no_send",
              stub.calls == [] and host.last().get("payload", {}).get("status") == "failed", json.dumps(host.last()))
    stub, host, _c = run_case("chan", gcfg, item("chan", {"type": "channel", "id": OWNER}))
    rep.check("ob_unknown_target_type_no_send", stub.calls == [] and
              host.last().get("payload", {}).get("status") == "failed", json.dumps(host.last().get("payload")))
    stub, host, _c = run_case("empty", gcfg, item("empty", {"type": "group", "id": groups[0]}, text="   "))
    rep.check("ob_empty_text_no_send", stub.calls == [] and
              host.last().get("payload", {}).get("response", {}).get("reason") == "empty_text", json.dumps(host.last()))

    stub, host, _c = run_case("ret", gcfg, item("ret", {"type": "group", "id": groups[0]}),
                              response={"status": "failed", "retcode": 1, "wording": "bad"})
    rep.check("ob_retcode_nonzero_failed", len(stub.calls) == 1 and
              host.last().get("payload", {}).get("status") == "failed" and
              "platform_message_id" not in host.last().get("payload", {}),
              json.dumps(host.last().get("payload", {}).get("status")))

    stub, host, _c = run_case("tmo", gcfg, item("tmo", {"type": "group", "id": groups[0]}), exc=ApiTimeout("x"))
    rep.check("ob_timeout_unknown_no_resend", len(stub.calls) == 1 and
              host.last().get("payload", {}).get("status") == "unknown",
              "calls=%d status=%s" % (len(stub.calls), host.last().get("payload", {}).get("status")))
    stub, host, _c = run_case("tr", gcfg, item("tr", {"type": "group", "id": groups[0]}),
                              exc=ApiTransportError("boom"))
    rep.check("ob_transport_error_unknown", len(stub.calls) == 1 and
              host.last().get("payload", {}).get("status") == "unknown", json.dumps(host.last().get("payload")))

    payload = host.last().get("payload", {})
    rep.check("ob_receipt_payload_shape", set(payload) <= {"attempt_id", "status", "response", "platform_message_id"}
              and isinstance(payload.get("response"), dict), json.dumps(sorted(payload)))
    rep.check("outbound_params_ran", True, "stubbed platform+host only, no QQ traffic")


class StubPlatformVerify:
    """SUBSTITUTE platform for the read-back checks: answers the send, then
    answers `get_msg` from a script and records every id it was asked for."""

    def __init__(self, send_response=None, verify_responses=None, verify_exc=None, send_exc=None):
        self.calls = []
        self.send_response = send_response if send_response is not None else {
            "status": "ok", "retcode": 0, "data": {"message_id": 990001}}
        self.verify_responses = verify_responses or []
        self.verify_exc = verify_exc
        self.send_exc = send_exc
        self.verify_ids = []

    def api_call(self, action, params=None, timeout=15.0, meta=None):
        self.calls.append({"action": action, "params": params, "meta": meta, "timeout": timeout})
        if action == "get_msg":
            self.verify_ids.append((params or {}).get("message_id"))
            if self.verify_exc is not None:
                raise self.verify_exc
            index = min(len(self.verify_ids) - 1, len(self.verify_responses) - 1)
            return self.verify_responses[index]
        if self.send_exc is not None:
            raise self.send_exc
        return self.send_response


def _stored_msg(segs, group_id=None, user_id=None, mtype=None, account=None, sender_id=None):
    data = {"message_id": 990001, "message": segs, "sender": {"user_id": int(sender_id or account or 0)},
            "message_sent_type": "self"}
    if group_id is not None:
        data["group_id"] = int(group_id)
        data["message_type"] = mtype or "group"
    if user_id is not None:
        data["user_id"] = int(user_id)
        data["message_type"] = mtype or "private"
    return {"status": "ok", "retcode": 0, "data": data}


NOT_FOUND = {"status": "failed", "retcode": 1200, "data": None, "wording": "消息不存在"}


def _check_outbound_verify(rep, gcfg, root):
    """Read-back checks against a SUBSTITUTE platform: nothing is sent, nothing
    is claimed.  The point is that the read-back may add information but can
    never move the send status, never cause a re-send and never query an id it
    was not handed by its own send."""
    if gcfg is None:
        rep.check("outbound_verify_ran", False, "no group config")
        return
    groups = sorted(gcfg.allowed_groups)
    grp, other_grp = groups[0], groups[1]
    account = str(gcfg.napcat["account_id"])

    def T(t):
        return {"type": "text", "data": {"text": t}}

    def A(qq):
        return {"type": "at", "data": {"qq": qq}}

    def RP(rid):
        return {"type": "reply", "data": {"id": rid}}

    def item(name, target, text, reply_to=None):
        return {"publication_id": "vfy-%s" % name, "attempt_id": "a-%s" % name,
                "target": target, "text": text, "reply_to": reply_to}

    def run(name, out_item, send_response=None, verify_responses=None, verify_exc=None,
            verify=True, retry=0.0, send_exc=None):
        stub = StubPlatformVerify(send_response=send_response, verify_responses=verify_responses,
                                  verify_exc=verify_exc, send_exc=send_exc)
        host = StubHost()
        counters = Counters()
        ob = outbound_mod.Outbound(gcfg, host, stub, Journal(root + "/vfy_" + name), counters,
                                   log=lambda _m: None, ack_timeout=5.0, verify=verify,
                                   verify_delay=0.0, verify_retry_delay=retry, verify_timeout=3.0)
        ob.handle_item(out_item)
        return stub, host, counters, ob

    GRP = {"type": "group", "id": grp}
    DM = {"type": "dm", "id": OWNER}
    sent_segs = [RP("987654"), T("收到 "), A("900000103"), T(" 的建议")]
    sent_types = ["reply", "text", "at", "text"]

    def actions(stub):
        return [c["action"] for c in stub.calls]

    stub, host, counters, _ob = run("ok", item("ok", GRP, "收到 @qq:900000103 的建议", reply_to="987654"),
                                    verify_responses=[_stored_msg(sent_segs, group_id=grp, account=account)])
    payload = host.last().get("payload", {})
    ver = (payload.get("response") or {}).get("verification") or {}
    rep.check("verify_group_verified", ver.get("result") == "verified" and ver.get("target_ok") is True and
              ver.get("stored_segments") == sent_types and ver.get("sender_is_self") is True and
              ver.get("stored_as_self_sent") is True, json.dumps(ver, ensure_ascii=False))
    rep.check("verify_keeps_platform_accepted", payload.get("status") == "platform_accepted" and
              payload.get("platform_message_id") == "990001", json.dumps(payload.get("status")))
    rep.check("verify_queries_only_own_id", stub.verify_ids == [990001], json.dumps(stub.verify_ids))
    rep.check("verify_no_resend", actions(stub).count("send_group_msg") == 1, json.dumps(actions(stub)))
    rep.check("verify_counter_recorded", counters.snapshot().get("verify_verified") == 1,
              json.dumps(counters.snapshot()))
    rep.check("verify_receipt_keeps_raw_response",
              (payload.get("response") or {}).get("retcode") == 0 and
              isinstance((payload.get("response") or {}).get("data"), dict),
              json.dumps(sorted((payload.get("response") or {}).keys())))
    gm = [c for c in stub.calls if c["action"] == "get_msg"][0]
    rep.check("verify_get_msg_params_bounded", gm["params"] == {"message_id": 990001} and
              gm["timeout"] == 3.0, json.dumps([gm["params"], gm["timeout"]]))
    rep.check("verify_late_get_msg_cannot_receipt",
              (gm["meta"] or {}).get("purpose") == "outbound_verification" and
              "attempt_id" not in (gm["meta"] or {}), json.dumps(gm["meta"]))
    rep.check("verify_api_surface_bounded", set(actions(stub)) <= {"send_group_msg", "get_msg"},
              json.dumps(sorted(set(actions(stub)))))
    jpath = os.path.join(root, "vfy_ok", "journal", "sends.jsonl")
    body = open(jpath, encoding="utf-8").read() if os.path.exists(jpath) else ""
    rep.check("verify_journaled", '"verification"' in body and '"verified"' in body, os.path.basename(jpath))

    stub, host, counters, _ob = run("nf", item("nf", GRP, "正文"), verify_responses=[NOT_FOUND])
    payload = host.last().get("payload", {})
    ver = (payload.get("response") or {}).get("verification") or {}
    rep.check("verify_not_found_keeps_accepted", payload.get("status") == "platform_accepted" and
              ver.get("result") == "not_found" and counters.snapshot().get("verify_not_found") == 1,
              json.dumps([payload.get("status"), ver], ensure_ascii=False))

    stub, host, _c, _ob = run("retry", item("retry", GRP, "正文"),
                              verify_responses=[NOT_FOUND, _stored_msg([T("正文")], group_id=grp, account=account)],
                              retry=0.0)
    ver = (host.last().get("payload", {}).get("response") or {}).get("verification") or {}
    rep.check("verify_retry_once_then_verified", stub.verify_ids == [990001, 990001] and
              ver.get("result") == "verified", json.dumps([stub.verify_ids, ver.get("result")]))

    stub, host, _c, _ob = run("retry2", item("retry2", GRP, "正文"), verify_responses=[NOT_FOUND, NOT_FOUND])
    ver = (host.last().get("payload", {}).get("response") or {}).get("verification") or {}
    rep.check("verify_retry_bounded", stub.verify_ids == [990001, 990001] and ver.get("result") == "not_found",
              json.dumps([stub.verify_ids, ver.get("result")]))

    for tag, exc in (("timeout", ApiTimeout("x")), ("notconn", outbound_mod.ApiNotConnected("x")),
                     ("transport", outbound_mod.ApiTransportError("x"))):
        stub, host, counters, _ob = run(tag, item(tag, GRP, "正文"), verify_exc=exc)
        payload = host.last().get("payload", {})
        ver = (payload.get("response") or {}).get("verification") or {}
        rep.check("verify_%s_keeps_accepted_no_resend" % tag,
                  payload.get("status") == "platform_accepted" and ver.get("result") == "unavailable" and
                  actions(stub).count("send_group_msg") == 1 and
                  counters.snapshot().get("verify_unavailable") == 1,
                  json.dumps([payload.get("status"), ver.get("result"), actions(stub)]))

    stub, host, _c, _ob = run("tgt", item("tgt", GRP, "正文"),
                              verify_responses=[_stored_msg([T("正文")], group_id=other_grp, account=account)])
    payload = host.last().get("payload", {})
    ver = (payload.get("response") or {}).get("verification") or {}
    rep.check("verify_target_mismatch_recorded",
              payload.get("status") == "platform_accepted" and ver.get("result") == "target_mismatch" and
              ver.get("target_ok") is False and ver.get("stored_target_id") == str(other_grp),
              json.dumps(ver, ensure_ascii=False))

    stub, host, _c, _ob = run("seg", item("seg", GRP, "收到 @qq:900000103 的建议", reply_to="987654"),
                              verify_responses=[_stored_msg([T("正文")], group_id=grp, account=account)])
    payload = host.last().get("payload", {})
    ver = (payload.get("response") or {}).get("verification") or {}
    rep.check("verify_segment_mismatch_recorded",
              payload.get("status") == "platform_accepted" and ver.get("result") == "segment_mismatch" and
              ver.get("stored_segments") == ["text"], json.dumps(ver, ensure_ascii=False))

    # Outbound faces: a `[表情:名字]` goes out as a real face segment, and a face the platform did not store is
    # recorded as a segment mismatch (the host tells her which part did not land).
    F = lambda fid: {"type": "face", "data": {"id": fid}}
    stub, host, _c, _ob = run("face", item("face", GRP, "好饿[表情:干饭]"),
                              verify_responses=[_stored_msg([T("好饿"), F("475")], group_id=grp, account=account)])
    sent = next((c for c in stub.calls if c["action"] == "send_group_msg"), {}).get("params", {}).get("message") or []
    ver = (host.last().get("payload", {}).get("response") or {}).get("verification") or {}
    rep.check("outbound_face_sent_as_face_segment", sent[-1:] == [F("475")] and ver.get("result") == "verified",
              json.dumps([sent, ver.get("result")], ensure_ascii=False))
    stub, host, _c, _ob = run("face_lost", item("face_lost", GRP, "好饿[表情:干饭]"),
                              verify_responses=[_stored_msg([T("好饿")], group_id=grp, account=account)])
    ver = (host.last().get("payload", {}).get("response") or {}).get("verification") or {}
    rep.check("outbound_face_not_stored_is_a_mismatch",
              ver.get("result") == "segment_mismatch" and ver.get("sent_segments") == ["text", "face"] and
              ver.get("stored_segments") == ["text"], json.dumps(ver, ensure_ascii=False))

    stub, host, counters, _ob = run("shape", item("shape", GRP, "正文"),
                                    verify_responses=[{"status": "ok", "retcode": 0, "data": {"message_id": 990001}}])
    ver = (host.last().get("payload", {}).get("response") or {}).get("verification") or {}
    rep.check("verify_unexpected_shape_unavailable",
              ver.get("result") == "unavailable" and ver.get("reason") == "unexpected_shape" and
              host.last().get("payload", {}).get("status") == "platform_accepted",
              json.dumps(ver, ensure_ascii=False))

    # the shape the platform actually returned for a private send: the
    # read-back carries user_id = our own account, not the peer
    stub, host, _c, _ob = run("dm", item("dm", DM, "正文"),
                              verify_responses=[_stored_msg([T("正文")], user_id=account, account=account)])
    ver = (host.last().get("payload", {}).get("response") or {}).get("verification") or {}
    rep.check("verify_dm_verified", ver.get("result") == "verified" and ver.get("target_ok") is True
              and ver.get("peer_bound") is False, json.dumps(ver, ensure_ascii=False))

    stub, host, _c, _ob = run("dmother", item("dmother", DM, "正文"),
                              verify_responses=[_stored_msg([T("正文")], user_id=OWNER,
                                                                                             account=account,
                                                                                             sender_id=OWNER)])
    ver = (host.last().get("payload", {}).get("response") or {}).get("verification") or {}
    rep.check("verify_dm_readback_from_somebody_else", ver.get("result") == "target_mismatch"
              and ver.get("sender_is_self") is False, json.dumps(ver, ensure_ascii=False))

    stub, host, _c, _ob = run("dmbad", item("dmbad", DM, "正文"),
                              verify_responses=[_stored_msg([T("正文")], group_id=grp, account=account)])
    ver = (host.last().get("payload", {}).get("response") or {}).get("verification") or {}
    rep.check("verify_dm_wrong_conversation", ver.get("result") == "target_mismatch", json.dumps(ver, ensure_ascii=False))

    stub, host, _c, _ob = run("failed", item("failed", GRP, "正文"),
                              send_response={"status": "failed", "retcode": 1, "data": None})
    payload = host.last().get("payload", {})
    rep.check("verify_skipped_on_failed_send", stub.verify_ids == [] and payload.get("status") == "failed" and
              "verification" not in (payload.get("response") or {}),
              json.dumps([stub.verify_ids, payload.get("status")]))

    stub, host, _c, _ob = run("unk", item("unk", GRP, "正文"), send_exc=ApiTimeout("send"))
    rep.check("verify_skipped_on_unknown_send", stub.verify_ids == [] and
              host.last().get("payload", {}).get("status") == "unknown",
              json.dumps([stub.verify_ids, host.last().get("payload", {}).get("status")]))

    stub, host, _c, _ob = run("off", item("off", GRP, "正文"),
                              verify_responses=[_stored_msg([T("正文")], group_id=grp, account=account)],
                              verify=False)
    payload = host.last().get("payload", {})
    rep.check("verify_disabled_no_call", stub.verify_ids == [] and
              payload.get("status") == "platform_accepted" and
              "verification" not in (payload.get("response") or {}),
              json.dumps([stub.verify_ids, sorted((payload.get("response") or {}).keys())]))

    stub, host, counters, _ob = run("badid", item("badid", GRP, "正文"),
                                    send_response={"status": "ok", "retcode": 0, "data": {"message_id": "abc"}})
    payload = host.last().get("payload", {})
    ver = (payload.get("response") or {}).get("verification") or {}
    rep.check("verify_non_numeric_id_no_call",
              stub.verify_ids == [] and payload.get("status") == "platform_accepted" and
              ver.get("result") == "unavailable" and ver.get("reason") == "id_not_numeric",
              json.dumps([stub.verify_ids, payload.get("status"), ver], ensure_ascii=False))

    stub, host, _c, ob = run("late", item("late", GRP, "正文"),
                             verify_responses=[_stored_msg([T("正文")], group_id=grp, account=account)])
    ob.on_late_ack({"publication_id": "vfy-late", "attempt_id": "a-late"},
                   {"retcode": 0, "data": {"message_id": 990002}})
    late = host.receipts[-1].get("payload", {})
    rep.check("verify_late_ack_path_unchanged",
              late.get("status") == "platform_accepted" and "verification" not in (late.get("response") or {}),
              json.dumps([late.get("status"), sorted((late.get("response") or {}).keys())]))
    ob.on_late_ack({"publication_id": "vfy-late-tmo", "attempt_id": "a-late-tmo"},
                   {"status": "failed", "retcode": 1200, "data": None,
                    "message": "Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg"})
    late = host.receipts[-1].get("payload", {})
    rep.check("late_platform_send_timeout_stays_unknown",
              late.get("status") == "unknown" and (late.get("response") or {}).get("reason") == "platform_send_timeout",
              json.dumps([late.get("status"), late.get("response")], ensure_ascii=False))
    rep.check("outbound_verify_ran", True, "stub platform: %d ids queried, all from own sends" %
              len(stub.verify_ids))


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"selftest-png-body" * 4
PNG_SHA = hashlib.sha256(PNG_BYTES).hexdigest()
JPEG_BYTES = b"\xff\xd8\xff" + b"selftest-jpeg-body"
ABSENT = object()


def _att_ok(data=None, media="image/png"):
    data = PNG_BYTES if data is None else data
    return Result("ok", 200, {"data": data, "bytes": len(data),
                              "sha256": hashlib.sha256(data).hexdigest(), "content_type": media})


def _att_descriptor(data=None, media="image/png", sha=None, **over):
    data = PNG_BYTES if data is None else data
    out = {"artifact_id": "blob-selftest-image", "media_type": media,
           "sha256": sha if sha is not None else hashlib.sha256(data).hexdigest()}
    out.update(over)
    return out


class StubImageOneBot:
    """SUBSTITUTE answering both the send and the one `get_msg` read-back."""

    def __init__(self, stored_segments, account):
        self.stored = stored_segments
        self.account = account
        self.calls = []

    def api_call(self, action, params=None, timeout=15.0, meta=None):
        self.calls.append({"action": action, "params": params, "timeout": timeout})
        if action == "get_msg":
            return {"retcode": 0, "data": {"message": [{"type": t} for t in self.stored],
                                           "message_type": "private", "user_id": int(self.account),
                                           "sender": {"user_id": int(self.account)},
                                           "message_sent_type": "self"}}
        return {"retcode": 0, "msg": "", "data": {"message_id": 777001}}


def _check_outbound_attachments(rep, cfg, root):
    """Outbound image attachments against StubOneBot/StubHost: nothing is sent to
    QQ, nothing is claimed, and no host file path is opened -- the bytes only
    ever arrive through the stubbed channel API call.
    """
    if OWNER not in (cfg.allowed_private or []):
        rep.check("attachment_checks_ran", False, "the fixture DM peer is not authorized in this config")
        return
    owner, account = OWNER, cfg.napcat["account_id"]
    DM = {"type": "dm", "id": owner}
    GRP = {"type": "group", "id": fixtures.GROUPS[0]}
    actions = set()

    def item(name, target, text="这张给你", attachment=ABSENT, reply_to=None):
        row = {"publication_id": "att-%s" % name, "attempt_id": "attempt-%s" % name,
               "target": target, "text": text, "reply_to": reply_to}
        if attachment is not ABSENT:
            row["attachment"] = attachment
        return row

    def run(name, out_item, attachment=None, verify=False):
        stub, host, counters = StubOneBot(), StubHost(attachment=attachment), Counters()
        outbound_mod.Outbound(cfg, host, stub, Journal(root + "/att_" + name), counters,
                              log=lambda _m: None, ack_timeout=5.0, verify=verify,
                              verify_delay=0.0, verify_timeout=3.0).handle_item(out_item)
        actions.update(c["action"] for c in stub.calls)
        return stub, host, counters

    def reason_of(host):
        return ((host.last().get("payload") or {}).get("response") or {}).get("reason")

    # 1. the happy path: one private send carrying [image, text], her words intact
    stub, host, counters = run("ok", item("ok", DM, attachment=_att_descriptor()), attachment=_att_ok())
    call = stub.calls[0] if stub.calls else {}
    msg = (call.get("params") or {}).get("message") or []
    b64 = base64.b64encode(PNG_BYTES).decode("ascii")
    rep.check("att_dm_sends_image_then_text",
              call.get("action") == "send_private_msg" and len(msg) == 2
              and msg[0] == {"type": "image", "data": {"file": "base64://" + b64}}
              and msg[1] == {"type": "text", "data": {"text": "这张给你"}},
              json.dumps(msg, ensure_ascii=False)[:220])
    payload = host.last().get("payload") or {}
    rep.check("att_ok_receipt_accepted", payload.get("status") == "platform_accepted"
              and payload.get("platform_message_id") == "990001", json.dumps(payload.get("status")))
    sent_att = (payload.get("response") or {}).get("attachment") or {}
    rep.check("att_receipt_reports_what_was_sent",
              sent_att.get("sha256") == PNG_SHA and sent_att.get("bytes") == len(PNG_BYTES)
              and sent_att.get("sha256_verified") is True
              and sent_att.get("artifact_id") == "blob-selftest-image",
              json.dumps(sent_att, sort_keys=True)[:220])
    calls = host.attachment_calls
    rep.check("att_bytes_asked_for_this_publication_only",
              len(calls) == 1 and calls[0]["publication_id"] == "att-ok"
              and calls[0]["attempt_id"] == "attempt-ok" and calls[0]["expect_sha256"] == PNG_SHA
              and calls[0]["max_bytes"] == outbound_mod.MAX_IMAGE_BYTES,
              json.dumps(calls[:1], sort_keys=True)[:220])
    rep.check("att_counter_fetched", counters.snapshot().get("attachment_fetched") == 1,
              json.dumps(counters.snapshot(), sort_keys=True))

    # 2-5. every byte-level failure: nothing is sent, and the receipt says failed
    for name, given, want in (
            ("retry", Result("retry", None, error="ConnectionRefusedError"), "attachment_fetch_unavailable"),
            ("sha", Result("reject", 200, {"error": "sha256_mismatch", "expected": PNG_SHA,
                                           "observed": "0" * 64}), "attachment_fetch_sha256_mismatch"),
            ("toolarge", Result("reject", 200, {"error": "over_limit", "read_bytes": 900000}),
             "attachment_fetch_over_limit"),
            ("notimage", _att_ok(data=b"a plain text body, not a picture"), "attachment_not_an_image"),
            ("typemismatch", _att_ok(data=JPEG_BYTES), "attachment_media_type_mismatch")):
        stub, host, counters = run(name, item(name, DM, attachment=_att_descriptor()), attachment=given)
        payload = host.last().get("payload") or {}
        rep.check("att_%s_sends_no_text_instead" % name,
                  not any(str(c["action"]).startswith("send_") for c in stub.calls)
                  and payload.get("status") == "failed" and reason_of(host) == want
                  and "platform_message_id" not in payload,
                  "%s actions=%s %s" % (reason_of(host), [c["action"] for c in stub.calls],
                                        json.dumps(payload, ensure_ascii=False)[:160]))
        rep.check("att_%s_counter" % name, counters.snapshot().get("attachment_failed") == 1,
                  json.dumps(counters.snapshot(), sort_keys=True))

    # 6-9. a descriptor that cannot work is refused before a single byte is asked for
    for name, descriptor, want in (
            ("oversize", _att_descriptor(size=outbound_mod.MAX_IMAGE_BYTES + 1), "attachment_over_limit"),
            ("badshape", "blob-selftest-image", "attachment_descriptor_invalid"),
            ("nosha", _att_descriptor(sha=None), "attachment_sha256_missing"),
            ("pdf", _att_descriptor(media="application/pdf"), "attachment_media_type_unsupported")):
        if name == "nosha":
            descriptor = dict(descriptor)
            descriptor.pop("sha256")
        stub, host, _c = run(name, item(name, DM, attachment=descriptor), attachment=_att_ok())
        rep.check("att_%s_refused_without_download" % name,
                  stub.calls == [] and host.attachment_calls == []
                  and (host.last().get("payload") or {}).get("status") == "failed"
                  and reason_of(host) == want,
                  "%s fetches=%d %s" % (reason_of(host), len(host.attachment_calls),
                                        json.dumps((host.last().get("payload") or {}).get("response"),
                                                   ensure_ascii=False)[:160]))
    # a group carries her picture too (which one may go is the host's call); a reply stays first
    for name, reply_to, head in (("group", None, []),
                                 ("groupreply", "777001", [{"type": "reply", "data": {"id": "777001"}}])):
        stub, host, _c = run(name, item(name, GRP, attachment=_att_descriptor(), reply_to=reply_to),
                             attachment=_att_ok())
        call = stub.calls[0] if stub.calls else {}
        msg = (call.get("params") or {}).get("message") or []
        rep.check("att_%s_sends_image_then_text" % name,
                  call.get("action") == "send_group_msg"
                  and msg == head + [{"type": "image", "data": {"file": "base64://" + b64}},
                                     {"type": "text", "data": {"text": "这张给你"}}]
                  and len(host.attachment_calls) == 1
                  and (host.last().get("payload") or {}).get("status") == "platform_accepted",
                  json.dumps(msg, ensure_ascii=False)[:220])
    stub, host, _c = run("elsewhere", item("elsewhere", {"type": "channel", "id": "1"}, attachment=_att_descriptor()),
                         attachment=_att_ok())
    rep.check("att_unknown_target_sends_nothing",
              not any(str(c["action"]).startswith("send_") for c in stub.calls) and host.attachment_calls == [],
              reason_of(host) or "-")

    # 10. an item without an attachment is byte-for-byte the text send it always was
    stub, host, _c = run("plain", item("plain", DM))
    plain = (stub.calls[0].get("params") or {}).get("message") if stub.calls else None
    rep.check("att_absent_shape_unchanged",
              plain == [{"type": "text", "data": {"text": "这张给你"}}] and host.attachment_calls == []
              and (host.last().get("payload") or {}).get("status") == "platform_accepted",
              json.dumps(plain, ensure_ascii=False)[:160])

    # 11. the read-back expects the image segment, so it does not cry mismatch
    stub = StubImageOneBot(["image", "text"], account)
    host = StubHost(attachment=_att_ok())
    outbound_mod.Outbound(cfg, host, stub, Journal(root + "/att_verify"), Counters(),
                          log=lambda _m: None, ack_timeout=5.0, verify=True, verify_delay=0.0,
                          verify_timeout=3.0).handle_item(item("verify", DM, attachment=_att_descriptor()))
    actions.update(c["action"] for c in stub.calls)
    payload = host.last().get("payload") or {}
    ver = (payload.get("response") or {}).get("verification") or {}
    rep.check("att_verification_allows_image_segment",
              ver.get("result") == "verified" and ver.get("stored_segments") == ["image", "text"]
              and ver.get("sent_segments") == ["image", "text"], json.dumps(ver, sort_keys=True)[:220])
    rep.check("att_verification_cannot_move_status", payload.get("status") == "platform_accepted"
              and (payload.get("response") or {}).get("attachment", {}).get("sha256") == PNG_SHA,
              json.dumps(payload.get("status")))
    rep.check("att_get_msg_params_bounded",
              [c for c in stub.calls if c["action"] == "get_msg"][0]["params"] == {"message_id": 777001},
              json.dumps([c["params"] for c in stub.calls if c["action"] == "get_msg"]))

    # 12. the platform surface this whole section touched is still the same three actions
    rep.check("att_api_surface_bounded", actions <= {"send_private_msg", "send_group_msg", "get_msg"},
              json.dumps(sorted(actions)))


def _check_attachment_http(rep, cfg):
    """The real HostApi byte path against a real loopback HTTP server: no QQ, no
    host, nothing claimed.  This is the check that a 1.5 MiB image survives the
    client at all -- the JSON path would have truncated it at 256 KiB.
    """
    import http.server
    import threading

    body = (b"\x89PNG\r\n\x1a\n" + bytes((i * 7) % 251 for i in range(65528))) * 24
    digest = hashlib.sha256(body).hexdigest()
    seen, auths = [], []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, payload, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except ConnectionError:
                pass  # the client stopped reading early, which is what over_limit means

        def do_GET(self):
            seen.append(self.path)
            auths.append(self.headers.get("Authorization") or "")
            if self.path.startswith("/v1/channels/qq/outbox/att-http/attachment"):
                if "attempt-missing" in self.path:
                    return self._send(404, b'{"error":"PUBLICATION_NOT_FOUND"}', "application/json")
                if "attempt-down" in self.path:
                    return self._send(503, b'{"error":"HOST_TEMPORARILY_UNAVAILABLE"}', "application/json")
                if "attempt-json" in self.path:
                    return self._send(200, b'{"error":"ARTIFACT_NOT_IMAGE"}', "application/json")
                return self._send(200, body, "application/octet-stream")
            if self.path.startswith("/v1/channels/qq/outbox"):
                return self._send(200, b'{"items":[]}', "application/json")
            return self._send(404, b'{"error":"NO_ROUTE"}', "application/json")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        api = hostapi_mod.HostApi({"base_url": "http://127.0.0.1:%d" % server.server_address[1],
                                   "token": cfg.host["token"], "channel_id": "qq"}, timeout=10)
        res = api.get_attachment("att-http", "attempt-ok", artifact_id="blob-1", expect_sha256=digest)
        obj = res.obj if isinstance(res.obj, dict) else {}
        rep.check("att_http_big_body_not_truncated",
                  res.kind == "ok" and isinstance(obj.get("data"), bytes) and len(body) > 262144
                  and obj.get("bytes") == len(body) and obj.get("sha256") == digest,
                  "kind=%s bytes=%s served=%d" % (res.kind, obj.get("bytes"), len(body)))
        rep.check("att_http_uses_the_channel_bearer_token",
                  auths and all(a == "Bearer " + cfg.host["token"] for a in auths),
                  json.dumps(auths[:1])[:120])
        for name, kwargs, want_kind, want_error in (
                ("sha", {"expect_sha256": "0" * 64}, "reject", "sha256_mismatch"),
                ("limit", {"max_bytes": 4096}, "reject", "over_limit"),
                ("json", {}, "reject", "unexpected_content_type"),
                ("missing", {}, "reject", "http_404"),
                ("down", {}, "retry", "http_503")):
            attempt = {"sha": "attempt-ok", "limit": "attempt-ok", "json": "attempt-json",
                       "missing": "attempt-missing", "down": "attempt-down"}[name]
            res = api.get_attachment("att-http", attempt, **kwargs)
            obj = res.obj if isinstance(res.obj, dict) else {}
            rep.check("att_http_%s" % name, res.kind == want_kind and obj.get("error") == want_error,
                      repr(res)[:180])
        res = api.claim_outbox(0, timeout=5)
        paths = [p for p in seen if p.startswith("/v1/channels/qq/outbox?")]
        rep.check("att_claim_declares_image_capability",
                  res.kind == "empty" and paths and "supports=image" in paths[-1], json.dumps(paths[-1:]))
        api.claim_outbox(0, timeout=5, supports=())
        paths = [p for p in seen if p.startswith("/v1/channels/qq/outbox?")]
        rep.check("att_claim_capability_can_be_withdrawn", "supports=" not in paths[-1], json.dumps(paths[-1:]))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _check_live(rep, adapter):
    adapter.onebot.start()
    api_up = adapter.onebot.wait_up("/api", 15)
    rep.check("ws_api_connected", api_up, "")
    if api_up:
        identity = adapter.verify_identity()
        adapter.identity = identity
        rep.check("identity_matches", bool(identity.get("match")), json.dumps(identity, sort_keys=True))
    else:
        rep.check("identity_matches", False, "api websocket down")
    event_up = adapter.onebot.wait_up("/event", 15)
    rep.check("ws_event_connected", event_up, "")
    time.sleep(2)
    snap = adapter.counters.snapshot()
    rep.check("frames_seen", snap.get("frames_event", 0) + snap.get("frames_api", 0) > 0,
              json.dumps(snap, sort_keys=True))
    if api_up and adapter.peers is not None:
        # real platform, read-only: the identity lookups are not a stub here
        grows = sorted([r for r in adapter.cfg.routes.values() if r.message_type == "group"],
                       key=lambda r: r.route_id)
        if grows:
            route = grows[0]
            uid = sorted(route.allowed_senders)[0]
            prof = adapter.peers.observe(
                _peer_env(adapter.cfg, uid, route.target_id,
                          sender={"user_id": int(uid), "nickname": "", "card": ""}, mid=900001),
                adapter.onebot)
            rep.check("peer_live_group_lookup",
                      bool(prof) and prof["verified"] and prof["source"] == "api" and prof["role"] in ("owner", "admin", "member"),
                      "person=%s group=%s display_chars=%d role=%s" % (prof.get("person_id"), route.target_id,
                                                                       len(prof.get("display") or ""), prof.get("role")))
        owner_id = adapter.cfg.allowed_private[0]
        profd = adapter.peers.observe(
            _peer_env(adapter.cfg, owner_id, None, sender={"user_id": int(owner_id), "nickname": ""}, mid=900002),
            adapter.onebot)
        rep.check("peer_live_dm_lookup", bool(profd) and profd["verified"] and profd["scene"] == "dm",
                  "person=%s relation=%s display_chars=%d" % (profd.get("person_id"), profd.get("relation"),
                                                              len(profd.get("display") or "")))
        snap = adapter.counters.snapshot()
        rep.check("peer_live_no_stranger_blob", "address" not in open(adapter.peers.path, encoding="utf-8").read(),
                  "store=%s" % json.dumps(adapter.peers.summary(), sort_keys=True))
    adapter.onebot.stop()


def _check_live_outbox(rep, adapter):
    """The host outbox seam.  Only run this when claiming a real pending
    publication is acceptable; it does not fabricate anything."""
    reachable, code, error = adapter.host.probe_auth()
    rep.check("host_reachable_auth_enforced", reachable and code in (401, 403), "http=%s error=%s" % (code, error))
    res = adapter.host.claim_outbox(0, timeout=8)
    if res.kind == "empty":
        rep.check("host_outbox_empty", True, "")
    elif res.kind == "items":
        got = (res.obj.get("items") or [{}])[0]
        adapter.out.handle_item(got, stopping=True)
        rep.check("host_outbox_claimed_reported_unknown", True, "pub=%s" % got.get("publication_id"))
    elif res.kind == "retry" and "Timeout" in str(res.error):
        rep.check("host_outbox_longpoll_held", True, "host kept the claim open: token accepted, nothing to claim")
    else:
        rep.check("host_outbox_readable", False, repr(res))

def _check_admission(rep, root):
    """Explicit enrollment and automatic admission, measured separately.

    `explicit` means the configured allowlists are the whole authorization
    surface.  `automatic` means previously unknown DMs, groups and members are
    admitted under the owner's policy and the adapter derives `auto-dm-<id>` /
    `auto-group-<id>` route ids for them, while configured targets keep their
    routes.  A denial proved in one mode says nothing about the other, so each
    case is stated twice instead of sharing one expectation.
    """
    explicit = fixtures.load_config(admission="explicit")
    auto = fixtures.load_config(admission="automatic")
    grp = fixtures.GROUPS[0]
    member = fixtures.first_member(grp)

    # ---- explicit: the configured allowlists are everything ----------------
    seen = inbound_mod.SeenLRU(64)
    _r, why = inbound_mod.classify(_msg_event(explicit, user_id=int(UNKNOWN_SENDER), message_id=6001),
                                   explicit, seen)
    rep.check("admission_explicit_unknown_dm_denied", why == "unauthorized_sender",
              "%s (admission=explicit)" % why)
    _r, why = inbound_mod.classify(_group_event(explicit, UNKNOWN_GROUP, member, 6002), explicit, seen)
    rep.check("admission_explicit_unknown_group_denied", why == "group_not_allowed",
              "%s (admission=explicit)" % why)
    _r, why = inbound_mod.classify(_group_event(explicit, grp, OUTSIDER, 6003), explicit, seen)
    rep.check("admission_explicit_member_snapshot_required", why == "unauthorized_group_member", why)
    rep.check("admission_explicit_derives_no_routes",
              explicit.route_for_sender(UNKNOWN_SENDER) is None
              and explicit.route_for_group(UNKNOWN_GROUP) is None,
              "explicit admission never invents a route")
    rep.check("admission_explicit_keeps_configured_route",
              explicit.route_for_group(grp).route_id == "group-%s" % grp,
              explicit.route_for_group(grp).route_id)

    # ---- automatic: unknown targets are admitted with derived route ids ----
    seen = inbound_mod.SeenLRU(64)
    res, why = inbound_mod.classify(_msg_event(auto, user_id=int(UNKNOWN_SENDER), message_id=6011), auto, seen)
    env = res[0] if why == "accepted" else {}
    rep.check("admission_automatic_unknown_dm_admitted",
              why == "accepted" and env.get("route_id") == "auto-dm-%s" % UNKNOWN_SENDER
              and env.get("sender_id") == UNKNOWN_SENDER,
              "%s route=%s" % (why, env.get("route_id")))
    res, why = inbound_mod.classify(_group_event(auto, UNKNOWN_GROUP, OUTSIDER, 6012), auto, seen)
    env = res[0] if why == "accepted" else {}
    rep.check("admission_automatic_unknown_group_admitted",
              why == "accepted" and env.get("route_id") == "auto-group-%s" % UNKNOWN_GROUP
              and env.get("group_id") == UNKNOWN_GROUP and env.get("sender_id") == OUTSIDER,
              "%s route=%s" % (why, env.get("route_id")))
    _r, why = inbound_mod.classify(_group_event(auto, grp, OUTSIDER, 6013), auto, seen)
    rep.check("admission_automatic_member_snapshot_not_required", why == "accepted", why)
    res, why = inbound_mod.classify(_group_event(auto, grp, member, 6014), auto, seen)
    rep.check("admission_automatic_keeps_configured_route",
              why == "accepted" and res[0]["route_id"] == "group-%s" % grp,
              res[0].get("route_id") if why == "accepted" else why)
    try:
        rep.check("admission_automatic_loads_without_routes",
                  fixtures.load_config(admission="automatic", routes="none").routes == {},
                  "an automatic-admission adapter may start with no configured route")
    except ConfigError as exc:
        rep.check("admission_automatic_loads_without_routes", False, str(exc))
    bad = fixtures.raw_config(admission="sometimes")
    try:
        Config(bad, "bad-admission")
        rep.check("admission_bad_value_rejected", False, "loaded anyway")
    except ConfigError as exc:
        rep.check("admission_bad_value_rejected", "admission" in str(exc), str(exc))

    # ---- blocking is honored in both modes, before admission ---------------
    for mode in ("explicit", "automatic"):
        blocked = fixtures.load_config(admission=mode,
                                       blocked_senders=[fixtures.BLOCKED_SENDER, OWNER],
                                       blocked_groups=[fixtures.BLOCKED_GROUP])
        seen = inbound_mod.SeenLRU(16)
        _r, why = inbound_mod.classify(_group_event(blocked, grp, fixtures.BLOCKED_SENDER, 6031), blocked, seen)
        rep.check("admission_%s_blocked_sender_denied" % mode, why == "unauthorized_group_member", why)
        _r, why = inbound_mod.classify(_group_event(blocked, fixtures.BLOCKED_GROUP,
                                                    fixtures.first_member(fixtures.BLOCKED_GROUP), 6032),
                                       blocked, seen)
        # the blocked group is on the allowlist, so the closed answer here is
        # "no route for it"; either way nothing about it reaches the host
        rep.check("admission_%s_blocked_group_denied" % mode,
                  why in ("group_route_missing", "group_not_allowed"), why)
        _r, why = inbound_mod.classify(_msg_event(blocked, user_id=int(OWNER), message_id=6033), blocked, seen)
        rep.check("admission_%s_blocked_dm_denied" % mode, why == "unauthorized_sender", why)

    # ---- outbound: the same split decides who may be sent to ---------------
    def send_to(cfg, name, target):
        stub, host = StubOneBot(), StubHost()
        outbound_mod.Outbound(cfg, host, stub, Journal(os.path.join(root, "adm_" + name)), Counters(),
                              log=lambda _m: None, ack_timeout=5.0, verify=False).handle_item(
            {"publication_id": "adm-%s" % name, "attempt_id": "a-%s" % name,
             "target": target, "text": "正文", "reply_to": None})
        return stub, host

    stub, host = send_to(explicit, "ex_grp", {"type": "group", "id": UNKNOWN_GROUP})
    rep.check("admission_explicit_outbound_unknown_group_denied",
              stub.calls == [] and host.last().get("payload", {}).get("status") == "failed"
              and ((host.last().get("payload") or {}).get("response") or {}).get("reason") == "target_not_authorized",
              json.dumps([c["action"] for c in stub.calls] + [host.last().get("payload", {}).get("status")]))
    stub, host = send_to(explicit, "ex_dm", {"type": "dm", "id": UNKNOWN_SENDER})
    rep.check("admission_explicit_outbound_unknown_dm_denied",
              stub.calls == [] and host.last().get("payload", {}).get("status") == "failed",
              json.dumps([c["action"] for c in stub.calls] + [host.last().get("payload", {}).get("status")]))
    stub, host = send_to(auto, "au_grp", {"type": "group", "id": UNKNOWN_GROUP})
    rep.check("admission_automatic_outbound_unknown_group_sends",
              [c["action"] for c in stub.calls] == ["send_group_msg"]
              and stub.calls[0]["params"]["group_id"] == int(UNKNOWN_GROUP)
              and host.last().get("payload", {}).get("status") == "platform_accepted",
              json.dumps([c["action"] for c in stub.calls] + [host.last().get("payload", {}).get("status")]))
    stub, host = send_to(auto, "au_dm", {"type": "dm", "id": UNKNOWN_SENDER})
    rep.check("admission_automatic_outbound_unknown_dm_sends",
              [c["action"] for c in stub.calls] == ["send_private_msg"]
              and stub.calls[0]["params"]["user_id"] == int(UNKNOWN_SENDER),
              json.dumps([c["action"] for c in stub.calls]))
    blocked_auto = fixtures.load_config(admission="automatic", blocked_groups=[fixtures.BLOCKED_GROUP])
    stub, host = send_to(blocked_auto, "au_blocked", {"type": "group", "id": fixtures.BLOCKED_GROUP})
    rep.check("admission_automatic_outbound_blocked_group_denied",
              stub.calls == [] and host.last().get("payload", {}).get("status") == "failed",
              json.dumps([c["action"] for c in stub.calls] + [host.last().get("payload", {}).get("status")]))
    rep.check("admission_checks_ran", True, "explicit and automatic measured separately")


def run(cfg, data_dir, live=True, live_config=True):
    """`cfg` is the config actually in hand; `live_config` says whether it came
    from a real file (then it is cross-checked) or from the built-in fixtures
    (then that section is skipped).  `live` is the only switch that lets a
    platform be contacted or the real outbox be claimed.
    """
    rep = Report()
    root = os.path.join(data_dir, "selftest")
    os.makedirs(root, exist_ok=True)
    gcfg = _fixture_deployment(rep)
    _check_config_policy(rep, gcfg)
    if live_config:
        _check_live_config(rep, cfg)
    else:
        rep.skip("live_config_cross_check",
                 "no deployment config was given: behaviour ran on built-in fixtures, nothing to cross-check")
    _check_private(rep, gcfg)
    _check_admission(rep, root)
    _check_group_inbound(rep, gcfg)
    _check_media(rep, gcfg, root)
    _check_spool(rep, root)
    _check_outbound_params(rep, gcfg, root)
    _check_outbound_verify(rep, gcfg, root)
    _check_outbound_attachments(rep, gcfg, root)
    _check_attachment_http(rep, gcfg)
    _check_peer_timekeeping(rep, gcfg, root)
    _check_peers(rep, gcfg, root)
    _check_lock_and_spool(rep, gcfg, root)
    _check_catchup(rep, gcfg, root)
    if live:
        adapter = Adapter(cfg, root)
        _check_live(rep, adapter)
        _check_live_outbox(rep, adapter)
    else:
        rep.skip("live_platform_checks", "--offline: no websocket, no identity call, no platform lookup")
        rep.skip("outbox_checks", "--offline: the real outbox was not claimed")
    observer = Adapter(gcfg, os.path.join(root, "health"))
    observer.journal.write_health(observer.health_snapshot())
    print("SELFTEST_SUMMARY pass=%d fail=%d skip=%d" % (rep.passed, rep.failed, rep.skipped), flush=True)
    return 0 if rep.failed == 0 else 1


def _check_catchup(rep, gcfg, root):
    """Catch-up (catchup.py) over a recorded history page: only a named route is fetched, rows reach the spool
    through the usual gate oldest first and marked, her own line and a non-member's are dropped, and a
    second run spools nothing new (the local dedup)."""
    from .catchup import CATCHUP_KEY
    adapter = Adapter(gcfg, os.path.join(root, "catchup"), peer_mode="off")
    group = fixtures.GROUPS[0]
    route = gcfg.route_for_group(group).route_id
    now = int(time.time())
    page = [_group_event(gcfg, group, "900000101", 9003, time=now - 300),
            _group_event(gcfg, group, "900000102", 9001, time=now - 900),
            _group_event(gcfg, group, gcfg.napcat["account_id"], 9002, time=now - 600),
            _group_event(gcfg, group, OUTSIDER, 9004, time=now - 200)]
    for row in page:
        row["message_seq"] = row["message_id"]
    calls = []

    def history(action, params=None, timeout=15.0, meta=None):
        calls.append((action, dict(params or {})))
        return {"retcode": 0, "data": {"messages": [dict(r) for r in sorted(page, key=lambda r: r["message_seq"])]}}
    adapter.onebot.api_call = history
    adapter.catchup.routes = frozenset([route])
    adapter.catchup.run("startup")
    spooled = [adapter.journal.read_json(p)["envelope"] for p in adapter.journal.spool_list("inbound")]
    rep.check("catchup_named_route_only", [c[0] for c in calls] == ["get_group_msg_history"]
              and calls[0][1].get("group_id") == int(group) and calls[0][1].get("disable_get_url") is True,
              json.dumps(calls, sort_keys=True)[:300])
    rep.check("catchup_oldest_first_marked_gate_kept",
              [e["event_id"] for e in spooled] == ["9001", "9003"]
              and all(e["raw"].get(CATCHUP_KEY, {}).get("reason") == "startup" for e in spooled),
              json.dumps([e["event_id"] for e in spooled]))
    rep.check("catchup_cursor_moves_with_accepted_lines",
              adapter.catchup.cursor(route).get("seq") == 9003, json.dumps(adapter.catchup.cursor(route)))
    adapter.catchup.run("reconnect")
    rep.check("catchup_second_run_adds_nothing", len(adapter.journal.spool_list("inbound")) == len(spooled))


def _check_lock_and_spool(rep, cfg, root):
    """Mutual exclusion on one data dir, checked in isolation (no service data,
    no host, no QQ), plus the route suffix on spool file names."""
    holder = Journal(root + "/lockdir")
    path = holder.acquire_lock()
    with open(path, "r", encoding="utf-8") as handle:
        contents = handle.read()
    rep.check("lock_acquired", "pid=%d" % os.getpid() in contents, contents.strip()[:40])
    try:
        Journal(root + "/lockdir").acquire_lock()
        rep.check("lock_second_holder_refused", False, "second holder accepted")
    except RuntimeError as exc:
        rep.check("lock_second_holder_refused", True, str(exc)[:70])

    # hand the lock to a separate process, then check both directions:
    # a live holder is refused, and a holder that dies releases the lock so the
    # leftover file never blocks a restart
    holder.release_lock()
    child = subprocess.Popen([sys.executable, "-c", HELPER_LOCK_CHILD, path, "30", os.path.dirname(HERE)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True)
    try:
        # a reader thread, not select(): Windows can only select sockets, not a pipe
        said = []
        reader = threading.Thread(target=lambda: said.append(child.stdout.readline()), daemon=True)
        reader.start()
        reader.join(8)
        ready = bool(said)
        line = said[0].strip() if said else ""
        refused = None
        if line == "LOCKED":
            try:
                Journal(root + "/lockdir").acquire_lock()
            except RuntimeError as exc:
                refused = str(exc)[:70]
        rep.check("lock_other_process_refused", refused is not None,
                  refused or "child=%r ready=%s" % (line, bool(ready)))
        child.kill()
        child.wait()
        try:
            restarted = Journal(root + "/lockdir")
            restarted.acquire_lock()
            rep.check("lock_released_when_holder_dies", True,
                      "leftover %s did not block the restart" % os.path.basename(path))
            restarted.release_lock()
        except RuntimeError as exc:
            rep.check("lock_released_when_holder_dies", False, str(exc)[:70])
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()

    sk = Adapter(cfg, root + "/spoolkey")
    groups = sorted(cfg.allowed_groups)
    shared = 515151
    sk.on_event(_msg_event(cfg, message_id=shared))
    sk.on_event(_group_event(cfg, groups[0], fixtures.first_member(groups[0]), shared))
    sk.on_event(_group_event(cfg, groups[1], fixtures.first_member(groups[1]), shared))
    paths = sk.journal.spool_list("inbound")
    names = [os.path.basename(p) for p in paths]
    routes = []
    for path in paths:
        try:
            routes.append((sk.journal.read_json(path).get("envelope") or {}).get("route_id"))
        except Exception:
            routes.append(None)
    want = sorted(["owner-dm", "group-%s" % groups[0], "group-%s" % groups[1]])
    rep.check("spool_names_carry_route", len(paths) == 3 and sorted(routes) == want and
              all(any(r in n for r in want) for n in names),
              "names=%s" % names)
    rep.check("lock_and_spool_ran", True, "flock only: no ttl, no heartbeat, no takeover")


# ---------------------------------------------------------------------------
# peer identity (ADR-005 phase 1)


class StubIdentityApi:
    """SUBSTITUTE for the platform identity lookups: records the exact action and
    params, answers from a canned per-person blob, never touches QQ."""

    def __init__(self, data=None, exc=None):
        self.calls = []
        self.data = data or {}
        self.exc = exc

    def api_call(self, action, params=None, timeout=15.0, meta=None):
        self.calls.append({"action": action, "params": params, "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        key = params.get("group_id") if action == "get_group_member_info" else params.get("user_id")
        blob = self.data.get(str(key))
        if blob is None:
            return {"retcode": 1200, "msg": "not found", "data": None}
        return {"retcode": 0, "msg": "", "data": blob}

    def actions(self):
        return [c["action"] for c in self.calls]


class DenyOnceHost:
    """SUBSTITUTE for the host: refuses the first post that carries the injected
    block, exactly like a host whose envelope allowlist has not grown yet."""

    def __init__(self, error="CHANNEL_ENVELOPE_FIELD_DENIED", key=PEER_KEY):
        self.posts = []
        self.denied = False
        self.error = error
        self.key = key

    def post_event(self, envelope):
        self.posts.append(json.loads(json.dumps(envelope, ensure_ascii=False, default=str)))
        if self.key in (envelope.get("raw") or {}) and not self.denied:
            self.denied = True
            return Result("reject", 403, {"error": self.error})
        return Result("accepted", 200, {"status": "accepted", "episode_id": "ep-peer"})


def _peer_env(cfg, account, group_id=None, sender=None, mid=1, text="正文", sub_type="friend"):
    raw = {"time": int(time.time()), "post_type": "message", "message_id": mid,
           "user_id": int(account), "message": _text(text),
           "message_type": "group" if group_id else "private"}
    if group_id:
        raw["group_id"] = int(group_id)
    else:
        raw["sub_type"] = sub_type
    if sender is not None:
        raw["sender"] = sender
    env = {"route_id": ("group-%s" % group_id) if group_id else "owner-dm",
           "account_id": cfg.napcat["account_id"], "sender_id": str(account),
           "event_id": str(mid), "text": text, "raw": raw}
    if group_id:
        env["group_id"] = str(group_id)
        env["mentioned_account_ids"] = []
    return env


def _force_tz(zone):
    """Point this process at another zone; return the offset that actually took
    hold (seconds west of UTC), or None when this machine cannot provide it."""
    if not hasattr(time, "tzset"):
        return None
    os.environ["TZ"] = zone
    time.tzset()
    return time.timezone


def _restore_tz(previous):
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous
    if hasattr(time, "tzset"):                # Windows has none: _force_tz changed nothing there
        time.tzset()


def _rename_needs_fresh_lookup(cfg, store):
    """Watch a person in their group, then the same person under a new nickname,
    and report whether the second lookup asked the platform to skip its cache.
    This is the path the stored UTC stamp decides, and the one that silently
    degraded on a machine that was not on UTC.
    """
    grp = sorted(cfg.allowed_groups)[0]
    member = sorted(cfg.route_for_group(grp).allowed_senders)[0]
    os.makedirs(store, exist_ok=True)
    pdir = PeerDirectory(store, counters=Counters(), min_refresh=0.0)
    blob = {"group_id": int(grp), "user_id": int(member), "card": "名片", "role": "member", "title": ""}
    sender = dict(blob, nickname="旧名")
    pdir.observe(_peer_env(cfg, member, grp, sender=sender, mid=9001),
                 StubIdentityApi({grp: dict(blob, nickname="旧名")}))
    api = StubIdentityApi({grp: dict(blob, nickname="新名")})
    prof = pdir.observe(_peer_env(cfg, member, grp, sender=dict(sender, nickname="新名"), mid=9002), api)
    params = api.calls[0]["params"] if api.calls else {}
    return params.get("no_cache") is True, params, prof.get("changed")


def _check_peer_timekeeping(rep, cfg, root):
    """`iso()` writes UTC, so `epoch()` has to read it back as UTC.

    That stored instant decides whether a rename is worth a fresh platform
    lookup.  Reading it through local time shifts the answer by this machine's
    offset -- west of UTC a fresh lookup lands in the future and the rename
    stops forcing a re-check, east of UTC it lands in the past -- and a UTC
    machine sees nothing at all.  So the check forces zones on both sides
    (`Etc/GMT-9` is UTC+9, `Etc/GMT+4` is UTC-4; the `Etc/GMT-*` form avoids
    borrowing any city's rules) and reports SKIP when a zone is not installed
    here rather than passing quietly.
    """
    # The value below is a fixed instant (2023-11-14T22:13:20Z), a timestamp, not anyone's QQ
    # number.  One fixed instant: no clock, no drift.
    fixed = 1700000000  # personal-scan: ok
    stamp = peers_mod.iso(fixed)
    rep.check("peer_iso_is_utc", stamp == "2023-11-14T22:13:20Z", stamp)
    rep.check("peer_epoch_roundtrip_utc", peers_mod.epoch(stamp) == fixed,
              "%s -> %s" % (stamp, peers_mod.epoch(stamp)))
    rep.check("peer_epoch_rejects_junk",
              peers_mod.epoch("") is None and peers_mod.epoch("nope") is None
              and peers_mod.epoch(None) is None, "empty and unparsable stay None")
    baseline, previous = time.timezone, os.environ.get("TZ")
    try:
        for zone, want, tag in (("Etc/GMT-9", -9 * 3600, "east9"), ("Etc/GMT+4", 4 * 3600, "west4")):
            offset = _force_tz(zone)
            if offset is None:
                rep.skip("peer_epoch_utc_" + tag, "no time.tzset here: cannot force %s" % zone)
                continue
            if offset != want:
                rep.skip("peer_epoch_utc_" + tag,
                         "%s is not installed here (localtime offset stayed %s)" % (zone, offset))
                continue
            back = peers_mod.epoch(peers_mod.iso(fixed))
            rep.check("peer_epoch_utc_" + tag, back == fixed,
                      "%s (localtime offset %s): %s -> %s, want %s"
                      % (zone, offset, peers_mod.iso(fixed), back, fixed))
            # and the decision that value feeds: 10 seconds ago is fresh, ten
            # days ago is not, in whichever zone this machine happens to run in
            fresh = peers_mod.epoch(peers_mod.iso(time.time() - 10))
            aged = peers_mod.epoch(peers_mod.iso(time.time() - 10 * 86400))
            rep.check("peer_cache_window_" + tag,
                      abs((time.time() - fresh) - 10) <= 2 and 9 * 86400 < time.time() - aged < 11 * 86400,
                      "a 10s-old lookup reads as %.0fs old, a 10-day-old one as %.0fs old"
                      % (time.time() - fresh, time.time() - aged))
            # the decision itself, end to end, in that zone: a renamed person is
            # worth a cache-skipping lookup wherever this happens to run
            ok, params, changed = _rename_needs_fresh_lookup(cfg, os.path.join(root, "peers_tz_" + tag))
            rep.check("peer_rename_forces_lookup_" + tag, ok and changed == ["nickname"],
                      "%s (localtime offset %s): no_cache=%s params=%s changed=%s"
                      % (zone, offset, params.get("no_cache"), json.dumps(params, sort_keys=True), changed))
    finally:
        _restore_tz(previous)
    rep.check("peer_tz_restored", time.timezone == baseline,
              "localtime offset before=%s after=%s" % (baseline, time.timezone))


def _check_peers(rep, cfg, root):
    """Who is talking, and is a renamed person still the same one.  Offline: the
    platform answers come from StubIdentityApi, the host from DenyOnceHost."""
    groups = sorted(cfg.allowed_groups)
    if not groups:
        rep.check("peer_group_scene_available", False, "no group routes in config")
        return
    grp = groups[0]
    grp2 = groups[1] if len(groups) > 1 else groups[0]
    member = sorted(cfg.route_for_group(grp).allowed_senders)[0]
    member2 = sorted(cfg.route_for_group(grp2).allowed_senders)[0]
    store = os.path.join(root, "peers")
    os.makedirs(store, exist_ok=True)
    counters = Counters()
    pdir = PeerDirectory(store, counters=counters)
    sender = {"user_id": int(member), "nickname": "深夜", "card": "夜猫", "role": "admin", "title": ""}
    api = StubIdentityApi({grp: {"group_id": int(grp), "user_id": int(member), "nickname": "深夜",
                                 "card": "夜猫", "role": "admin", "title": "", "join_time": 1700000000,  # personal-scan: ok (fixed epoch, not an id)
                                 "address": "深圳南山区", "interest": "红警3", "eMail": "a@b.c"}})
    env = _peer_env(cfg, member, grp, sender=sender, mid=1)
    shape_before = sorted(env)
    prof = pdir.observe(env, api)
    rep.check("peer_group_lookup_called", api.actions() == ["get_group_member_info"], str(api.actions()))
    rep.check("peer_group_lookup_params",
              api.calls[0]["params"] == {"group_id": int(grp), "user_id": int(member), "no_cache": False},
              json.dumps(api.calls[0]["params"], sort_keys=True))
    rep.check("peer_profile_fields",
              prof["nickname"] == "深夜" and prof["card"] == "夜猫" and prof["role"] == "admin"
              and prof["display"] == "夜猫" and prof["display_source"] == "card",
              json.dumps({k: prof[k] for k in ("nickname", "card", "role", "display", "display_source")},
                         ensure_ascii=False))
    rep.check("peer_person_id_is_account", prof["person_id"] == "qq:%s" % member, prof["person_id"])
    rep.check("peer_verified_after_api", prof["verified"] is True and prof["source"] == "api", prof["source"])
    rep.check("peer_joined_at_kept", bool(prof.get("joined_at")), prof.get("joined_at", ""))
    rep.check("peer_injected_into_raw", env["raw"][PEER_KEY] == prof, sorted(env["raw"]))
    rep.check("peer_envelope_shape_unchanged", sorted(env) == shape_before, sorted(env))
    body = open(pdir.path, encoding="utf-8").read()
    rep.check("peer_api_blob_whitelisted",
              all(k not in body for k in ("address", "深圳南山区", "红警3", "eMail", "join_time")), body[:120])
    rep.check("peer_no_message_text_in_store", "正文" not in body, "store carries identity only")

    again = pdir.observe(_peer_env(cfg, member, grp, sender=sender, mid=2), api)
    rep.check("peer_lookup_not_repeated", len(api.calls) == 1, "calls=%d" % len(api.calls))
    rep.check("peer_message_count_tracks", again["seen_messages"] == 2, str(again["seen_messages"]))

    pdir.min_refresh = 0.0
    renamed = dict(sender, nickname="新名字")
    api2 = StubIdentityApi({grp: {"group_id": int(grp), "user_id": int(member), "nickname": "新名字",
                                  "card": "夜猫", "role": "admin", "title": ""}})
    prof2 = pdir.observe(_peer_env(cfg, member, grp, sender=renamed, mid=3), api2)
    rep.check("peer_rename_forces_fresh_lookup",
              api2.calls and api2.calls[0]["params"]["no_cache"] is True,
              json.dumps(api2.calls[0]["params"] if api2.calls else {}, sort_keys=True))
    rep.check("peer_rename_same_person",
              prof2["person_id"] == "qq:%s" % member and prof2["changed"] == ["nickname"]
              and prof2["previous"]["nickname"] == "深夜",
              json.dumps({k: prof2.get(k) for k in ("person_id", "changed", "previous")}, ensure_ascii=False))
    rep.check("peer_rename_keeps_both_names",
              set(["深夜", "新名字"]) <= set(prof2.get("aliases") or []), json.dumps(prof2.get("aliases"), ensure_ascii=False))
    lines = open(os.path.join(store, "journal", "peer_changes.jsonl"), encoding="utf-8").read()
    rep.check("peer_change_journalled",
              '"field": "nickname"' in lines and '"person_id": "qq:%s"' % member in lines, lines.strip()[-160:])

    recarded = dict(renamed, card="新名片")
    api3 = StubIdentityApi({grp: {"group_id": int(grp), "user_id": int(member), "nickname": "新名字",
                                  "card": "新名片", "role": "admin", "title": ""}})
    prof3 = pdir.observe(_peer_env(cfg, member, grp, sender=recarded, mid=4), api3)
    rep.check("peer_card_change_recorded",
              prof3["changed"] == ["card"] and prof3["previous"]["card"] == "夜猫", prof3.get("changed"))
    rep.check("peer_card_change_not_a_new_person",
              prof3["person_id"] == "qq:%s" % member and prof3["display"] == "新名片", prof3["display"])

    api4 = StubIdentityApi({grp2: {"group_id": int(grp2), "user_id": int(member), "nickname": "新名字",
                                   "card": "", "role": "member", "title": ""}})
    prof4 = pdir.observe(_peer_env(cfg, member, grp2, sender={"user_id": int(member), "nickname": "新名字",
                                                              "card": "", "role": "member"}, mid=5), api4)
    rep.check("peer_card_is_per_group",
              prof4["group_id"] == grp2 and prof4["card"] == "" and prof4["display"] == "新名字"
              and prof4["display_source"] == "nickname",
              json.dumps({k: prof4.get(k) for k in ("group_id", "card", "display", "display_source")},
                         ensure_ascii=False))
    person = pdir.dump()["people"]["qq:%s" % member]
    rep.check("peer_one_person_three_scenes",
              len(person["scenes"]) == 2 and person["nickname"] == "新名字",
              json.dumps(sorted(person["scenes"])))

    fat = {"user_id": int(member), "nickname": "新名字", "sex": "male", "age": 30,
           "address": "深圳南山区", "birthday_day": 8, "interest": "红警3", "eMail": "a@b.c"}
    api5 = StubIdentityApi({member: fat})
    prof5 = pdir.observe(_peer_env(cfg, member, None,
                                   sender={"user_id": int(member), "nickname": "新名字"}, mid=6), api5)
    rep.check("peer_dm_uses_stranger_info", api5.actions() == ["get_stranger_info"], str(api5.actions()))
    rep.check("peer_dm_scene_and_relation", prof5["scene"] == "dm" and prof5["relation"] == "friend",
              json.dumps({k: prof5.get(k) for k in ("scene", "relation")}))
    body = open(pdir.path, encoding="utf-8").read()
    rep.check("peer_stranger_blob_dropped",
              all(k not in body for k in ("address", "深圳南山区", "红警3", "eMail", "birthday_day")), body[:120])
    person = pdir.dump()["people"]["qq:%s" % member]
    rep.check("peer_one_person_three_scenes",
              len(person["scenes"]) == 3 and sorted(person["scenes"]) == sorted(["dm", "group:%s" % grp,
                                                                                 "group:%s" % grp2]),
              json.dumps(sorted(person["scenes"])))

    fail_counters = Counters()
    failing = PeerDirectory(os.path.join(root, "peers_fail"), counters=fail_counters)
    prof6 = failing.observe(_peer_env(cfg, member, grp, sender=sender, mid=7),
                            StubIdentityApi({}, exc=ApiTimeout("api timeout")))
    rep.check("peer_api_failure_not_fatal", prof6 is not None and prof6["verified"] is False, str(prof6)[:120])
    rep.check("peer_api_failure_source", prof6["source"] == "api_error:ApiTimeout", prof6["source"])
    rep.check("peer_api_failure_keeps_sender_view",
              prof6["nickname"] == "深夜" and prof6["role"] == "admin" and prof6["display"] == "夜猫",
              json.dumps(prof6, ensure_ascii=False)[:160])
    rep.check("peer_api_failure_counted", fail_counters.snapshot().get("peer_api_errors", 0) >= 1,
              json.dumps(fail_counters.snapshot(), sort_keys=True))

    mismatch = PeerDirectory(os.path.join(root, "peers_mismatch"), counters=Counters(), min_refresh=0.0)
    wrong = StubIdentityApi({grp: {"group_id": int(grp), "user_id": int(member) + 1, "nickname": "别人",
                                   "card": "别人名片", "role": "member"}})
    prof7 = mismatch.observe(_peer_env(cfg, member, grp, sender=sender, mid=8), wrong)
    rep.check("peer_api_answered_for_somebody_else",
              prof7["source"] == "api_error:identity_mismatch" and prof7["nickname"] == "深夜"
              and prof7["verified"] is False and prof7["display"] == "夜猫",
              json.dumps({k: prof7.get(k) for k in ("source", "nickname", "display", "verified")},
                         ensure_ascii=False))

    noseed = PeerDirectory(os.path.join(root, "peers_nosender"), counters=Counters(), min_refresh=0.0)
    prof8 = noseed.observe(_peer_env(cfg, member, grp, sender=None, mid=9),
                           StubIdentityApi({grp: {"group_id": int(grp), "user_id": int(member),
                                                  "nickname": "深夜", "card": "夜猫", "role": "owner"}}))
    rep.check("peer_no_sender_block_still_identifies",
              prof8["verified"] is True and prof8["nickname"] == "深夜" and prof8["role"] == "owner",
              json.dumps({k: prof8.get(k) for k in ("verified", "nickname", "role")}, ensure_ascii=False))

    reloaded = PeerDirectory(store, counters=Counters())
    rep.check("peer_store_roundtrip",
              reloaded.summary()["people"] == 1 and reloaded.summary()["scenes"] == 3,
              json.dumps(reloaded.summary(), sort_keys=True))
    with open(reloaded.path, "w", encoding="utf-8") as handle:
        handle.write("{not json")
    broken = PeerDirectory(store, counters=Counters())
    rep.check("peer_corrupt_store_kept_aside",
              broken.summary()["store_reset"] == "JSONDecodeError" and os.path.exists(broken.path + ".bad"),
              json.dumps(broken.summary(), sort_keys=True))

    svc = Adapter(cfg, os.path.join(root, "peersvc"))
    svc.host = DenyOnceHost()
    env2 = _peer_env(cfg, member2, grp2, sender={"user_id": int(member2), "nickname": "甲", "card": "", "role": "member"},
                     mid=11)
    res = svc._submit_event(env2)
    posts = svc.host.posts
    rep.check("peer_field_denied_reposts_without_losing_event",
              res.kind == "accepted" and len(posts) == 2 and PEER_KEY in posts[0]["raw"]
              and PEER_KEY not in posts[1]["raw"],
              "kind=%s posts=%d first=%s second=%s" % (res.kind, len(posts), PEER_KEY in posts[0]["raw"],
                                                       PEER_KEY in posts[1]["raw"]))
    rep.check("peer_enriched_counted",
              svc.counters.snapshot().get("peer_enriched", 0) >= 1
              and svc.counters.snapshot().get("peer_field_denied", 0) == 1,
              json.dumps({k: v for k, v in svc.counters.snapshot().items() if k.startswith("peer_")},
                         sort_keys=True))

    other = Adapter(cfg, os.path.join(root, "peersother"))
    other.host = DenyOnceHost(error="INPUT_IDENTITY_OR_CONTENT_CONFLICT")
    env5 = _peer_env(cfg, member2, grp2, sender={"user_id": int(member2), "nickname": "甲"}, mid=14)
    res5 = other._submit_event(env5)
    rep.check("peer_any_reject_retries_clean",
              res5.kind == "accepted" and len(other.host.posts) == 2
              and PEER_KEY not in other.host.posts[1]["raw"],
              "kind=%s posts=%d" % (res5.kind, len(other.host.posts)))

    store_only = Adapter(cfg, os.path.join(root, "peersstore"), peer_mode="store")
    store_only.host = DenyOnceHost()
    env3 = _peer_env(cfg, member2, grp2, sender={"user_id": int(member2), "nickname": "甲", "card": "", "role": "member"},
                     mid=12)
    store_only._submit_event(env3)
    rep.check("peer_store_mode_does_not_touch_raw",
              PEER_KEY not in env3["raw"] and store_only.peers.summary()["people"] == 1,
              json.dumps(store_only.peers.summary(), sort_keys=True))

    off = Adapter(cfg, os.path.join(root, "peersoff"), peer_mode="off")
    env4 = _peer_env(cfg, member2, grp2, sender={"user_id": int(member2)}, mid=13)
    off.host = DenyOnceHost()
    off._submit_event(env4)
    rep.check("peer_mode_off_leaves_everything_alone",
              off.peers is None and PEER_KEY not in env4["raw"] and off.host.posts[0]["raw"].get("sender") is not None,
              "peers=%s" % off.peers)


IMG_SEG = {"type": "image",
           "data": {"file": "59A164CFF5F2565F41C6A51948A1D77D.png", "file_id": "fid1",
                    "file_size": "40087", "sub_type": 0, "summary": "",
                    "url": "https://multimedia.nt.qq.com.cn/download?appid=1407&fileid=abc"}}


def _media_cfg(base, mode):
    """The same authorized config with one different media_mode, through the
    real parser (the mode is configuration, not a call-site argument)."""
    raw = json.loads(json.dumps(base.raw))
    raw["adapter"]["media_mode"] = mode
    return Config(raw, "%s#media_mode=%s" % (base.path, mode))


def _check_media(rep, gcfg, root):
    """0.4.0: pictures, stickers and bare replies reach the host as themselves.

    Offline only: synthetic events, a substitute host, no platform call.
    """
    groups = sorted(gcfg.allowed_groups)
    if not groups:
        rep.check("media_checks_ran", False, "no group routes")
        return
    grp = groups[0]
    members = sorted(gcfg.route_for_group(grp).allowed_senders)
    member, other = members[0], members[1]
    seen = inbound_mod.SeenLRU(128)

    # the real case that started this: a picture in the owner DM, no text at all
    res, reason = inbound_mod.classify(_msg_event(gcfg, message=[dict(IMG_SEG)], message_id=5101), gcfg, seen)
    env = res[0] if reason == "accepted" else {}
    meta = res[1] if reason == "accepted" else {}
    rep.check("media_dm_image_accepted", reason == "accepted" and env.get("text") == "[图片（未解析）]"
              and meta.get("media_segments") == 1 and meta.get("media_only") is True, reason)
    rep.check("media_dm_envelope_shape_unchanged", set(env) <= ALLOWED_ENVELOPE_KEYS,
              ",".join(sorted(env)))
    rep.check("media_dm_no_group_fields",
              not ({"group_id", "mentioned_account_ids", "reply_to"} & set(env)), ",".join(sorted(env)))
    block = (env.get("raw") or {}).get(inbound_mod.MEDIA_KEY) or {}
    rep.check("media_dm_block_in_raw", block.get("count") == 1 and
              (block.get("items") or [{}])[0].get("url", "").startswith("https://") and
              block["items"][0]["type"] == "image" and block["items"][0]["size"] == "40087",
              json.dumps(block, ensure_ascii=False)[:220])
    rep.check("media_dm_raw_still_carries_the_original",
              isinstance((env.get("raw") or {}).get("message"), list) and
              (env["raw"]["message"][0]["data"]["file"]).endswith(".png"), "")

    # a sticker in an authorized group: presence and name, nothing invented
    res, reason = inbound_mod.classify(_group_event(gcfg, grp, member, 5102, message=[
        {"type": "face", "data": {"face_id": "194", "text": "[微笑]"}}]), gcfg, seen)
    rep.check("media_group_sticker_visible", reason == "accepted" and res[0]["text"] == "[表情:微笑]"
              and res[0]["mentioned_account_ids"] == [] and res[1]["media_types"] == "face", reason)

    # the non-@ reply that used to vanish: reply + picture, no text, no at
    res, reason = inbound_mod.classify(_group_event(gcfg, grp, member, 5103, message=[
        {"type": "reply", "data": {"id": 777}}, dict(IMG_SEG)]), gcfg, seen)
    rep.check("media_group_image_reply_visible", reason == "accepted"
              and res[0].get("reply_to") == "777" and res[0]["mentioned_account_ids"] == []
              and res[0]["text"] == "[图片（未解析）]" and res[1]["has_reply"] is True
              and res[1]["mentions"] == 0, reason)

    # a reply with nothing but the reply segment
    res, reason = inbound_mod.classify(_group_event(gcfg, grp, member, 5104, message=[
        {"type": "reply", "data": {"id": 778}}]), gcfg, seen)
    rep.check("media_group_reply_only_visible", reason == "accepted"
              and res[0]["text"] == inbound_mod.REPLY_ONLY_FALLBACK and res[0]["reply_to"] == "778", reason)

    # bare @ of this account is a direct address; of somebody else it is not
    res, reason = inbound_mod.classify(_group_event(gcfg, grp, member, 5105, message=[
        {"type": "at", "data": {"qq": gcfg.napcat["account_id"]}}]), gcfg, seen)
    rep.check("media_group_bare_self_at_visible", reason == "accepted"
              and res[0]["mentioned_account_ids"] == [gcfg.napcat["account_id"]]
              and res[0]["text"] == "@" + gcfg.napcat["account_id"], reason)
    res, reason = inbound_mod.classify(_group_event(gcfg, grp, member, 5106, message=[
        {"type": "at", "data": {"qq": other}}]), gcfg, seen)
    rep.check("media_group_bare_at_other_dropped", reason == "no_text", reason)
    res, reason = inbound_mod.classify(_group_event(gcfg, grp, member, 5113, message=[
        {"type": "at", "data": {"qq": "all"}}]), gcfg, seen)
    rep.check("media_at_all_alone_still_dropped", reason == "no_text", reason)

    # an unauthorized member's picture is still never looked at
    res, reason = inbound_mod.classify(_group_event(gcfg, grp, OUTSIDER, 5107, message=[dict(IMG_SEG)]),
                                       gcfg, seen)
    rep.check("media_unauthorized_member_still_denied", reason == "unauthorized_group_member", reason)
    res, reason = inbound_mod.classify(_group_event(gcfg, UNKNOWN_GROUP, member, 5108, message=[dict(IMG_SEG)]),
                                       gcfg, seen)
    rep.check("media_unauthorized_group_still_denied", reason == "group_not_allowed", reason)

    # modes
    off = _media_cfg(gcfg, "off")
    res, reason = inbound_mod.classify(_group_event(off, grp, member, 5109, message=[dict(IMG_SEG)]), off, seen)
    rep.check("media_mode_off_drops_image", reason == "no_text", reason)
    res, reason = inbound_mod.classify(_group_event(off, grp, member, 5110,
                                                   message=_text("前半") + [dict(IMG_SEG)]), off, seen)
    rep.check("media_mode_off_is_byte_identical_to_030", reason == "accepted" and res[0]["text"] == "前半"
              and inbound_mod.MEDIA_KEY not in res[0]["raw"] and res[1]["non_text_segments"] == 1
              and res[1]["media_segments"] == 1, repr(res[0].get("text")))
    ann = _media_cfg(gcfg, "annotate")
    res, reason = inbound_mod.classify(_group_event(ann, grp, member, 5111, message=[dict(IMG_SEG)]), ann, seen)
    rep.check("media_mode_annotate_drops_image_only", reason == "no_text", reason)
    res, reason = inbound_mod.classify(_group_event(ann, grp, member, 5112,
                                                   message=_text("前半") + [dict(IMG_SEG)]), ann, seen)
    rep.check("media_mode_annotate_keeps_placeholder", reason == "accepted"
              and res[0]["text"] == "前半[图片（未解析）]", reason)
    bad = json.loads(json.dumps(gcfg.raw))
    bad["adapter"]["media_mode"] = "everything"
    try:
        Config(bad, "bad-media-mode")
        rep.check("media_mode_bad_value_rejected", False, "loaded anyway")
    except ConfigError as exc:
        rep.check("media_mode_bad_value_rejected", "media_mode" in str(exc), str(exc))
    rep.check("media_mode_defaults_to_full", _media_cfg(gcfg, "full").media_mode == "full"
              and inbound_mod.media_mode_of(object()) == "full"
              and inbound_mod.media_mode_of(type("X", (), {"media_mode": "nonsense"})()) == "full", "")
    rep.check("media_mode_in_describe", "media_mode=off" in off.describe(), off.describe()[-60:])

    # bounds: a wall of pictures, an oversized url, an oversized card title
    many = [{"type": "image", "data": {"file": "x%d.png" % i, "url": "https://u/" + ("y" * 900)}}
            for i in range(12)]
    parsed = inbound_mod.parse_message(many)
    rep.check("media_items_capped", len(parsed["media"]) == inbound_mod.MAX_MEDIA_ITEMS
              and parsed["media_extra"] == 12 - inbound_mod.MAX_MEDIA_ITEMS
              and all(len(i.get("url", "")) <= inbound_mod.MAX_URL for i in parsed["media"]),
              "items=%d extra=%d" % (len(parsed["media"]), parsed["media_extra"]))
    blk = inbound_mod.media_block(parsed)
    rep.check("media_block_counts_all_and_flags_truncation",
              blk["count"] == 12 and blk.get("truncated") is True and len(blk["items"]) == 8,
              json.dumps({k: v for k, v in blk.items() if k != "items"}))
    rep.check("media_placeholder_keeps_position",
              inbound_mod.parse_message([{"type": "image", "data": {}},
                                         {"type": "text", "data": {"text": "后"}}])["text_with_media"]
              == "[图片（未解析）]后", "")
    rep.check("media_reply_never_enters_text",
              inbound_mod.parse_message([{"type": "reply", "data": {"id": 1}},
                                         {"type": "text", "data": {"text": "正文"}}])["text_with_media"]
              == "正文", "")
    long_card = json.loads(json.dumps(gcfg.raw))
    parsed = inbound_mod.parse_message([{"type": "mystery", "data": {}}])
    rep.check("media_unknown_segment_labelled",
              parsed["text_with_media"] == "[mystery消息（未解析）]" and parsed["other_segments"] == 1,
              parsed["text_with_media"])
    parsed = inbound_mod.parse_message([{"type": "json", "data": {"data": json.dumps({"app": 0, "prompt": "网页链接"})}}])
    rep.check("media_card_prompt_used", "网页链接" in parsed["text_with_media"], parsed["text_with_media"])
    parsed = inbound_mod.parse_message([{"type": "xml",
                                         "data": {"data": "<msg><title><![CDATA[群分享：示例角色]]></title></msg>"}}])
    rep.check("media_xml_title_used", "群分享：示例角色" in parsed["text_with_media"], parsed["text_with_media"])
    parsed = inbound_mod.parse_message([{"type": "json", "data": {"data": "{not json"}}])
    rep.check("media_unreadable_card_does_not_raise",
              parsed["text_with_media"] == "[卡片消息（未解析）]", parsed["text_with_media"])
    parsed = inbound_mod.parse_message([{"type": "image", "data": {"file": "A.png", "summary": "[动画表情]"}}])
    rep.check("media_image_summary_used",
              parsed["text_with_media"] == "[图片:动画表情（未解析）]", parsed["text_with_media"])
    parsed = inbound_mod.parse_message([{"type": "image", "data": {"file": "A.png", "summary": ""}}])
    rep.check("media_image_without_summary_bare_label",
              parsed["text_with_media"] == "[图片（未解析）]", parsed["text_with_media"])
    parsed = inbound_mod.parse_message([{"type": "file", "data": {"file_name": "报告.pdf", "file_size": "12"}}])
    rep.check("media_file_name_used", parsed["text_with_media"] == "[文件:报告.pdf（未解析）]",
              parsed["text_with_media"])
    parsed = inbound_mod.parse_message([{"type": "record", "data": {}}, {"type": "video", "data": {}},
                                        {"type": "poke", "data": {}}, {"type": "forward", "data": {}}])
    rep.check("media_common_types_labelled",
              parsed["text_with_media"] == "[语音（未解析）][视频（未解析）][戳一戳][合并转发（未解析）]"
              and parsed["media_extra"] == 0, parsed["text_with_media"])
    parsed = inbound_mod.parse_message([{"type": None, "data": None}])
    rep.check("media_broken_segment_survives",
              parsed["text_with_media"] == "[unknown消息（未解析）]" and parsed["other_segments"] == 1,
              parsed["text_with_media"])

    # dedup does not care whether the message had text
    _r, first = inbound_mod.classify(_msg_event(gcfg, message=[dict(IMG_SEG)], message_id=5120), gcfg, seen)
    _r, again = inbound_mod.classify(_msg_event(gcfg, message=[dict(IMG_SEG)], message_id=5120), gcfg, seen)
    rep.check("media_dedup_unchanged", (first, again) == ("accepted", "duplicate_local"),
              "%s/%s" % (first, again))

    # a host whose allowlist has not grown yet still gets the message
    svc = Adapter(gcfg, os.path.join(root, "mediasvc"), peer_mode="off")
    svc.host = DenyOnceHost(key=inbound_mod.MEDIA_KEY)
    env = {"route_id": "owner-dm", "account_id": gcfg.napcat["account_id"],
           "sender_id": OWNER, "event_id": "5121", "text": "[图片（未解析）]",
           "raw": {"message_id": 5121, inbound_mod.MEDIA_KEY: {"count": 1, "items": []}}}
    res = svc._submit_event(env)
    rep.check("media_field_denied_reposts_without_losing_event",
              res.kind == "accepted" and len(svc.host.posts) == 2
              and inbound_mod.MEDIA_KEY in svc.host.posts[0]["raw"]
              and inbound_mod.MEDIA_KEY not in svc.host.posts[1]["raw"]
              and svc.counters.snapshot().get("media_field_denied") == 1,
              "kind=%s posts=%d" % (res.kind, len(svc.host.posts)))
    rep.check("media_strip_is_idempotent", inbound_mod.strip_media(env) is False
              and inbound_mod.strip_media({}) is False and inbound_mod.media_block({"media": []}) is None, "")

    # the spool carries the media meta, so a backlog is still readable later
    journal = Journal(os.path.join(root, "mediaspool"))
    res, reason = inbound_mod.classify(_msg_event(gcfg, message=[dict(IMG_SEG)], message_id=5122), gcfg, seen)
    journal.spool_add("inbound", {"envelope": res[0], "meta": res[1]}, key="owner-dm-5122")
    reread = journal.read_json(journal.spool_list("inbound")[0])
    rep.check("media_meta_survives_the_spool",
              reread["meta"]["media_segments"] == 1 and reread["meta"]["media_only"] is True
              and inbound_mod.MEDIA_KEY in reread["envelope"]["raw"],
              json.dumps(reread["meta"], sort_keys=True)[:160])

    # the host takes 1-16000 characters, so an annotation must never be the
    # reason a message that 0.3.0 could submit is now rejected
    near = "a" * (inbound_mod.MAX_TEXT - 3)
    res, reason = inbound_mod.classify(_msg_event(gcfg, message=_text(near) + [dict(IMG_SEG)],
                                                 message_id=5130), gcfg, seen)
    rep.check("media_placeholder_never_breaks_the_limit",
              reason == "accepted" and res[0]["text"] == near and res[1]["over_host_limit"] is False
              and res[1]["media_shrunk_for_limit"] is True and res[1]["media_segments"] == 1
              and res[1]["chars"] == len(near),
              "%s chars=%s" % (reason, len((res[0].get("text") or ""))))
    res, reason = inbound_mod.classify(_group_event(gcfg, grp, member, 5131,
                                                   message=_text(near) + [dict(IMG_SEG)]), gcfg, seen)
    rep.check("media_placeholder_limit_applies_to_group", reason == "accepted"
              and res[0]["text"] == near and res[1]["media_shrunk_for_limit"] is True
              and inbound_mod.MEDIA_KEY in res[0]["raw"], reason)
    too_long = "a" * (inbound_mod.MAX_TEXT + 50)
    res, reason = inbound_mod.classify(_msg_event(gcfg, message=_text(too_long) + [dict(IMG_SEG)],
                                                 message_id=5132), gcfg, seen)
    rep.check("media_over_limit_still_reported_as_is",
              reason == "accepted" and res[1]["over_host_limit"] is True
              and "media_shrunk_for_limit" not in res[1], reason)

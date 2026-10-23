"""Wiring: WS reader -> durable spool -> one lane per conversation -> host, host outbox -> send.

The /event callback only writes a spool file.  Submission to the host happens on
other threads, so a slow or unreachable host cannot stall the WebSocket reader,
and a spool backlog cannot lose an authorized message.  Each conversation's lines
go to the host in their order from a lane of their own (ADR-095): a line that is
slow to prepare (a voice, a forward, a lookup) or does not go in holds only its
own conversation.
"""
import json
import os
import signal
import threading
import time

from . import forward as forward_mod
from . import inbound as inbound_mod
from . import mutes as mutes_mod
from . import notices as notices_mod
from .catchup import Catchup
from .media_keys import MediaKeys
from .members import Members
from .hostapi import CAPABILITIES, HostApi, file_capability
from .journal import Counters, Journal
from .onebot import OneBot
from .outbound import Outbound
from .peers import PeerDirectory
from .selfrole import SelfRoles
from . import voice as voice_mod

STATUS_EVERY = 60
HEALTH_EVERY = 5
INBOUND_LANES = 8             # conversations whose lines are prepared and posted at once (ADR-095)
WHOLE_HOST = ("HOST_RECONFIGURING", "HOST_STOPPING", "HOST_DATABASE_UNAVAILABLE")   # the host's 503 names
LANE_BATCH = 20               # lines a lane posts before it gives its place to a conversation that waits
HOST_ERROR_TRIES = 5          # a line that fails on its own is tried this often, then set aside
RETRY_WAITS = (2, 5, 15, 30, 60)   # seconds before a conversation's first line is tried again; the last repeats


def utc_stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _echo_shape(event):
    """Segment types and at targets of a message the platform echoed back.

    The echo is the platform own view of a message we sent, so it is what
    an `at` promotion gets checked against in real traffic.  Metadata only.
    """
    message = event.get("message")
    if not isinstance(message, list):
        return "raw_string", "-"
    types, ats = [], []
    for seg in message:
        if not isinstance(seg, dict):
            continue
        types.append(str(seg.get("type")))
        if seg.get("type") == "at":
            data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
            ats.append(str(data.get("qq")))
    return (",".join(types) or "-"), (",".join(ats) or "-")


class Adapter:
    def __init__(self, cfg, data_dir, claim_wait=20, ack_timeout=15.0, verify=True, verify_delay=0.8,
                 peer_mode="full"):
        self.cfg = cfg
        self.data_dir = data_dir
        self.journal = Journal(data_dir)
        self.counters = Counters()
        self.seen = inbound_mod.SeenLRU(512)
        self.host = HostApi(cfg.host)
        self.onebot = OneBot(cfg.napcat, self.counters, self.on_event, log=self.log)
        self.out = Outbound(cfg, self.host, self.onebot, self.journal, self.counters, log=self.log,
                            ack_timeout=ack_timeout, verify=verify, verify_delay=verify_delay)
        self.onebot.on_late_ack = self.out.on_late_ack
        # who is talking, and whether a rename changed the person: observation
        # only, on the submitter thread, never in the way of an inbound turn
        self.peers = None
        if peer_mode != "off":
            self.peers = PeerDirectory(data_dir, log=self.log, counters=self.counters,
                                       inject=(peer_mode == "full"))
        # her own role in each group (owner/admin/member), carried to the host as raw.asuna_self
        self.self_roles = SelfRoles(cfg.napcat["account_id"], counters=self.counters)
        # the messages missed while this adapter or its event socket was down (catchup.py)
        self.catchup = Catchup(cfg, data_dir, self.onebot, self.on_event, self.counters, log=self.log)
        # who is in each admitted group, posted to the host when it changed (members.py)
        self.members = Members(cfg, data_dir, self.onebot, self.host, self.counters, log=self.log)
        # the current picture-link keys, posted to the host every few minutes (media_keys.py)
        self.media_keys = MediaKeys(self.onebot, self.host, self.counters, log=self.log)
        # her own mute in each admitted group: notices about her, refused sends, a look at start (mutes.py)
        self.mutes = mutes_mod.Mutes(cfg, data_dir, self.onebot, self.host, self.counters, self.members.groups,
                                     log=self.log)
        self.out.on_muted = self.mutes.look_now
        # notices and requests: every kind projected and counted, the shown ones posted (notices.py)
        self.notice_counts = notices_mod.Counts(data_dir)
        self.home_notices = notices_mod.HomePoster(cfg, self.onebot, self.host, self.counters, log=self.log)
        self.onebot.on_up = self._on_up
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.claim_wait = claim_wait
        self._tries = {}              # spool path -> times the host answered it with an error
        self._attempts = {}           # spool path -> times it did not go in (its backoff)
        self._lanes = {}              # route id -> the lane posting that conversation's lines
        self._spooled = {}            # spool path -> its route id, each file read once (submit_pending)
        self._tried_at = {}           # spool path -> when its last try was posted
        self._lane_started = {}       # route id -> when a lane for it last started (submit_pending's order)
        self._last_in = 0.0           # when a line last went in, any conversation
        self._lanes_lock = threading.Lock()
        self.retry_waits = RETRY_WAITS
        self.lane_batch = LANE_BATCH
        self.inbound_lanes = INBOUND_LANES
        self._last_status = 0.0
        self.identity = None
        # what she may send through reply (ADR-064 phase 2); a poke or reaction NapCat refuses comes back to her
        # what this bridge carries, told to the host on every claim (ADR-079: the pointer family too; ADR-093: it
        # settles each voice before its line)
        self.capabilities = list(CAPABILITIES) + [file_capability(cfg.napcat["max_file_bytes"]),
                                                  "react", "poke", "quote", "quote_in", "react_in", "recall", "voice_in"]

    def log(self, msg):
        print("%s %s" % (utc_stamp(), msg), flush=True)

    def _on_up(self, path, gap):
        if path == "/event" and gap is not None:
            self.catchup.request("reconnect")
            self.mutes.sweep("reconnect")

    # ---- inbound (WS reader thread) ------------------------------------
    def on_event(self, event):
        if isinstance(event, dict) and event.get("post_type") not in (None, "message"):
            return self.on_notice(event)
        result, reason = inbound_mod.classify(event, self.cfg, self.seen)
        if reason == "accepted":
            envelope, meta = result
            self.catchup.note(meta["route_id"], event)
            # the spool key carries the route: one platform message_id seen in a
            # group and in the private chat are two different items
            self.journal.spool_add("inbound", {"envelope": envelope, "meta": meta},
                                   key="%s-%s" % (envelope["route_id"], envelope["event_id"]))
            self.counters.inc("inbound_spooled")
            if meta.get("media_only"):
                # an inbound turn that carried no text at all: a picture, a
                # sticker, a bare reply into a thread
                self.counters.inc("inbound_media_only")
            self.counters.set("last_event_at", round(time.time(), 3))
            self.log("INBOUND_SPOOLED event_id=%s route=%s scene=%s group=%s chars=%d non_text_segments=%d"
                     " mentions=%d at_all=%d reply=%s over_host_limit=%s media=%d media_types=%s media_only=%s"
                     % (envelope["event_id"], meta["route_id"], meta.get("scene"), meta.get("group_id", "-"),
                        meta["chars"], meta["non_text_segments"], meta.get("mentions", 0),
                        meta.get("at_all_segments", 0), 1 if meta.get("has_reply") else 0, meta["over_host_limit"],
                        meta.get("media_segments", 0), meta.get("media_types", "-"),
                        bool(meta.get("media_only"))))
            self.wake.set()
            return
        self.counters.inc("inbound_" + reason)
        if reason == "self_echo" and event.get("message_type") == "group":
            # our own group message coming back off the platform: still dropped,
            # but the echoed segment list is independent evidence of what the
            # platform stored for a promoted @qq:<digits> marker
            types, ats = _echo_shape(event)
            self.log("SELF_ECHO group=%s message_id=%s segments=%s at_targets=%s"
                     % (event.get("group_id"), event.get("message_id"), types, ats))
            return
        if reason in ("unauthorized_sender", "unauthorized_group_member", "group_not_allowed",
                      "group_route_missing", "no_text", "wrong_self", "duplicate_local", "bad_shape"):
            self.log("INBOUND_IGNORED reason=%s post_type=%s message_type=%s group_id=%s user_id=%s message_id=%s"
                     % (reason, event.get("post_type"), event.get("message_type"), event.get("group_id"),
                        event.get("user_id"), event.get("message_id")))

    def on_notice(self, event):
        """A notice, request or meta event: counted by kind; her own mute to its state; a shown kind posted."""
        kind, known = notices_mod.kind_of(event)
        muted = mutes_mod.notice_body(event, self.cfg)
        if muted is not None:
            # a state report, not a chat line: posted from the mutes thread, never spooled as a turn
            self.notice_counts.add(kind, "own_state")
            self.counters.inc("inbound_own_mute_notice")
            self.mutes.notice(muted)
            return
        proj = notices_mod.project(event, str(self.cfg.napcat["account_id"])) if known else None
        if proj is None or proj["kind"] not in notices_mod.SHOWN:
            self.notice_counts.add(proj["kind"] if proj else kind,
                                   "not_shown" if proj else "not_projected" if known else "unknown")
            self.counters.inc("inbound_nonmessage")
            return
        kind = proj["kind"]
        if proj["where"] == "home":
            if proj.get("group_id") and kind != "request_invite" and self.cfg.route_for_group(proj["group_id"]) is None:
                self.notice_counts.add(kind, "group_not_allowed")
                return
            self.notice_counts.add(kind, "home")
            self.home_notices.put(proj, event)
            return
        envelope, why = notices_mod.envelope(proj, event, self.cfg, self.seen)
        if envelope is None:
            self.notice_counts.add(kind, why)
            self.counters.inc("inbound_" + why)
            return
        self.notice_counts.add(kind, "posted")
        self.journal.spool_add("inbound", {"envelope": envelope, "meta": {"route_id": envelope["route_id"],
                                                                         "notice": kind}},
                               key="%s-%s" % (envelope["route_id"], envelope["event_id"]))
        self.counters.inc("inbound_notice_spooled")
        self.log("NOTICE_SPOOLED kind=%s route=%s event_id=%s" % (kind, envelope["route_id"], envelope["event_id"]))
        self.wake.set()

    # ---- inbound lanes (ADR-095) -------------------------------------------
    def submit_pending(self):
        """Hand each conversation with lines in the spool to a lane of its own, at most INBOUND_LANES at once, the
        conversation with the oldest line first. A lane posts its conversation's lines one at a time, in their order;
        a line that is slow or does not go in holds only its own conversation. Each spool file is read once here (its
        route is remembered), so a lane can remove it without a reader in the way. Returns how many lanes started."""
        listed = self.journal.spool_list("inbound")
        current = set(listed)
        for path in [path for path in self._spooled if path not in current]:
            del self._spooled[path]
        routes = {}
        for path in listed:
            route = self._spooled.get(path)
            if route is None:
                try:
                    blob = self.journal.read_json(path)
                except FileNotFoundError:
                    continue                  # posted by its lane meanwhile
                except ValueError:
                    blob = None               # not JSON
                except OSError:
                    continue                  # held open a moment (Windows): the next pass reads it
                if not isinstance(blob, dict) or not isinstance(blob.get("envelope"), dict):
                    self.journal.spool_move(path, "inbound_unreadable.jsonl", {"reason": "unreadable"})
                    continue
                route = self._spooled[path] = str(blob["envelope"].get("route_id") or "")
            routes.setdefault(route, []).append(path)
        started = []
        with self._lanes_lock:
            # A conversation that never had a lane, or had one longest ago, first; among equals the oldest line first.
            for route in sorted(routes, key=lambda route: self._lane_started.get(route, 0.0)):
                if route in self._lanes or len(self._lanes) >= self.inbound_lanes:
                    continue
                lane = threading.Thread(target=self._lane, args=(route, routes[route][:self.lane_batch]),
                                        name="inbound-" + route[:40], daemon=True)
                self._lanes[route] = lane
                self._lane_started[route] = time.monotonic()
                started.append(lane)
        for lane in started:
            lane.start()
        return len(started)

    def _lane(self, route, paths):
        """One conversation's lines, in order: each is tried until it is settled (in, set aside or gone); the next
        waits for it. After LANE_BATCH lines the lane ends and the dispatcher starts it again behind the
        conversations that wait. A line still waiting at shutdown stays in the spool for the next start."""
        try:
            for path in paths:
                while True:
                    try:
                        done = self._submit_one(path)
                    except Exception as exc:
                        done = self._lane_error(route, path, exc)
                    if done:
                        break
                    if self.stop.is_set():
                        return
                    tried = self._attempts.get(path, 1)
                    self.stop.wait(self.retry_waits[min(tried, len(self.retry_waits)) - 1])
        finally:
            with self._lanes_lock:
                self._lanes.pop(route, None)
            self.wake.set()

    @staticmethod
    def _host_away(res):
        """Whether an answer is about the host, not this line: no answer, the whole host unavailable (503), or this
        adapter's key no longer taken (the host's settings changed). Such answers wait; they don't count."""
        if res.kind == "retry" and (res.code is None or res.code == 503):
            return True
        error = res.obj.get("error") if isinstance(res.obj, dict) else None
        return res.kind == "reject" and res.code == 403 and error == "CHANNEL_AUTH_REQUIRED"

    def _submit_one(self, path):
        """Prepare one spooled line once (the prepared line is written back), then post it. True when it is settled
        (in, set aside or gone); False when it waits for another try (ADR-095 §5.4):
        - any 2xx settles it: accepted, a duplicate, or held, dropped or passed over by the host;
        - an answer about the host (`_host_away`) never counts while other lines get in meanwhile; once they do, the
          host is there and this line is the one not getting in, so it counts;
        - any other 5xx counts; HOST_ERROR_TRIES counted tries set the line aside (`inbound_failed.jsonl`);
        - a 4xx refuses it (`inbound_rejected.jsonl`), after the one repost without the injected blocks."""
        try:
            blob = self.journal.read_json(path)
        except FileNotFoundError:
            return True
        except ValueError:
            blob = None
        except OSError:
            return False                      # held open a moment: tried again after its wait
        if not isinstance(blob, dict) or not isinstance(blob.get("envelope"), dict):
            self.journal.spool_move(path, "inbound_unreadable.jsonl", {"reason": "unreadable"})
            return True
        envelope = blob["envelope"]
        if not blob.get("prepared"):
            self._prepare(envelope)
            # A retry posts what was prepared: the platform is not asked again (a voice it has cleared is not
            # fetched twice) and a lookup is counted once. Not when a voice could not be handed to the host: that
            # is the host's state, so the next try fetches and hands it over again.
            if not voice_mod.host_refused(envelope):
                self.journal.write_json(path, dict(blob, envelope=envelope, prepared=True))
        started = time.monotonic()
        res = self._post(envelope)
        where = "event_id=%s route=%s" % (envelope.get("event_id"), envelope.get("route_id"))
        if res.kind in ("accepted", "duplicate", "ok"):
            obj = res.obj if isinstance(res.obj, dict) else {}
            result = res.kind if res.kind != "ok" else str(obj.get("status") or "ok")
            self.counters.inc("inbound_" + (res.kind if res.kind != "ok" else "settled"))
            self.journal.append("inbound_sent.jsonl",
                                {"ts": utc_stamp(), "event_id": envelope.get("event_id"),
                                 "route_id": envelope.get("route_id"), "result": result,
                                 "episode_id": obj.get("episode_id"), "http": res.code})
            self.journal.spool_remove(path)
            self._settled(path)
            self._last_in = time.monotonic()
            self.log("INBOUND_%s %s episode=%s http=%s" % (result.upper(), where, obj.get("episode_id"), res.code))
            return True
        self._attempts[path] = self._attempts.get(path, 0) + 1
        if self._host_away(res):
            previous, self._tried_at[path] = self._tried_at.get(path), started
            said = res.error or (res.obj.get("error") if isinstance(res.obj, dict) else None)
            # A state the host names (applying settings, stopping, its database) and a key it does not take are the
            # host's whatever else happens. No answer, or an unnamed 503 (an older host), is this line's only when
            # other lines went in since its previous try.
            if said in WHOLE_HOST or said == "CHANNEL_AUTH_REQUIRED" or previous is None or self._last_in <= previous:
                self.counters.inc("inbound_waits")
                self.log("INBOUND_WAIT %s http=%s error=%s (the host is not taking lines)" % (where, res.code, said))
                return False
            return self._count(path, envelope, res, "not_taken_while_others_go_in")
        if res.kind == "retry":
            return self._count(path, envelope, res, "host_error")
        self.journal.spool_move(path, "inbound_rejected.jsonl",
                                {"reason": "host_rejected", "http": res.code, "body": res.obj})
        self._settled(path)
        self.log("INBOUND_REJECTED %s http=%s body=%s"
                 % (where, res.code, json.dumps(res.obj, ensure_ascii=False)[:300]))
        return True

    def _count(self, path, envelope, res, reason):
        """One counted try of a line that fails on its own; the last one sets it aside."""
        self.counters.inc("inbound_retries")
        tries = self._tries.get(path, 0) + 1
        self._tries[path] = tries
        where = "event_id=%s route=%s" % (envelope.get("event_id"), envelope.get("route_id"))
        if tries >= HOST_ERROR_TRIES:
            self.journal.spool_move(path, "inbound_failed.jsonl",
                                    {"reason": reason, "tries": tries, "http": res.code, "body": res.obj})
            self._settled(path)
            self.log("INBOUND_FAILED %s tries=%d http=%s reason=%s" % (where, tries, res.code, reason))
            return True
        self.log("INBOUND_RETRY %s tries=%d http=%s reason=%s" % (where, tries, res.code, reason))
        return False

    def _lane_error(self, route, path, exc):
        """A try that raised in this adapter (a journal write, a lookup's bug): counted like a failed try, with the
        same backoff, and the line set aside after HOST_ERROR_TRIES of them."""
        self.counters.inc("submitter_error")
        self._attempts[path] = self._attempts.get(path, 0) + 1
        tries = self._tries.get(path, 0) + 1
        self._tries[path] = tries
        self.log("SUBMITTER_ERROR route=%s tries=%d type=%s" % (route, tries, type(exc).__name__))
        if tries < HOST_ERROR_TRIES:
            return False
        try:
            self.journal.spool_move(path, "inbound_failed.jsonl",
                                    {"reason": "adapter_error", "tries": tries, "error": type(exc).__name__})
        except Exception:
            return False
        self._settled(path)
        return True

    def _settled(self, path):
        self._tries.pop(path, None)
        self._attempts.pop(path, None)
        self._tried_at.pop(path, None)

    def _submit_event(self, envelope):
        """Prepare one authorized event and post it (the self-test's way in; a lane prepares a line once and posts
        it as often as it takes)."""
        self._prepare(envelope)
        return self._post(envelope)

    def _prepare(self, envelope):
        """Everything a line asks the platform for before it goes to the host: the peer profile inside `raw`, the
        people it mentions, a merged forward, her own role, its voices.

        Each lookup is bounded and optional: if the platform does not answer, the message still goes to the host with
        whatever is already known.
        """
        if self.peers is not None:
            try:
                profile = self.peers.observe(envelope, self.onebot)
            except Exception as exc:
                profile = None
                self.counters.inc("peer_error")
                self.log("PEER_ERROR type=%s" % type(exc).__name__)
            if profile:
                self.counters.inc("peer_enriched")
                self.log("PEER person=%s scene=%s group=%s display=%r nick=%r card=%r role=%s"
                         " source=%s verified=%s msgs=%d changed=%s"
                         % (profile["person_id"], profile["scene"], profile.get("group_id", "-"),
                            profile["display"], profile["nickname"], profile.get("card", "-"),
                            profile["role"], profile["source"], profile["verified"],
                            profile["seen_messages"], ",".join(profile.get("changed") or []) or "-"))
        if self.peers is not None and envelope.get("group_id") and envelope.get("mentioned_account_ids"):
            try:
                mentioned = self.peers.observe_mentions(envelope, self.onebot)
            except Exception as exc:
                mentioned = []
                self.counters.inc("peer_mention_error")
                self.log("PEER_MENTION_ERROR type=%s" % type(exc).__name__)
            for profile in mentioned:
                self.counters.inc("peer_mention_enriched")
                self.log("PEER_MENTION person=%s group=%s display=%r verified=%s"
                         % (profile["person_id"], profile.get("group_id", "-"), profile["display"],
                            profile["verified"]))
        try:
            # a merged forward's messages, inline or fetched once, bounded (forward.py)
            forward_mod.attach(envelope, lambda action, params: self.onebot.api_call(
                action, params, timeout=forward_mod.TIMEOUT, meta={"forward": envelope.get("event_id")}), log=self.log)
        except Exception as exc:
            self.counters.inc("forward_errors")
            self.log("FORWARD_ERROR type=%s" % type(exc).__name__)
        if envelope.get("group_id"):
            try:
                self.self_roles.attach(envelope, self.onebot)
            except Exception as exc:
                self.counters.inc("self_role_errors")
                self.log("SELF_ROLE_ERROR type=%s" % type(exc).__name__)
        try:
            # Its voices first: fetched from NapCat and settled by the host, so the line arrives with its words, in
            # its place among the lines (voice.py).
            voice_mod.settle(envelope, self.onebot, self.host, self.counters, log=self.log)
        except Exception as exc:
            self.counters.inc("voice_errors")
            self.log("VOICE_ERROR event_id=%s type=%s" % (envelope.get("event_id"), type(exc).__name__))
    def _post(self, envelope):
        """Post one prepared event. If the host ever refuses the injected block, the same event is posted once more
        without it, so an observation can never eat a turn."""
        res = self.host.post_event(envelope)
        if res.kind == "reject" and not self._host_away(res):
            # any 4xx with an injected block on board gets one clean retry: the
            # second post is byte-for-byte the envelope this adapter sent before
            # the observation existed, so an observation cannot eat a turn
            repost = False
            if self.peers is not None:
                if self.peers.denied(res.obj):
                    self.log("PEER_FIELD_DENIED event_id=%s host refused the injected block"
                             % envelope.get("event_id"))
                if self.peers.strip(envelope):
                    self.counters.inc("peer_field_denied")
                    self.log("PEER_REPOST event_id=%s resent without the injected block"
                             % envelope.get("event_id"))
                    repost = True
            if inbound_mod.strip_media(envelope):
                self.counters.inc("media_field_denied")
                self.log("MEDIA_REPOST event_id=%s resent without the media block"
                         % envelope.get("event_id"))
                repost = True
            if repost:
                res = self.host.post_event(envelope)
        return res

    def _submitter_loop(self):
        while not self.stop.is_set():
            self.wake.wait(2.0)
            self.wake.clear()
            if self.stop.is_set():
                break
            try:
                self.submit_pending()
            except Exception as exc:
                self.counters.inc("submitter_error")
                self.log("SUBMITTER_ERROR type=%s" % type(exc).__name__)

    # ---- health/status --------------------------------------------------
    def health_snapshot(self):
        snap = self.counters.snapshot()
        snap.update({
            "pid": os.getpid(),
            "utc": utc_stamp(),
            "uptime_seconds": round(time.time() - self.journal.started, 1),
            "ws_event_up": self.onebot.event_up,
            "ws_api_up": self.onebot.api_up,
            "spool_inbound": len(self.journal.spool_list("inbound")),
            "spool_receipts": len(self.journal.spool_list("receipts")),
            "pending_echo": self.onebot.pending_count(),
            "group_routes": sum(1 for r in self.cfg.routes.values() if r.message_type == "group"),
            "identity": self.identity,
            "peers": self.peers.summary() if self.peers is not None else None,
            "notices": self.notice_counts.summary(),
        })
        return snap

    def _health_loop(self):
        while not self.stop.wait(HEALTH_EVERY):
            try:
                self.journal.write_health(self.health_snapshot())
            except Exception as exc:
                self.log("HEALTH_ERROR type=%s" % type(exc).__name__)

    def maybe_status(self, force=False):
        now = time.time()
        if not force and now - self._last_status < STATUS_EVERY:
            return
        self._last_status = now
        snap = self.health_snapshot()
        self.log("STATUS ws_event=%s ws_api=%s spool_inbound=%d spool_receipts=%d pending_echo=%d group_routes=%d counters=%s"
                 % ("up" if snap["ws_event_up"] else "down",
                    "up" if snap["ws_api_up"] else "down",
                    snap["spool_inbound"], snap["spool_receipts"], snap["pending_echo"], snap["group_routes"],
                    json.dumps({k: v for k, v in sorted(snap.items())
                                if k.startswith(("inbound_", "outbox", "send_", "receipt", "frames", "resp", "ws_", "api_", "late_", "peer_", "media_", "attachment_", "catchup_", "members_", "mutes_", "voice_"))},
                               sort_keys=True)))

    # ---- identity -------------------------------------------------------
    def verify_identity(self):
        try:
            resp = self.onebot.api_call("get_login_info", timeout=10)
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "match": False}
        data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
        uid = str(data.get("user_id") or "")
        info = {
            "ok": resp.get("retcode") == 0,
            "user_id": uid,
            "match": uid == self.cfg.napcat["account_id"],
            "nickname_chars": len(str(data.get("nickname") or "")),
        }
        try:
            ver = self.onebot.api_call("get_version_info", timeout=10)
            vdata = ver.get("data") if isinstance(ver.get("data"), dict) else {}
            info["app_name"] = vdata.get("app_name")
            info["app_version"] = vdata.get("app_version")
            info["protocol_version"] = vdata.get("protocol_version")
        except Exception as exc:
            info["version_error"] = type(exc).__name__
        return info

    # ---- main -----------------------------------------------------------
    def run(self):
        self.journal.acquire_lock()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self._on_signal)
            except (ValueError, OSError):
                pass
        self.onebot.start()
        api_up = self.onebot.wait_up("/api", 20)
        self.log("CONFIG %s" % self.cfg.describe())
        for note in self.cfg.notes:
            self.log("CONFIG_NOTE %s" % note)
        if not api_up:
            self.log("FATAL api websocket did not connect within 20s (no identity check possible)")
            self.onebot.stop()
            self.journal.release_lock()
            return 2
        self.identity = self.verify_identity()
        self.log("IDENTITY %s" % json.dumps(self.identity, sort_keys=True))
        if self.peers is not None:
            self.log("PEERS %s" % json.dumps(self.peers.summary(), sort_keys=True))
        if not self.identity.get("match"):
            self.log("FATAL login account does not match adapter.napcat.account_id; refusing to send")
            self.onebot.stop()
            self.journal.release_lock()
            return 3
        if not self.onebot.wait_up("/event", 20):
            self.log("WARN event websocket is down; inbound will start after the retry loop reconnects")
        threading.Thread(target=self._submitter_loop, name="submitter", daemon=True).start()
        threading.Thread(target=self._health_loop, name="health", daemon=True).start()
        threading.Thread(target=self.catchup.loop, args=(self.stop,), name="catchup", daemon=True).start()
        threading.Thread(target=self.members.loop, args=(self.stop,), name="members", daemon=True).start()
        threading.Thread(target=self.media_keys.loop, args=(self.stop,), name="media_keys", daemon=True).start()
        threading.Thread(target=self.mutes.loop, args=(self.stop,), name="mutes", daemon=True).start()
        threading.Thread(target=self.home_notices.loop, args=(self.stop,), name="home_notices", daemon=True).start()
        self.catchup.request("startup")
        self.mutes.sweep("startup")
        self.log("READY pid=%d identity=%s ws_event=%s ws_api=%s spool_inbound=%d spool_receipts=%d"
                 % (os.getpid(), self.identity.get("user_id"),
                    "up" if self.onebot.event_up else "down",
                    "up" if self.onebot.api_up else "down",
                    len(self.journal.spool_list("inbound")), len(self.journal.spool_list("receipts"))))
        self.maybe_status(force=True)
        code = 0
        try:
            self._main_loop()
        except Exception as exc:
            self.counters.inc("main_loop_error")
            self.log("MAIN_LOOP_ERROR type=%s" % type(exc).__name__)
            code = 1
        finally:
            self.stop.set()
            self.onebot.stop()
            try:
                self.journal.write_health(self.health_snapshot())
            except Exception:
                pass
            try:
                self.catchup.flush(force=True)
            except Exception:
                pass
            try:
                self.notice_counts.save()
            except Exception:
                pass
            self.journal.release_lock()
            self.log("SHUTDOWN spool_inbound=%d spool_receipts=%d counters=%s"
                     % (len(self.journal.spool_list("inbound")), len(self.journal.spool_list("receipts")),
                        json.dumps(self.counters.snapshot(), sort_keys=True)))
        return code

    def _main_loop(self):
        while not self.stop.is_set():
            self.onebot.prune()
            try:
                self.out.replay_receipts()
            except Exception as exc:
                self.counters.inc("receipt_replay_error")
                self.log("RECEIPT_REPLAY_ERROR type=%s" % type(exc).__name__)
            res = self.host.claim_outbox(self.claim_wait, supports=self.capabilities)
            if res.kind == "items":
                items = res.obj.get("items") or []
                self.out.handle_item(items[0], stopping=self.stop.is_set())
            elif res.kind == "retry":
                self.counters.inc("outbox_errors")
                self.log("OUTBOX_ERROR %s" % json.dumps({"error": res.error, "http": res.code}))
                self.stop.wait(3)
            self.maybe_status()

    def _on_signal(self, signum, _frame):
        if not self.stop.is_set():
            self.log("SIGNAL %d stopping" % signum)
        self.stop.set()
        self.wake.set()

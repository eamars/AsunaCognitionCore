"""Wiring: WS reader -> durable spool -> host submitter, host outbox -> send.

The /event callback only writes a spool file.  Submission to the host happens on
a separate thread, so a slow or unreachable host cannot stall the WebSocket
reader, and a spool backlog cannot lose an authorized message.
"""
import json
import os
import signal
import threading
import time

from . import inbound as inbound_mod
from .hostapi import HostApi
from .journal import Counters, Journal
from .onebot import OneBot
from .outbound import Outbound
from .peers import PeerDirectory
from .selfrole import SelfRoles

STATUS_EVERY = 60
HEALTH_EVERY = 5
MAX_EVENT_TRIES = 10


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
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.claim_wait = claim_wait
        self._tries = {}
        self._last_status = 0.0
        self.identity = None

    def log(self, msg):
        print("%s %s" % (utc_stamp(), msg), flush=True)

    # ---- inbound (WS reader thread) ------------------------------------
    def on_event(self, event):
        result, reason = inbound_mod.classify(event, self.cfg, self.seen)
        if reason == "accepted":
            envelope, meta = result
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

    # ---- inbound submitter (own thread) --------------------------------
    def submit_pending(self):
        submitted = 0
        for path in self.journal.spool_list("inbound"):
            try:
                blob = self.journal.read_json(path)
            except Exception:
                self.journal.spool_move(path, "inbound_unreadable.jsonl", {"reason": "unreadable"})
                continue
            envelope = blob.get("envelope") or {}
            res = self._submit_event(envelope)
            if res.kind in ("accepted", "duplicate"):
                obj = res.obj if isinstance(res.obj, dict) else {}
                self.counters.inc("inbound_" + res.kind)
                self.journal.append("inbound_sent.jsonl",
                                    {"ts": utc_stamp(), "event_id": envelope.get("event_id"),
                                     "route_id": envelope.get("route_id"), "result": res.kind,
                                     "episode_id": obj.get("episode_id"), "http": res.code})
                self.journal.spool_remove(path)
                self._tries.pop(path, None)
                self.log("INBOUND_%s event_id=%s route=%s episode=%s http=%s"
                         % (res.kind.upper(), envelope.get("event_id"), envelope.get("route_id"),
                            obj.get("episode_id"), res.code))
                submitted += 1
            elif res.kind == "retry":
                tries = self._tries.get(path, 0) + 1
                self._tries[path] = tries
                self.counters.inc("inbound_retries")
                if tries > MAX_EVENT_TRIES:
                    self.journal.spool_move(path, "inbound_failed.jsonl",
                                            {"reason": "host_unreachable_too_long", "tries": tries})
                    self.log("INBOUND_FAILED event_id=%s tries=%d reason=host_unreachable_too_long"
                             % (envelope.get("event_id"), tries))
                else:
                    self.log("INBOUND_RETRY event_id=%s tries=%d error=%s"
                             % (envelope.get("event_id"), tries, res.error or res.code))
            else:
                self.journal.spool_move(path, "inbound_rejected.jsonl",
                                        {"reason": "host_rejected", "http": res.code, "body": res.obj})
                self.log("INBOUND_REJECTED event_id=%s http=%s body=%s"
                         % (envelope.get("event_id"), res.code, json.dumps(res.obj, ensure_ascii=False)[:300]))
        return submitted

    def _submit_event(self, envelope):
        """Post one authorized event, carrying the peer profile inside `raw`.

        The identity lookup is bounded and optional: if the platform does not
        answer, the message still goes to the host with whatever is already
        known.  If a host ever refuses the injected block, the same event is
        posted once more without it, so an observation can never eat a turn.
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
        if envelope.get("group_id"):
            try:
                self.self_roles.attach(envelope, self.onebot)
            except Exception as exc:
                self.counters.inc("self_role_errors")
                self.log("SELF_ROLE_ERROR type=%s" % type(exc).__name__)
        res = self.host.post_event(envelope)
        if res.kind == "reject":
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
                                if k.startswith(("inbound_", "outbox", "send_", "receipt", "frames", "resp", "ws_", "api_", "late_", "peer_", "media_", "attachment_"))},
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
                self.submit_pending()
            except Exception:
                pass
            try:
                self.journal.write_health(self.health_snapshot())
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
            res = self.host.claim_outbox(self.claim_wait)
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

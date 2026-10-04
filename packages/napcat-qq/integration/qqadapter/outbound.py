"""Host outbox -> OneBot send_private_msg / send_group_msg -> receipt.

The outbox target decides the platform action: `dm` keeps the 0.1.0 private
shape (one text segment, unchanged), `group` must pass the configured group
allowlist, may carry one leading `reply` segment when the host supplied
`reply_to`, and encodes the host text into text/at segments.

Group encoding: an explicit `@qq:<digits>` marker written in the character's own
public text becomes a real OneBot `at` segment at the position it was written,
so that person is actually notified instead of reading a bare "@qq:123".
Everything else in that text stays text: plain `@昵称`, `@全体`, an email-looking
`someone@qq:123`, `@qq:all`, or a digit run too long to be a QQ account. The
adapter still never invents an at-all segment. Private sends promote nothing.

The platform's own response is the only source of truth.  A send whose result
cannot be verified becomes `unknown` and is never re-sent; a receipt may be
re-reported with the identical attempt_id.

After a send the platform accepted, the adapter reads that one message back
with `get_msg` (0.2.3).  The id queried is always the one this very send
returned, and the answer is checked against the route we sent to.  It is
observation only: it can never change platform_accepted/failed/unknown, never
trigger a re-send, and never widens what we read (no inbound ids, no reply ids,
no history).  It answers "did the platform store the segments we submitted, in
this conversation, as us" -- not "did a client render a mention".
"""
import re
import time

from .onebot import ApiNotConnected, ApiTimeout, ApiTransportError

RETRY_WAITS = (0, 2, 5)
MAX_SPOOL_TRIES = 20

SEND_ACTIONS = {"dm": "send_private_msg", "group": "send_group_msg"}
# a group send may carry these; a private send only ever carries `text`
ALLOWED_OUT_SEGMENTS = ("reply", "text", "at")
PRIVATE_OUT_SEGMENTS = ("text",)

# 0.2.3 read-back verification: one `get_msg` per accepted send, for the id that
# send returned, after a short settle gap; one retry only when the platform has
# not indexed that id yet.  Observation only -- see the module docstring.
VERIFY_DELAY_SECONDS = 0.8
VERIFY_RETRY_DELAY_SECONDS = 1.5
VERIFY_TIMEOUT_SECONDS = 5.0
VERIFY_COUNTER = {"verified": "verify_verified",
                  "segment_mismatch": "verify_mismatch",
                  "target_mismatch": "verify_mismatch",
                  "not_found": "verify_not_found",
                  "unavailable": "verify_unavailable"}

# `@qq:101030` is the one spelling that means "point at this account".
# An ASCII word char or one of . @ _ - right before the `@` means the `@qq:` is
# part of a longer token (an address, a path); a letter/_/- right after the
# digits means the run is not a bare account id.  Real QQ ids are <= 12 digits,
# so a run longer than 20 is left as text instead of guessed at.
AT_MARKER = re.compile(r"(?<![A-Za-z0-9.@_\-])@qq:([0-9]{1,20})(?![A-Za-z0-9_\-])")


def encode_group_text(text):
    """Split host group text into text/at segments, promoting @qq:<digits>.

    Position is preserved and the marker itself disappears (the platform renders
    the mention).  Empty text pieces are dropped, so a message that is only
    markers yields only `at` segments.
    """
    segments = []
    pos = 0
    for match in AT_MARKER.finditer(text):
        before = text[pos:match.start()]
        if before:
            segments.append({"type": "text", "data": {"text": before}})
        segments.append({"type": "at", "data": {"qq": match.group(1)}})
        pos = match.end()
    tail = text[pos:]
    if tail:
        segments.append({"type": "text", "data": {"text": tail}})
    return segments


def build_send_params(target_type, target_id, text, reply_to=None):
    """Return (action, params) for a host outbox target, or None if unusable.

    Group sends get a `reply` segment only when the host actually provided
    `reply_to`, and their text goes through encode_group_text; private sends are
    byte-for-byte the 0.1.0 shape (one text segment, markers included).
    """
    action = SEND_ACTIONS.get(target_type)
    if action is None:
        return None
    if target_type == "group":
        segments = []
        rid = str(reply_to).strip() if reply_to is not None else ""
        if rid:
            segments.append({"type": "reply", "data": {"id": rid}})
        segments.extend(encode_group_text(text))
        allowed = ALLOWED_OUT_SEGMENTS
    else:
        segments = [{"type": "text", "data": {"text": text}}]
        allowed = PRIVATE_OUT_SEGMENTS
    if not segments:
        return None
    for seg in segments:
        if seg["type"] not in allowed:
            return None
    key = "group_id" if target_type == "group" else "user_id"
    return action, {key: int(target_id), "message": segments}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def verify_payload(resp, checked_id, meta):
    """Classify a `get_msg` answer against what this attempt actually sent.

    Total and side-effect free: anything odd is `unavailable`, never an
    exception and never a claim that the send failed -- by now the message is
    already out.  `target_mismatch` is the binding check (the platform says this
    message lives in a different conversation than the route we sent to);
    `segment_mismatch` means the platform stored a different segment shape than
    the one we submitted.
    """
    sent = [str(s) for s in ((meta or {}).get("segments") or [])]
    ttype = str((meta or {}).get("target_type") or "")
    tid = str((meta or {}).get("target_id") or "")
    out = {"checked_id": str(checked_id), "sent_segments": sent, "result": "unavailable"}
    if not isinstance(resp, dict):
        out["reason"] = "no_response"
        return out
    retcode = resp.get("retcode")
    out["platform_retcode"] = retcode
    data = resp.get("data")
    if retcode != 0:
        out["result"] = "not_found" if retcode == 1200 else "unavailable"
        out["reason"] = str(resp.get("wording") or resp.get("message") or "retcode_%s" % retcode)[:120]
        return out
    if not isinstance(data, dict) or not isinstance(data.get("message"), list):
        out["reason"] = "unexpected_shape"
        return out
    stored = [str(seg.get("type")) for seg in data["message"] if isinstance(seg, dict)]
    sender = data.get("sender") if isinstance(data.get("sender"), dict) else {}
    self_sent = str(sender.get("user_id") or "") == str((meta or {}).get("account_id") or "")
    peer_bound = True
    if ttype == "group":
        target_ok = str(data.get("message_type") or "") == "group" and str(data.get("group_id") or "") == tid
    elif ttype == "dm":
        # NapCat answers get_msg for a private message with user_id = whoever
        # sent it (our own account when reading back our own send), never the
        # peer, so a DM read-back binds "a private conversation this account
        # spoke in" and nothing more.  Comparing that field to the peer id
        # could not ever pass; the first real DM read-back said so.
        target_ok = str(data.get("message_type") or "") == "private" and self_sent
        peer_bound = False
    else:
        target_ok = False
    stored_tid = data.get("group_id") if ttype == "group" else data.get("user_id")
    out.update({"stored_segments": stored, "target_ok": bool(target_ok),
                "stored_target_type": str(data.get("message_type") or ""),
                "stored_target_id": str(stored_tid or ""),
                "sender_is_self": self_sent, "peer_bound": peer_bound,
                "stored_as_self_sent": str(data.get("message_sent_type") or "") == "self"})
    if not target_ok:
        out["result"] = "target_mismatch"
    elif stored != sent:
        out["result"] = "segment_mismatch"
    else:
        out["result"] = "verified"
    return out


def receipt_payload(status, attempt_id, response, platform_message_id=None):
    payload = {"attempt_id": attempt_id, "status": status, "response": response}
    if platform_message_id:
        payload["platform_message_id"] = str(platform_message_id)
    return payload


class Outbound:
    def __init__(self, cfg, host, onebot, journal, counters, log=print, ack_timeout=15.0,
                 verify=True, verify_delay=VERIFY_DELAY_SECONDS,
                 verify_retry_delay=VERIFY_RETRY_DELAY_SECONDS,
                 verify_timeout=VERIFY_TIMEOUT_SECONDS):
        self.cfg = cfg
        self.host = host
        self.onebot = onebot
        self.journal = journal
        self.counters = counters
        self.log = log
        self.ack_timeout = ack_timeout
        self.verify = bool(verify)
        self.verify_delay = float(verify_delay)
        self.verify_retry_delay = float(verify_retry_delay)
        self.verify_timeout = float(verify_timeout)

    # ---- one claimed publication ---------------------------------------
    def handle_item(self, item, stopping=False):
        pub = str(item.get("publication_id") or "")
        attempt = str(item.get("attempt_id") or "")
        target = item.get("target") or {}
        ttype = str(target.get("type") or "")
        tid = str(target.get("id") or "")
        text = item.get("text")
        self.counters.inc("outbox_claims")
        self.log("OUTBOX_CLAIMED pub=%s attempt=%s target=%s:%s chars=%s reply_to=%s"
                 % (pub, attempt, ttype, tid, len(text) if isinstance(text, str) else "-", item.get("reply_to")))
        if stopping:
            self.report(pub, receipt_payload("unknown", attempt, {"reason": "adapter_stopping_before_send"}), "stopping")
            return
        if not pub or not attempt:
            self.counters.inc("outbox_shape_reject")
            self.log("OUTBOX_SHAPE pub=%s missing publication_id/attempt_id" % pub)
            return
        route = self.cfg.route_for_target(ttype, tid)
        if route is None:
            # covers a group target outside adapter.allowed_group_ids as well as
            # an unknown target.type: nothing is sent, the host gets a real failed
            self.counters.inc("outbox_target_reject")
            self.report(pub, receipt_payload("failed", attempt,
                                            {"reason": "target_not_authorized", "target_type": ttype, "target_id": tid}),
                        "target_not_authorized")
            return
        if not isinstance(text, str) or not text.strip():
            self.report(pub, receipt_payload("failed", attempt, {"reason": "empty_text"}), "empty_text")
            return
        built = build_send_params(ttype, tid, text, item.get("reply_to"))
        if built is None:
            self.counters.inc("outbox_shape_reject")
            self.report(pub, receipt_payload("failed", attempt,
                                            {"reason": "segment_guard", "target_type": ttype}), "segment_guard")
            return
        action, params = built
        meta = {"publication_id": pub, "attempt_id": attempt, "target_type": ttype, "target_id": tid,
                "account_id": self.cfg.napcat["account_id"],
                "chars": len(text), "segments": [seg["type"] for seg in params["message"]]}
        try:
            resp = self.onebot.api_call(action, params, timeout=self.ack_timeout, meta=meta)
        except ApiNotConnected as exc:
            self.counters.inc("send_not_connected")
            self.report(pub, receipt_payload("failed", attempt, {"reason": "ws_not_connected", "detail": str(exc)[:200]}),
                        "ws_not_connected")
            return
        except ApiTransportError as exc:
            self.counters.inc("send_unknown")
            self.report(pub, receipt_payload("unknown", attempt, {"reason": "transport_error", "detail": str(exc)[:200]}),
                        "transport_error")
            return
        except ApiTimeout:
            self.counters.inc("send_unknown")
            self.report(pub, receipt_payload("unknown", attempt, {"reason": "no_response_within_timeout",
                                                                 "timeout_seconds": self.ack_timeout}),
                        "ack_timeout")
            return
        self.settle(pub, attempt, resp, meta, stopping=stopping)

    def settle(self, pub, attempt, resp, meta, stopping=False):
        retcode = resp.get("retcode") if isinstance(resp, dict) else None
        data = resp.get("data") if isinstance(resp, dict) else None
        mid = data.get("message_id") if isinstance(data, dict) else None
        if retcode == 0 and mid is not None:
            self.counters.inc("send_accepted")
            status, pmid, tag = "platform_accepted", str(mid), "platform_accepted"
            response = resp
        else:
            self.counters.inc("send_failed")
            status, pmid, tag = "failed", None, "retcode_%s" % retcode
            response = resp if isinstance(resp, dict) else {"unparsed_response": True}
        verification = None
        if status == "platform_accepted" and self.verify:
            # the read-back runs before the receipt so the host can keep it in
            # the raw response object it already stores; it cannot move `status`
            verification = self.verify_send(pmid, meta, stopping=stopping)
            response = dict(response)
            response["verification"] = verification
        self.log("SEND_RESULT pub=%s attempt=%s target=%s status=%s retcode=%s platform_message_id=%s chars=%s"
                 " segments=%s"
                 % (pub, attempt, meta.get("target_type"), status, retcode, pmid or "-", meta.get("chars"),
                    ",".join(meta.get("segments") or [])))
        if verification is not None:
            self.log("VERIFY pub=%s attempt=%s pmid=%s result=%s sent=%s stored=%s target_ok=%s self_sent=%s%s"
                     % (pub, attempt, pmid, verification.get("result"),
                        ",".join(verification.get("sent_segments") or []) or "-",
                        ",".join(verification.get("stored_segments") or []) or "-",
                        verification.get("target_ok"), verification.get("stored_as_self_sent"),
                        "" if verification.get("result") == "verified" else
                        " detail=%s" % (verification.get("reason") or
                                        "%s/%s" % (verification.get("stored_target_type"),
                                                   verification.get("stored_target_id")))))
        self.report(pub, receipt_payload(status, attempt, response, pmid), tag)
        self.journal.append("sends.jsonl", {"ts": _now(), "publication_id": pub, "attempt_id": attempt,
                                           "status": status, "retcode": retcode,
                                           "platform_message_id": pmid, "chars": meta.get("chars"),
                                           "segments": meta.get("segments"),
                                           "verification": verification})

    # ---- read-back verification (observation only) ----------------------
    def verify_send(self, pmid, meta, stopping=False):
        """Ask the platform for the message this send just created, by that id.

        The id is never taken from anywhere else, so this cannot turn into a
        general "read any message" path: inbound ids, `reply_to` ids and history
        are not queried here.  A missing or odd answer is `unavailable`, and the
        send keeps the status the platform already gave it.
        """
        ident = str(pmid or "")
        sent = list((meta or {}).get("segments") or [])
        if not ident.isdigit():
            self.counters.inc("verify_unavailable")
            return {"checked_id": ident[:24], "result": "unavailable",
                    "reason": "id_not_numeric", "sent_segments": sent}
        params = {"message_id": int(ident)}
        checked = {"checked_id": ident, "result": "unavailable", "sent_segments": sent}
        if self.verify_delay > 0 and not stopping:
            time.sleep(self.verify_delay)
        for try_no in (1, 2):
            try:
                resp = self.onebot.api_call("get_msg", params, timeout=self.verify_timeout,
                                            meta={"purpose": "outbound_verification",
                                                  "publication_id": str((meta or {}).get("publication_id") or "")})
            except (ApiNotConnected, ApiTimeout, ApiTransportError) as exc:
                checked["reason"] = "api_%s" % type(exc).__name__
                self.counters.inc("verify_unavailable")
                return checked
            checked = verify_payload(resp, ident, meta)
            if checked["result"] != "not_found" or try_no == 2 or stopping:
                break
            if self.verify_retry_delay > 0:
                time.sleep(self.verify_retry_delay)
        self.counters.inc(VERIFY_COUNTER.get(checked.get("result"), "verify_unavailable"))
        return checked

    # ---- receipts -------------------------------------------------------
    def report(self, pub, payload, why):
        for index, wait in enumerate(RETRY_WAITS):
            if wait:
                time.sleep(wait)
            res = self.host.post_receipt(pub, payload)
            if res.kind in ("ok", "accepted", "duplicate"):
                self.counters.inc("receipts_reported")
                self.log("RECEIPT_OK pub=%s status=%s http=%s why=%s" % (pub, payload["status"], res.code, why))
                return True
            if res.kind == "reject":
                self.counters.inc("receipts_rejected")
                self.log("RECEIPT_REJECT pub=%s status=%s http=%s error=%s"
                         % (pub, payload["status"], res.code, (res.obj or {}).get("error") if isinstance(res.obj, dict) else res.error))
                self.journal.append("receipts_rejected.jsonl",
                                    {"ts": _now(), "publication_id": pub, "payload": payload,
                                     "http": res.code, "body": res.obj})
                return False
            self.counters.inc("receipt_retries")
        self.counters.inc("receipts_spooled")
        self.journal.spool_add("receipts", {"publication_id": pub, "payload": payload, "why": why, "tries": 1},
                               key=pub[:40])
        self.log("RECEIPT_SPOOLED pub=%s status=%s why=%s" % (pub, payload["status"], why))
        return False

    def replay_receipts(self):
        for path in self.journal.spool_list("receipts"):
            try:
                blob = self.journal.read_json(path)
            except Exception:
                self.journal.spool_move(path, "receipts_unreadable.jsonl", {"reason": "unreadable"})
                continue
            pub = str(blob.get("publication_id") or "")
            payload = blob.get("payload") or {}
            res = self.host.post_receipt(pub, payload)
            if res.kind in ("ok", "accepted", "duplicate"):
                self.counters.inc("receipts_reported")
                self.journal.append("receipts_reported.jsonl", {"ts": _now(), "publication_id": pub,
                                                               "status": payload.get("status"), "replay": True})
                self.journal.spool_remove(path)
                self.log("RECEIPT_REPLAYED pub=%s status=%s http=%s" % (pub, payload.get("status"), res.code))
            elif res.kind == "reject":
                self.counters.inc("receipts_rejected")
                self.journal.spool_move(path, "receipts_rejected.jsonl",
                                        {"reason": "host_rejected", "http": res.code, "body": res.obj})
                self.log("RECEIPT_REPLAY_REJECT pub=%s http=%s" % (pub, res.code))
            else:
                tries = int(blob.get("tries") or 0) + 1
                if tries > MAX_SPOOL_TRIES:
                    self.journal.spool_move(path, "receipts_abandoned.jsonl", {"reason": "host_unreachable_too_long"})
                    self.log("RECEIPT_ABANDONED pub=%s" % pub)
                else:
                    blob["tries"] = tries
                    self.journal.write_json(path, blob)

    # ---- late platform acks ---------------------------------------------
    def on_late_ack(self, meta, response):
        pub = str((meta or {}).get("publication_id") or "")
        attempt = str((meta or {}).get("attempt_id") or "")
        if not pub or not attempt:
            return
        retcode = response.get("retcode") if isinstance(response, dict) else None
        data = response.get("data") if isinstance(response, dict) else None
        mid = data.get("message_id") if isinstance(data, dict) else None
        if retcode == 0 and mid is not None:
            status, pmid = "platform_accepted", str(mid)
        else:
            status, pmid = "failed", None
        self.log("LATE_ACK pub=%s attempt=%s retcode=%s -> %s" % (pub, attempt, retcode, status))
        self.journal.append("late_acks.jsonl", {"ts": _now(), "publication_id": pub, "attempt_id": attempt,
                                               "retcode": retcode, "platform_message_id": pmid})
        self.report(pub, receipt_payload(status, attempt, response if isinstance(response, dict) else {"late": True}, pmid),
                    "late_ack")

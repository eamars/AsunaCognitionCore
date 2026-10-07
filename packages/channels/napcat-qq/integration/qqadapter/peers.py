"""Peer identity: who is speaking, and whether it is still the same person.

ADR-005 phase 1.  Two questions are answered here and nowhere else:

  1. what does the platform currently say about the sender of this authorized
     message - QQ nickname, this group's card, role in this group;
  2. after they rename or change their card, is this still the person we have
     been talking to.

Identity is the account, never the display name: `person_id` is `qq:<account>`
and is the same in the private chat and in every group.  Display names are
history attached to that identity, so a rename becomes a recorded change with
the previous value kept, not a new stranger.  A group card belongs to one group
only; the nickname belongs to the person.

Where the facts come from, most trusted first:
  api           get_group_member_info / get_stranger_info, called only for a
                sender who already passed this scene's authorization gate
  event_sender  the `sender` block the platform put on this very message
  cache         the last known profile, still marked with its source
Nothing is invented: a field nobody reported stays absent, and a failed lookup
leaves `verified: false` instead of a guess.  get_stranger_info answers with a
large personal profile (address, birthday, interests); only user_id and
nickname are kept, the rest is dropped and never written to disk.

The profile travels to the host inside `raw` under `asuna_peer`, because the
host envelope is a strict allowlist (an extra top-level field is answered with
CHANNEL_ENVELOPE_FIELD_DENIED).  Nothing else in the envelope changes.
"""
import json
import os
import threading
import time
from datetime import datetime, timezone

PEER_KEY = "asuna_peer"
FIELD_DENIED = "CHANNEL_ENVELOPE_FIELD_DENIED"
ROLES = ("owner", "admin", "member")
NAME_LIMIT = 60
MAX_NICKNAME_HISTORY = 12
MAX_CARD_HISTORY = 12
MAX_ALIASES = 8
MAX_CHANGES = 20
DEFAULT_TTL_SECONDS = 6 * 3600
MIN_REFRESH_SECONDS = 30
API_TIMEOUT = 3.0


def iso(ts=None):
    return datetime.fromtimestamp(int(time.time() if ts is None else ts),
                                  timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch(text):
    """Seconds since the epoch for an `iso()` string -- which is UTC.

    `time.mktime` reads a bare struct_time as *local* time, so the round trip
    was only correct on a UTC machine: west of UTC a fresh lookup looked like
    it belonged to the future (a rename no longer forced a re-check), east of
    UTC it looked already stale.  Parse it as what it is instead.
    """
    if not isinstance(text, str):
        return None
    try:
        return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    except (ValueError, TypeError, OverflowError):
        return None


def clean_name(value, limit=NAME_LIMIT):
    """A display name, or None when the platform reported nothing usable."""
    if value is None:
        return None
    text = " ".join(str(value).replace("\x00", " ").split())
    if not text:
        return None
    return text[:limit]


def clean_role(value):
    if isinstance(value, str):
        role = value.strip().lower()
        if role in ROLES:
            return role
    return None


def _take_names(target, source):
    """Copy the whitelisted identity fields out of a platform object.

    An empty `card` is kept as "" (the person removed their card), while an
    absent key means "nobody told us" and must not overwrite what we know.
    """
    if not isinstance(source, dict):
        return
    if "nickname" in source:
        target["nickname"] = clean_name(source.get("nickname")) or ""
    if "card" in source:
        target["card"] = clean_name(source.get("card")) or ""
    if "title" in source:
        target["title"] = clean_name(source.get("title")) or ""
    role = clean_role(source.get("role"))
    if role:
        target["role"] = role
    joined = source.get("join_time")
    if isinstance(joined, (int, float)) and joined > 0:
        target["joined_at"] = iso(joined)


def profile_from_event(event):
    """What the platform itself said about the sender on this message."""
    if not isinstance(event, dict):
        return None
    sender = event.get("sender")
    if not isinstance(sender, dict):
        return None
    out = {}
    _take_names(out, sender)
    uid = str(sender.get("user_id")).strip() if sender.get("user_id") is not None else ""
    if uid.isdigit():
        out["account_id"] = uid
    if not out:
        return None
    out["source"] = "event_sender"
    return out


def identity_from_api(resp, account):
    """Whitelisted view of a get_group_member_info / get_stranger_info answer."""
    if not isinstance(resp, dict):
        return {"error": "bad_response"}
    if resp.get("retcode") != 0:
        return {"error": "retcode_%s" % resp.get("retcode")}
    data = resp.get("data")
    if not isinstance(data, dict):
        return {"error": "no_data"}
    answered = str(data.get("user_id")).strip() if data.get("user_id") is not None else ""
    if answered and answered != account:
        # the platform answered about somebody else: trust neither side
        return {"error": "identity_mismatch"}
    out = {"nickname": "", "card": "", "title": "", "source": "api"}
    _take_names(out, data)
    if "card" not in data:
        out.pop("card", None)      # a stranger answer says nothing about any card
    if "title" not in data:
        out.pop("title", None)
    return out


def scene_display(scene_rec):
    card = (scene_rec.get("card") or "").strip()
    nick = (scene_rec.get("nickname") or "").strip()
    if card:
        return card, "card"
    if nick:
        return nick, "nickname"
    return "", "unknown"


def _new_person(account):
    now = iso()
    return {"person_id": "qq:%s" % account, "account_id": account, "nickname": "",
            "first_seen": now, "last_seen": now, "nickname_history": [],
            "aliases": [], "scenes": {}, "changes": []}


def _new_scene(scene):
    return {"scene": scene, "first_seen": iso(), "last_seen": iso(), "messages": 0,
            "nickname": "", "card": "", "role": "", "title": "", "display": "",
            "display_source": "unknown", "relation": "", "joined_at": "",
            "card_history": [], "role_history": [], "profile_at": "",
            "profile_source": "", "verified": False}


def _push(history, value, now):
    """Append to a bounded history, extending the run of the current value."""
    if history and history[-1].get("value") == value:
        history[-1]["last_seen"] = now
        return
    history.append({"value": value, "first_seen": now, "last_seen": now})
    while len(history) > MAX_NICKNAME_HISTORY:
        history.pop(0)


def _add_alias(person, value):
    aliases = person.setdefault("aliases", [])
    if value and value not in aliases:
        aliases.append(value)
    while len(aliases) > MAX_ALIASES:
        aliases.pop(0)


class PeerDirectory:
    """Persistent person records, keyed by account, one scene entry per group
    plus one for the private chat.

    `observe()` runs on the submitter thread (never on the WebSocket reader),
    so an identity lookup can take its few hundred milliseconds without holding
    up inbound.  It never raises: the worst case is a profile that says
    `verified: false` and an inbound message that still goes out.
    """

    def __init__(self, root, log=None, counters=None, ttl=DEFAULT_TTL_SECONDS,
                 min_refresh=MIN_REFRESH_SECONDS, api_timeout=API_TIMEOUT, inject=True):
        self.dir = os.path.join(root, "peers")
        self.path = os.path.join(self.dir, "peers.json")
        self.journal_dir = os.path.join(root, "journal")
        self.log = log or (lambda msg: None)
        self.counters = counters
        self.ttl = ttl
        self.min_refresh = min_refresh
        self.api_timeout = api_timeout
        self.inject = inject
        self.reset_reason = None
        self._lock = threading.RLock()
        self._people = {}
        self._last_call = {}
        self._changes_now = []
        os.makedirs(self.dir, exist_ok=True)
        os.makedirs(self.journal_dir, exist_ok=True)
        self._load()

    # ---- storage --------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                blob = json.load(handle)
        except FileNotFoundError:
            return
        except Exception as exc:
            # never start a new person from a file we could not read: keep the
            # broken one next to us and say so in the health snapshot
            self.reset_reason = type(exc).__name__
            try:
                os.replace(self.path, self.path + ".bad")
            except OSError:
                pass
            return
        people = blob.get("people") if isinstance(blob, dict) else None
        if not isinstance(people, dict):
            self.reset_reason = "bad_shape"
            return
        for key, rec in people.items():
            if isinstance(rec, dict) and isinstance(rec.get("scenes"), dict):
                self._people[str(key)] = rec

    def _save(self):
        blob = {"version": 1, "updated_at": iso(), "people": self._people}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(blob, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    # ---- observation ----------------------------------------------------
    def observe(self, envelope, api=None):
        """Update the directory for one authorized envelope.

        Returns the profile the character is allowed to see, and (when
        `inject` is on) puts the same object into envelope["raw"]["asuna_peer"].
        """
        account = str(envelope.get("sender_id") or "").strip()
        if not account.isdigit():
            return None
        group_id = str(envelope.get("group_id")).strip() if envelope.get("group_id") is not None else ""
        scene = "group:%s" % group_id if group_id else "dm"
        raw = envelope.get("raw") if isinstance(envelope.get("raw"), dict) else {}
        fresh = profile_from_event(raw)
        person_id = "qq:%s" % account
        self._changes_now = []
        with self._lock:
            rec = self._people.get(person_id) or _new_person(account)
            self._people[person_id] = rec
            rec["last_seen"] = iso()
            scene_rec = rec["scenes"].get(scene) or _new_scene(scene)
            rec["scenes"][scene] = scene_rec
            scene_rec["last_seen"] = rec["last_seen"]
            scene_rec["messages"] = int(scene_rec.get("messages") or 0) + 1
            if scene == "dm":
                relation = clean_name(raw.get("sub_type"), 20)
                if relation:
                    scene_rec["relation"] = relation
            disagree = bool(fresh) and _disagrees(rec, scene_rec, fresh)
            if fresh:
                self._merge(rec, scene_rec, fresh)
            want_api, no_cache = self._want_api(person_id, scene, scene_rec, disagree)
        result = self._fetch(api, scene, account, no_cache) if (want_api and api is not None) else None
        with self._lock:
            if result is not None:
                if result.get("error"):
                    scene_rec["profile_source"] = "api_error:%s" % str(result["error"])[:40]
                else:
                    result["source"] = "api"
                    self._merge(rec, scene_rec, result)
                    scene_rec["profile_at"] = iso()
                    scene_rec["profile_source"] = "api"
                    scene_rec["verified"] = True
            profile = self._profile_for(rec, scene_rec, scene, group_id)
            self._save()
        if self.inject and isinstance(envelope.get("raw"), dict):
            envelope["raw"][PEER_KEY] = profile
        return profile

    def _want_api(self, person_id, scene, scene_rec, disagree):
        """Spend a lookup only when it can tell us something new.  `disagree` is
        judged against the record as it stood before this message, because the
        sender block of this message is already merged in by now."""
        key = (person_id, scene)
        now = time.monotonic()
        if now - self._last_call.get(key, 0.0) < self.min_refresh:
            return False, False
        if scene_rec.get("profile_source") != "api":
            return True, False                       # never confirmed in this scene
        seen = epoch(scene_rec.get("profile_at"))
        if seen is None or time.time() - seen > self.ttl:
            return True, False                       # stale: take the platform cache
        if disagree:
            return True, True                        # the sender block says something changed
        return False, False

    def _fetch(self, api, scene, account, no_cache):
        action, params = self._lookup_for(scene, account, no_cache)
        if action is None:
            return {"error": "no_lookup"}
        self._last_call[(("qq:%s" % account), scene)] = time.monotonic()
        try:
            resp = api.api_call(action, params, timeout=self.api_timeout)
        except Exception as exc:
            self._bump("peer_api_errors")
            return {"error": type(exc).__name__}
        self._bump("peer_api_calls")
        return identity_from_api(resp, account)

    @staticmethod
    def _lookup_for(scene, account, no_cache):
        if scene == "dm":
            return "get_stranger_info", {"user_id": int(account), "no_cache": bool(no_cache)}
        if scene.startswith("group:"):
            group_id = scene.split(":", 1)[1]
            if group_id.isdigit():
                return ("get_group_member_info",
                        {"group_id": int(group_id), "user_id": int(account), "no_cache": bool(no_cache)})
        return None, None

    # ---- record keeping -------------------------------------------------
    def _merge(self, rec, scene_rec, facts):
        nick = facts.get("nickname")
        if isinstance(nick, str) and nick:
            scene_rec["nickname"] = nick             # what this scene sees of them
        if isinstance(nick, str) and nick and nick != rec.get("nickname"):
            previous = rec.get("nickname") or ""
            rec["nickname"] = nick
            _push(rec.setdefault("nickname_history", []), nick, iso())
            _add_alias(rec, nick)
            if previous:
                self._record_change(rec, scene_rec["scene"], "nickname", previous, nick)
        card = facts.get("card")
        if isinstance(card, str) and card != (scene_rec.get("card") or ""):
            previous = scene_rec.get("card") or ""
            scene_rec["card"] = card
            if card:
                _push(scene_rec.setdefault("card_history", []), card, iso())
                _add_alias(rec, card)
            if previous:
                self._record_change(rec, scene_rec["scene"], "card", previous, card)
        role = facts.get("role")
        if role and role != scene_rec.get("role"):
            previous = scene_rec.get("role") or ""
            scene_rec["role"] = role
            _push(scene_rec.setdefault("role_history", []), role, iso())
            if previous:
                self._record_change(rec, scene_rec["scene"], "role", previous, role)
        title = facts.get("title")
        if isinstance(title, str) and title != (scene_rec.get("title") or ""):
            previous = scene_rec.get("title") or ""
            scene_rec["title"] = title
            if previous:
                self._record_change(rec, scene_rec["scene"], "title", previous, title)
        if facts.get("joined_at"):
            scene_rec["joined_at"] = facts["joined_at"]
        display, source = scene_display(scene_rec)
        scene_rec["display"] = display
        scene_rec["display_source"] = source

    def _record_change(self, rec, scene, field, previous, current):
        now = iso()
        entry = {"at": now, "scene": scene, "field": field, "from": previous, "to": current}
        changes = rec.setdefault("changes", [])
        changes.append(entry)
        while len(changes) > MAX_CHANGES:
            changes.pop(0)
        rec["last_change"] = entry
        self._changes_now.append(entry)
        self._bump("peer_changes")
        try:
            line = json.dumps(dict(entry, person_id=rec["person_id"]), ensure_ascii=False, sort_keys=True)
            with open(os.path.join(self.journal_dir, "peer_changes.jsonl"), "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            pass
        self.log("PEER_CHANGED person=%s scene=%s field=%s from=%r to=%r"
                 % (rec["person_id"], scene, field, previous, current))

    def _profile_for(self, rec, scene_rec, scene, group_id):
        display, source = scene_display(scene_rec)
        profile = {
            "person_id": rec["person_id"],
            "account_id": rec["account_id"],
            "scene": scene,
            "display": display,
            "display_source": source,
            "nickname": rec.get("nickname") or "",
            "role": scene_rec.get("role") or "unknown",
            "known_since": rec.get("first_seen") or "",
            "seen_messages": int(scene_rec.get("messages") or 0),
            "source": scene_rec.get("profile_source") or "event_sender",
            "verified": bool(scene_rec.get("verified")),
        }
        if group_id:
            profile["group_id"] = group_id
            profile["card"] = scene_rec.get("card") or ""
        if scene_rec.get("relation"):
            profile["relation"] = scene_rec["relation"]
        if scene_rec.get("title"):
            profile["title"] = scene_rec["title"]
        if scene_rec.get("joined_at"):
            profile["joined_at"] = scene_rec["joined_at"]
        if scene_rec.get("profile_at"):
            profile["profile_at"] = scene_rec["profile_at"]
        aliases = [a for a in (rec.get("aliases") or []) if a]
        if aliases:
            profile["aliases"] = list(aliases[-MAX_ALIASES:])
        if self._changes_now:
            profile["changed"] = [c["field"] for c in self._changes_now]
            profile["previous"] = dict((c["field"], c["from"]) for c in self._changes_now)
            profile["changed_at"] = self._changes_now[-1]["at"]
        return profile

    # ---- misc -----------------------------------------------------------
    def _bump(self, name, delta=1):
        if self.counters is not None:
            self.counters.inc(name, delta)

    def summary(self):
        with self._lock:
            return {
                "people": len(self._people),
                "scenes": sum(len(r.get("scenes") or {}) for r in self._people.values()),
                "changes": sum(len(r.get("changes") or []) for r in self._people.values()),
                "store_reset": self.reset_reason,
            }

    def dump(self):
        with self._lock:
            return {"version": 1, "updated_at": iso(), "people": self._people}

    @staticmethod
    def strip(envelope):
        """Drop the injected block (used if a host ever refuses it)."""
        raw = envelope.get("raw") if isinstance(envelope.get("raw"), dict) else None
        if raw is not None and PEER_KEY in raw:
            del raw[PEER_KEY]
            return True
        return False

    @staticmethod
    def denied(obj):
        return isinstance(obj, dict) and obj.get("error") == FIELD_DENIED


def _disagrees(rec, scene_rec, fresh):
    for field in ("nickname", "card", "role", "title"):
        if field not in fresh:
            continue
        known = (rec.get("nickname") or "") if field == "nickname" else (scene_rec.get(field) or "")
        if (fresh.get(field) or "") != known:
            return True
    return False

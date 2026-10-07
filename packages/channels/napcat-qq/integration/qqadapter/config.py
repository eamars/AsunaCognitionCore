"""Load and validate /integration/config.json.

Secrets stay inside this object; `describe()` is the only thing allowed into
logs, journals or chat output.

Two route kinds are supported:
  private: message_type=private, target.type=dm,    sender_id=<peer>
  group:   message_type=group,   target.type=group, target.id=<group id>,
           allowed_sender_ids=[<member ids>]   (the authorized member snapshot)
Explicit admission is bounded by the configured allowlists. Automatic admission
uses deterministic routes for new targets under the owner's admission policy.
"""
import json
import os
import re
from urllib.parse import urlparse


class ConfigError(Exception):
    pass


SECRET_RE = re.compile(r"token|password|secret|key|auth|cookie", re.I)
DIGITS = re.compile(r"^[0-9]{4,20}$")

PRIVATE_ROUTE_KEYS = {"message_type", "sender_id", "target"}
GROUP_ROUTE_KEYS = {"message_type", "allowed_sender_ids", "target"}


def redacted(node, path=""):
    """Config tree with secret-looking leaves replaced by their length."""
    if isinstance(node, dict):
        return {k: redacted(v, path + "/" + k) for k, v in sorted(node.items())}
    if isinstance(node, list):
        return [redacted(v, "%s[%d]" % (path, i)) for i, v in enumerate(node)]
    last = path.rsplit("/", 1)[-1]
    if SECRET_RE.search(last):
        return "<len=%d>" % len(str(node))
    return node


def _id_list(values, label, route_id=""):
    if not isinstance(values, list) or not values:
        raise ConfigError("route %s: %s must be a non-empty list" % (route_id, label))
    out = []
    for val in values:
        sval = str(val)
        if not DIGITS.match(sval):
            raise ConfigError("route %s: %s contains a non-digit id" % (route_id, label))
        if sval not in out:
            out.append(sval)
    return out


class Route:
    __slots__ = ("route_id", "message_type", "sender_id", "target_type", "target_id", "allowed_senders")

    def __init__(self, route_id, blob):
        if not isinstance(blob, dict):
            raise ConfigError("route %s: not an object" % route_id)
        self.route_id = route_id
        self.message_type = blob.get("message_type")
        self.sender_id = blob.get("sender_id")
        target = blob.get("target") or {}
        if not isinstance(target, dict):
            raise ConfigError("route %s: target must be an object" % route_id)
        self.target_type = target.get("type")
        self.target_id = target.get("id")
        self.allowed_senders = frozenset()
        if self.message_type == "private":
            unknown = sorted(set(blob) - PRIVATE_ROUTE_KEYS)
            if unknown:
                raise ConfigError("route %s: unknown keys for a private route: %s" % (route_id, ",".join(unknown)))
            if self.target_type != "dm":
                raise ConfigError("route %s: target.type %r unsupported for a private route" % (route_id, self.target_type))
            if not isinstance(self.sender_id, str) or not DIGITS.match(self.sender_id):
                raise ConfigError("route %s: sender_id must be a digit string" % route_id)
            if not isinstance(self.target_id, str) or not DIGITS.match(self.target_id):
                raise ConfigError("route %s: target.id must be a digit string" % route_id)
            self.allowed_senders = frozenset([self.sender_id])
        elif self.message_type == "group":
            unknown = sorted(set(blob) - GROUP_ROUTE_KEYS)
            if unknown:
                raise ConfigError("route %s: unknown keys for a group route: %s" % (route_id, ",".join(unknown)))
            if self.target_type != "group":
                raise ConfigError("route %s: target.type %r unsupported for a group route" % (route_id, self.target_type))
            if not isinstance(self.target_id, str) or not DIGITS.match(self.target_id):
                raise ConfigError("route %s: target.id must be a digit group id" % route_id)
            if "sender_id" in blob:
                raise ConfigError("route %s: a group route must not pin sender_id" % route_id)
            self.sender_id = None
            self.allowed_senders = frozenset(_id_list(blob.get("allowed_sender_ids"), "allowed_sender_ids", route_id))
        else:
            raise ConfigError("route %s: message_type %r unsupported" % (route_id, self.message_type))

    @property
    def member_count(self):
        return len(self.allowed_senders)

    def accepts_sender(self, sender_id):
        return sender_id in self.allowed_senders


class Config:
    def __init__(self, raw, path):
        self.path = path
        if not isinstance(raw, dict):
            raise ConfigError("config root must be an object")
        self.raw = raw
        self.endpoints = self._endpoints(raw.get("endpoints"))
        adapter = raw.get("adapter")
        if not isinstance(adapter, dict):
            raise ConfigError("adapter section missing")
        self.admission = adapter.get('admission', 'explicit')
        if self.admission not in ('explicit', 'automatic'):
            raise ConfigError('adapter.admission must be explicit or automatic')
        self.blocked_senders = set(adapter.get('blocked_senders', []))
        self.blocked_groups = set(adapter.get('blocked_groups', []))
        private = adapter.get('allowed_private_user_ids') or []
        self.allowed_private = self._id_list(private, "allowed_private_user_ids") if private else []
        groups = adapter.get("allowed_group_ids") or []
        if not isinstance(groups, list):
            raise ConfigError("allowed_group_ids must be a list")
        self.allowed_groups = self._id_list(groups, "allowed_group_ids") if groups else []
        self.napcat = self._napcat(adapter.get("napcat"))
        self.host = self._host(adapter.get("host"))
        self.routes = self._routes(adapter.get("routes"))
        self.media_mode = self._media_mode(adapter.get("media_mode"))
        self.catchup_routes, self.catchup_lookback_hours = self._catchup(adapter.get("catchup"), self.routes)
        self._cross_check()

    # ---- sections -------------------------------------------------------
    @staticmethod
    def _media_mode(value):
        """How far media reporting goes; absent means the 0.4.0 default."""
        if value is None:
            return "full"
        if value not in ("full", "annotate", "off"):
            raise ConfigError("adapter.media_mode %r unsupported (need full|annotate|off)" % (value,))
        return value

    @staticmethod
    def _catchup(node, routes):
        """(route ids caught up after a gap, look-back hours); absent means off (catchup.py)."""
        if node is None:
            return frozenset(), 6
        if not isinstance(node, dict):
            raise ConfigError("adapter.catchup must be an object {routes, lookback_hours}")
        wanted = node.get("routes", [])
        if wanted == "all":
            chosen = frozenset(routes)
        elif isinstance(wanted, list) and all(isinstance(r, str) for r in wanted):
            unknown = sorted(set(wanted) - set(routes))
            if unknown:
                raise ConfigError("adapter.catchup.routes names unknown routes %s (routes are %s)"
                                  % (",".join(unknown), ",".join(sorted(routes))))
            chosen = frozenset(wanted)
        else:
            raise ConfigError('adapter.catchup.routes must be "all" or a list of route ids')
        hours = node.get("lookback_hours", 6)
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 6:
            raise ConfigError("adapter.catchup.lookback_hours %r unsupported (need an integer 1..6)" % (hours,))
        return chosen, hours

    @staticmethod
    def _endpoints(node):
        if not isinstance(node, dict) or not node:
            raise ConfigError("endpoints section missing")
        out = {}
        for name, ep in node.items():
            if not isinstance(ep, dict) or "host" not in ep or "port" not in ep:
                raise ConfigError("endpoint %s must have host and port" % name)
            out[name] = (str(ep["host"]), int(ep["port"]))
        return out

    def _require_endpoint(self, kind, host, port):
        for name, (eh, ep) in self.endpoints.items():
            if eh == host and ep == port:
                return name
        raise ConfigError("%s address %s:%s is not one of the configured endpoints" % (kind, host, port))

    def _napcat(self, node):
        if not isinstance(node, dict):
            raise ConfigError("adapter.napcat missing")
        transport = node.get("transport")
        if transport != "websocket_forward":
            raise ConfigError("adapter.napcat.transport %r unsupported (need websocket_forward)" % transport)
        url = node.get("url")
        if not isinstance(url, str):
            raise ConfigError("adapter.napcat.url missing")
        parsed = urlparse(url)
        if parsed.scheme not in ("ws", "wss") or not parsed.hostname:
            raise ConfigError("adapter.napcat.url must be ws:// or wss:// with a literal host")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        endpoint = self._require_endpoint("napcat", parsed.hostname, port)
        token = node.get("token")
        if not isinstance(token, str) or not token:
            raise ConfigError("adapter.napcat.token missing")
        account = node.get("account_id")
        if not isinstance(account, str) or not DIGITS.match(account):
            raise ConfigError("adapter.napcat.account_id must be a digit string")
        return {
            "url": url.rstrip("/"),
            "scheme": parsed.scheme,
            "host": parsed.hostname,
            "port": port,
            "endpoint": endpoint,
            "token": token,
            "account_id": account,
            "shared_account": bool(node.get("shared_account")),
            "transport": transport,
        }

    def _host(self, node):
        if not isinstance(node, dict):
            raise ConfigError("adapter.host missing")
        base = node.get("base_url")
        if not isinstance(base, str):
            raise ConfigError("adapter.host.base_url missing")
        parsed = urlparse(base)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ConfigError("adapter.host.base_url must be http(s) with a literal host")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        endpoint = self._require_endpoint("host", parsed.hostname, port)
        token = node.get("token")
        if not isinstance(token, str) or len(token) < 24:
            raise ConfigError("adapter.host.token must be at least 24 chars")
        channel = node.get("channel_id")
        if not isinstance(channel, str) or not channel:
            raise ConfigError("adapter.host.channel_id missing")
        return {
            "base_url": base.rstrip("/"),
            "host": parsed.hostname,
            "port": port,
            "endpoint": endpoint,
            "token": token,
            "channel_id": channel,
        }

    def _routes(self, node):
        if not isinstance(node, dict) or not node and self.admission != 'automatic':
            raise ConfigError("adapter.routes missing")
        routes = {}
        for route_id, blob in node.items():
            routes[route_id] = Route(route_id, blob)
        return routes

    def _cross_check(self):
        seen_group_targets = {}
        for route in self.routes.values():
            if route.message_type == "private":
                if route.sender_id not in self.allowed_private:
                    raise ConfigError("route %s sender %s not in allowed_private_user_ids" % (route.route_id, route.sender_id))
                if route.target_id not in self.allowed_private:
                    raise ConfigError("route %s target %s not in allowed_private_user_ids" % (route.route_id, route.target_id))
                continue
            if route.target_id not in self.allowed_groups:
                raise ConfigError("route %s group %s not in allowed_group_ids" % (route.route_id, route.target_id))
            if route.target_id in seen_group_targets:
                raise ConfigError("routes %s and %s both bind group %s" % (seen_group_targets[route.target_id],
                                                                          route.route_id, route.target_id))
            seen_group_targets[route.target_id] = route.route_id

    @staticmethod
    def _id_list(node, label):
        if not isinstance(node, list) or not node:
            raise ConfigError("%s must be a non-empty list" % label)
        out = []
        for val in node:
            sval = str(val)
            if not DIGITS.match(sval):
                raise ConfigError("%s contains a non-digit id" % label)
            if sval not in out:
                out.append(sval)
        return out

    # ---- lookups --------------------------------------------------------
    def route_for_sender(self, sender_id):
        if sender_id in self.blocked_senders or not DIGITS.fullmatch(sender_id):
            return None
        for route in self.routes.values():
            if route.message_type == "private" and route.sender_id == sender_id:
                return route
        if self.admission == 'automatic':
            return Route('auto-dm-' + sender_id, {'message_type': 'private', 'sender_id': sender_id,
                'target': {'type': 'dm', 'id': sender_id}})
        return None

    def route_for_group(self, group_id):
        if group_id in self.blocked_groups or not DIGITS.fullmatch(group_id):
            return None
        if group_id not in self.allowed_groups and self.admission != 'automatic':
            return None
        for route in self.routes.values():
            if route.message_type == "group" and route.target_id == group_id:
                return route
        if self.admission == 'automatic':
            return Route('auto-group-' + group_id, {'message_type': 'group',
                'allowed_sender_ids': [self.napcat['account_id']], 'target': {'type': 'group', 'id': group_id}})
        return None

    def route_for_target(self, target_type, target_id):
        if target_type == "dm":
            return self.route_for_sender(target_id)
        if target_type == "group":
            return self.route_for_group(target_id)
        return None

    def is_allowed_private(self, target_id):
        return self.route_for_sender(target_id) is not None

    def is_group_member(self, group_id, sender_id):
        route = self.route_for_group(group_id)
        return bool(route and sender_id not in self.blocked_senders and DIGITS.fullmatch(sender_id)
                    and (self.admission == 'automatic' or route.accepts_sender(sender_id)))

    def describe(self):
        group_routes = [r for r in self.routes.values() if r.message_type == "group"]
        return (
            "account=%s shared_account=%s napcat=%s(%s) host=%s(%s) channel=%s "
            "routes=%s allowed_private=%s allowed_groups=%s group_members=%s media_mode=%s catchup=%s"
            % (
                self.napcat["account_id"],
                self.napcat["shared_account"],
                self.napcat["url"],
                self.napcat["endpoint"],
                self.host["base_url"],
                self.host["endpoint"],
                self.host["channel_id"],
                ",".join(sorted(self.routes)),
                ",".join(self.allowed_private),
                ",".join(self.allowed_groups) or "-",
                ",".join("%s:%d" % (r.route_id, r.member_count) for r in sorted(group_routes, key=lambda r: r.route_id)) or "-",
                self.media_mode,
                ("%s/%dh" % (",".join(sorted(self.catchup_routes)), self.catchup_lookback_hours)
                 if self.catchup_routes else "off"),
            )
        )


def load(path=None):
    cfg_path = path or os.environ.get("ASUNA_INTEGRATION_CONFIG", "/integration/config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        raise ConfigError("config file not found: %s" % cfg_path)
    except ValueError as exc:
        raise ConfigError("config is not valid JSON: %s" % exc)
    return Config(raw, cfg_path)

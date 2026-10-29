"""Load and validate /integration/config.json.

Secrets stay inside this object; `describe()` is the only thing allowed into
logs, journals or chat output.

This adapter keeps only what it needs to reach its platform and the core: NapCat's address and token, the core's
address and token, the account, media and catch-up settings. Who may speak, which groups and people are listed, and
the block lists are the core's (ADR-107): the adapter asks it (`admission.py`) and holds no copy.
"""
import json
import os
import re
from urllib.parse import urlparse


# The largest file the adapter sends to a group (adapter.napcat.max_file_mb, in MiB), declared to the host as
# file:<bytes>.  A missing value is the default; an invalid one is the default too, said once in CONFIG_NOTE.
DEFAULT_MAX_FILE_MB = 50
MAX_FILE_MB_MOST = 4096           # QQ's own single-file limit for group files


class ConfigError(Exception):
    pass


SECRET_RE = re.compile(r"token|password|secret|key|auth|cookie", re.I)
DIGITS = re.compile(r"^[0-9]{4,20}$")


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


class Config:
    def __init__(self, raw, path):
        self.path = path
        if not isinstance(raw, dict):
            raise ConfigError("config root must be an object")
        self.raw = raw
        self.notes = []                  # a setting that fell back to its default, logged once at start
        self.endpoints = self._endpoints(raw.get("endpoints"))
        adapter = raw.get("adapter")
        if not isinstance(adapter, dict):
            raise ConfigError("adapter section missing")
        self.napcat = self._napcat(adapter.get("napcat"))
        self.host = self._host(adapter.get("host"))
        self.media_mode = self._media_mode(adapter.get("media_mode"))
        self.catchup_routes, self.catchup_lookback_hours, self.catchup_every = self._catchup(adapter.get("catchup"))

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
    def _catchup(node):
        """(route ids caught up after a gap, look-back hours, every); absent means off (catchup.py). A route id is a name
        the core gave (a listed route's, or `auto-group-<id>` / `auto-dm-<id>`): the adapter takes it as it is and asks
        the core at run time whether it is served. "all" means every route the core serves and every cursor kept."""
        if node is None:
            return frozenset(), 6, False
        if not isinstance(node, dict):
            raise ConfigError("adapter.catchup must be an object {routes, lookback_hours}")
        wanted = node.get("routes", [])
        if wanted == "all":
            chosen = frozenset()
        elif isinstance(wanted, list) and all(isinstance(r, str) and r for r in wanted):
            chosen = frozenset(wanted)
        else:
            raise ConfigError('adapter.catchup.routes must be "all" or a list of route ids')
        hours = node.get("lookback_hours", 6)
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 24:
            raise ConfigError("adapter.catchup.lookback_hours %r unsupported (need an integer 1..24)" % (hours,))
        return chosen, hours, wanted == "all"

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
        most = node.get("max_file_mb", DEFAULT_MAX_FILE_MB)
        if isinstance(most, bool) or not isinstance(most, int) or not 1 <= most <= MAX_FILE_MB_MOST:
            self.notes.append("adapter.napcat.max_file_mb %r unsupported (need an integer 1..%d): using %d"
                              % (most, MAX_FILE_MB_MOST, DEFAULT_MAX_FILE_MB))
            most = DEFAULT_MAX_FILE_MB
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
            "max_file_mb": most,
            "max_file_bytes": most * 1024 * 1024,
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

    def describe(self):
        return (
            "account=%s shared_account=%s napcat=%s(%s) host=%s(%s) channel=%s media_mode=%s catchup=%s max_file_mb=%d"
            % (
                self.napcat["account_id"],
                self.napcat["shared_account"],
                self.napcat["url"],
                self.napcat["endpoint"],
                self.host["base_url"],
                self.host["endpoint"],
                self.host["channel_id"],
                self.media_mode,
                ("all/%dh" % self.catchup_lookback_hours if self.catchup_every
                 else "%s/%dh" % (",".join(sorted(self.catchup_routes)), self.catchup_lookback_hours)
                 if self.catchup_routes else "off"),
                self.napcat["max_file_mb"],
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

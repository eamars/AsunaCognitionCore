"""Channel kinds registered by channel plugins (e.g. @asuna/napcat-qq). The core names no platform.

A kind module knows one platform's id formats and adapter conventions:

  KIND, TITLE, IMAGE_HOSTS                     its id prefix, workspace and platform title, media hosts
  ACCOUNT, INBOUND_MENTION                     an account id; how the adapter writes a real @ in inbound text
  person_id(account), account_of(person)       qq:<account> and back
  scene_id(bot, kind, target), scene_parts(id) a scene id and back
  outbound_mention(account)                    how her @ reaches the adapter
  adapter_config(adapter, channel), strip_derived(adapter)
  FACES, STICKERS (optional)                   the platform's own faces by name -> id; whether it sends stickers
  HOME (optional)                              its conversations are trusted home ones (owner_private); default public

Scene and person ids start with their kind (`<kind>:…`), and a configured channel's id names its kind
(`channels.qq`).
"""
import importlib
from pathlib import Path
import sys

_KINDS = {}


def register(module):
    _KINDS[module.KIND] = module
    return module


def load(entries):
    """Import each plugin's kind module: [{'python': <directory>, 'module': <name>}]."""
    for entry in entries or ():
        directory = str(Path(entry['python']).resolve())
        if directory not in sys.path:
            sys.path.insert(0, directory)
        register(importlib.import_module(entry['module']))


def get(kind):
    return _KINDS.get(kind)


def of(identifier):
    """The kind of a scene or person id, by its prefix; None for local ids and unknown kinds."""
    head, sep, _ = str(identifier or '').partition(':')
    return _KINDS.get(head) if sep else None


def of_channel(channel_id):
    kind = _KINDS.get(channel_id)
    if kind is None:
        raise ValueError('CHANNEL_KIND_NOT_INSTALLED: ' + str(channel_id))
    return kind


def kinds():
    return list(_KINDS.values())


def person_ids(account):
    """Every platform person id a bare account number could be (qq:<account>, …)."""
    return [kind.person_id(account) for kind in _KINDS.values() if kind.ACCOUNT.fullmatch(str(account))]


def faces_of(identifier):
    """The platform faces (name -> id) of the kind a scene id belongs to; empty when it has none."""
    return dict(getattr(of(identifier), 'FACES', None) or {})


def home(identifier):
    """A scene or person of a kind whose conversations are trusted home ones (ADR-017)."""
    return bool(getattr(of(identifier), 'HOME', False))


def sends_stickers(identifier):
    return bool(getattr(of(identifier), 'STICKERS', False))


def sticker_of(item):
    """'custom', 'market' or None for a stored media item the adapter did not mark (asks each kind)."""
    for kind in _KINDS.values():
        found = getattr(kind, 'sticker_of', None)
        value = found(item) if found else None
        if value:
            return value
    return None


def image_hosts():
    """The media hosts the installed platforms deliver images from (vision's default allowlist)."""
    return [host for kind in _KINDS.values() for host in getattr(kind, 'IMAGE_HOSTS', ())]

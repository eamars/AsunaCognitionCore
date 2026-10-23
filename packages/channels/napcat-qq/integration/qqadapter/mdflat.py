"""Flatten a QQ `markdown` message element into the plain text a reader wants (0.15.0).

NapCat delivers a markdown message as `{"type": "markdown", "data": {"content": "<one string>"}}` -
no nested segments.  The same message usually also carries a few `text` segments, which are QQ's
*lossy* rendering of the same words (its italic rule eats underscores: `group_log_7d_1024.jsonl`
arrives as `grouplog7d_1024.jsonl`, backticks are stripped).  The markdown string is the lossless
original, so it wins; this module turns it into plain text and decides which `text` segments it
already contains.

Flatten rules (what a reader needs, nothing more):
  [@X](mqqapi://...)        -> @X                (a mention; the platform's own link, not a URL to show)
  [text](https://...)       -> text (https://...) (a real link: the URL is information)
  [text](mqqapi://...)      -> text
  **bold**, __bold__        -> bold               (`__x__` is left alone when x is a bare identifier:
                                                   `__init__.py` is a name, not emphasis)
  `code`, ```fence```       -> the code itself, backticks removed, its characters untouched
  # heading                 -> heading            (heading text kept, the hashes go)
  - item, * item            -> kept as written
  \\[  \\_  \\*  ...          -> the escaped character
  line breaks               -> kept
  underscores, single *     -> untouched (never emphasis here)
"""
import re

_PH_OPEN, _PH_CLOSE = "\ue000", "\ue001"
_ESC_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~<:])")
_CODE_RE = re.compile(r"```[^\n]*\n?(.*?)```|`([^`\n]+)`", re.S)
_LINK_RE = re.compile(r"(!?)\[([^\]\n]*)\]\(([^)\s]*)(?:[ \t]+\"[^\"]*\")?\)")
_HEAD_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.M)
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_UBOLD_RE = re.compile(r"(?<![A-Za-z0-9_])__(?=\S)(.+?)(?<=\S)__(?![A-Za-z0-9_])")
_BARE_NAME_RE = re.compile(r"[A-Za-z0-9_]+")
_PH_RE = re.compile(_PH_OPEN + r"([ce])(\d+)" + _PH_CLOSE)


def _link(match):
    _bang, text, url = match.groups()
    if url.startswith("mqqapi://"):
        if "/mention" in url and not text.startswith("@"):
            return "@" + text
        return text
    if not text or text == url:
        return url
    if not url:
        return text
    return "%s (%s)" % (text, url)


def _ubold(match):
    inner = match.group(1)
    if _BARE_NAME_RE.fullmatch(inner):
        return match.group(0)      # __init__ : an identifier, keep its underscores
    return inner


def flatten(content):
    """Markdown string -> plain text.  Never raises; returns "" for non-strings."""
    if not isinstance(content, str):
        return ""
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    escapes, codes = [], []

    def stash_escape(match):
        escapes.append(match.group(1))
        return "%sc%d%s" % (_PH_OPEN, len(escapes) - 1, _PH_CLOSE)

    def stash_code(match):
        codes.append(match.group(1) if match.group(1) is not None else match.group(2))
        return "%se%d%s" % (_PH_OPEN, len(codes) - 1, _PH_CLOSE)

    text = _ESC_RE.sub(stash_escape, text)
    text = _CODE_RE.sub(stash_code, text)
    text = _LINK_RE.sub(_link, text)
    text = _HEAD_RE.sub("", text)
    text = _BOLD_RE.sub(lambda m: m.group(1), text)
    text = _UBOLD_RE.sub(_ubold, text)

    def restore(match):
        kind, idx = match.group(1), int(match.group(2))
        if kind == "e":
            return _PH_RE.sub(restore, codes[idx]) if idx < len(codes) else ""
        return escapes[idx] if idx < len(escapes) else ""

    for _ in range(3):
        if _PH_OPEN not in text:
            break
        text = _PH_RE.sub(restore, text)
    return text.strip()


def norm(text):
    """Letters, digits and CJK only (case-folded): the comparison key for 'is this the same words'."""
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def covers(text_segment, md_norm, md_plain):
    """True when a `text` segment is already inside the markdown rendering (so it is dropped).

    Whitespace-only segments are separator noise.  A segment with no letters or digits at all
    (a lone punctuation mark) is dropped only if it literally occurs in the flattened markdown."""
    key = norm(text_segment)
    if key:
        return key in md_norm
    stripped = str(text_segment).strip()
    return not stripped or stripped in md_plain

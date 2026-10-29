"""ADR-097: the reading of what came back, from the count rows (memory_fires), in counts only (no text, word, heading,
query, id or place name).

Per place (numbered by her turns there, with its kind when one is set) and in all: turns from someone's line, cues and
cues a turn, her recalls in a cue's turn or the next one (and those whose query has the cue's word), her notes back by
word and by meaning, recall's lines from elsewhere (hers, others') and past versions, W6 (a recall that brought back
what the turn itself had not) and the items it added; and for each cue and note, the minutes since the last compaction
of that turn's DSH session, read from the profile's session logs as asuna-cache-readout reads them.

Usage: python tools/memory_fires_report.py [--days 14] [--config config/local.json] [--data <data>] [--profile P]
       [--no-sessions]
"""
import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from asuna import crossing              # noqa: E402
from asuna.config import DATA, load     # noqa: E402
from asuna.state import Store           # noqa: E402


def compactions(data, profile, since_ms):
    """{DSH session id: [the end times (ms) of its compactions]}, from the profile's session logs."""
    spec = importlib.util.spec_from_file_location('cache_readout', ROOT / '.agents/skills/asuna-cache-readout/cache_readout.py')
    readout = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(readout)
    found, _ = readout.sessions(readout.session_roots(data, profile), data, since_ms, readout.core_presets())
    out = {}
    for session in found:
        for event in session.events:
            if event.get('type') == 'compaction/end' and not (event.get('data') or {}).get('error'):
                out.setdefault(session.id, []).append(event.get('time') or 0)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default='config/local.json')
    parser.add_argument('--days', type=int, default=14)
    parser.add_argument('--data', type=Path, default=DATA, help='the data folder holding the DSH sessions')
    parser.add_argument('--profile', default='asuna-native')
    parser.add_argument('--no-sessions', action='store_true', help='leave out the compaction join')
    args = parser.parse_args()
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    store = Store(load(args.config))
    try:
        joined = None if args.no_sessions else compactions(args.data, args.profile, since.timestamp() * 1000)
        print(json.dumps(crossing.report(store, since.isoformat(), joined), ensure_ascii=False, indent=1))
    finally:
        store.close()


if __name__ == '__main__':
    main()

"""She lives on one clock (ADR-106): the zone a time is drawn on comes from `schedule_rules.her_zone` and nowhere else.
A call site that asks for a room's zone, or reads the deployment's `timezone` itself, draws a clock that is not hers
again; this is the check that the old resolvers do not come back."""
import re

from asuna import repo_files
from asuna.config import ROOT

SOURCES = ('src/asuna', 'tools')
# The resolver itself, and the worker's start record, which reports only whether the setting is set.
MAY_READ_THE_SETTING = {'src/asuna/schedule_rules.py', 'src/asuna/native_worker.py'}
GONE = re.compile(rb'\bscene_timezone\b|\bzone_of\(|\bpersona_timezone\b|\bpersona_zone\b|'
                  rb'persona_model import[^\n]*\btimezone\b|place_timezone')
READS_A_ZONE = re.compile(rb"""\.get\(\s*['"]timezone['"]|\[\s*['"]timezone['"]\s*\](?!\s*=[^=])""")   # a read, not a write


def sources():
    return [path for path in repo_files.files(ROOT, *SOURCES) if path.endswith('.py')]


def test_the_room_and_rhythm_resolvers_are_gone_and_nothing_reads_a_zone_but_her_zone():
    listed = sources()
    assert {'src/asuna/schedule_rules.py', 'src/asuna/context.py', 'tools/memory_pilot_report.py'} <= set(listed), \
        'the scan reached the core and the tools'
    found = []
    for path in listed:
        for n, line in enumerate((ROOT / path).read_bytes().splitlines(), 1):
            if GONE.search(line) or (READS_A_ZONE.search(line) and path not in MAY_READ_THE_SETTING):
                found.append('%s:%d' % (path, n))
    assert not found, 'draw a time on her clock with schedule_rules.her_zone(config), not on a room\'s: %s' % found

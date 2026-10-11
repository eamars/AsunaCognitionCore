"""Every persona preset in the repository can be condensed on demand (ADR-049), and declares what it mounts.

A persona's compaction group must carry DSH's `/compact` command: the program condenses a quiet group through it, and
without it the attempt answers `no_compact_command`. Each DSH plugin a preset mounts must be a peer dependency of its
package, so installing the persona brings it.
"""
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PRESETS = sorted([*ROOT.glob('packages/personas/*/cordis.patch.yml'), *ROOT.glob('tests/fixtures/personas/*/cordis.patch.yml')])


def plugins(node):
    """Every plugin row ({id?, name, ...}) anywhere in a patch document."""
    if isinstance(node, dict):
        if isinstance(node.get('name'), str):
            yield node
        for value in node.values():
            yield from plugins(value)
    elif isinstance(node, list):
        for value in node:
            yield from plugins(value)


def compaction_groups(node):
    """The plugin groups that isolate a compaction service (a character preset's compaction)."""
    if isinstance(node, dict):
        if node.get('name') == 'cordis:group' and (node.get('isolate') or {}).get('compaction'):
            yield node
        for value in node.values():
            yield from compaction_groups(value)
    elif isinstance(node, list):
        for value in node:
            yield from compaction_groups(value)


@pytest.mark.parametrize('patch', PRESETS, ids=lambda p: p.parent.name)
def test_every_compaction_group_carries_the_compact_command(patch):
    groups = list(compaction_groups(yaml.safe_load(patch.read_text(encoding='utf-8'))))
    assert groups, '%s mounts no compaction group' % patch
    for group in groups:
        names = [row.get('name') for row in group.get('config') or [] if isinstance(row, dict)]
        assert '@deepseek-ai/dsh-command-compact' in names, (
            '%s: add `- id: command-compact / name: \'@deepseek-ai/dsh-command-compact\'` to the compaction group' % patch)


@pytest.mark.parametrize('patch', PRESETS, ids=lambda p: p.parent.name)
def test_every_dsh_plugin_a_preset_mounts_is_declared(patch):
    used = {row['name'] for row in plugins(yaml.safe_load(patch.read_text(encoding='utf-8')))
            if row['name'].startswith('@deepseek-ai/')}
    declared = set((json.loads((patch.parent / 'package.json').read_text(encoding='utf-8')).get('peerDependencies') or {}))
    assert used <= declared, '%s: declare %s in peerDependencies' % (patch.parent / 'package.json', sorted(used - declared))

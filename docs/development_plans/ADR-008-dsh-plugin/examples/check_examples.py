"""Local artifact checks only. Not a deployed gate or a DSH integration test."""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ExampleChecks(unittest.TestCase):
    def setUp(self):
        self.core = json.loads((ROOT/'examples/core.package.json').read_text())
        self.persona = json.loads((ROOT/'examples/xiaoman.package.json').read_text())

    def test_both_are_explicit_unpublished_templates(self):
        for item in (self.core, self.persona):
            self.assertTrue(item['private'])
            self.assertEqual(item['dsh']['bundle']['patch'], './cordis.patch.yml')

    def test_native_client_metadata_is_core_only(self):
        self.assertIn('./client', self.core['exports'])
        self.assertEqual(self.core['dsh']['client']['platform'], 'web')
        self.assertNotIn('client', self.persona['dsh'])

    def test_core_does_not_depend_on_persona(self):
        self.assertNotIn('@asuna/xiaoman', self.core.get('peerDependencies', {}))
        self.assertIn('@asuna/cognition-core', self.persona['peerDependencies'])

    def test_distribution_lists_do_not_pack_runtime_roots(self):
        for item in (self.core, self.persona):
            for folder in item['files']:
                self.assertNotIn(folder.rstrip('/'), {'.runtime', 'node_modules', '.venv', 'config', '*', '**'})

    def test_md_relative_links(self):
        for file in ROOT.rglob('*.md'):
            text = file.read_text(encoding='utf-8')
            for target in re.findall(r'\]\(([^)]+)\)', text):
                if '://' in target or target.startswith('#'):
                    continue
                target = target.split('#', 1)[0]
                if target:
                    self.assertTrue((file.parent/target).exists(), f'{file}: {target}')

if __name__ == '__main__':
    unittest.main()

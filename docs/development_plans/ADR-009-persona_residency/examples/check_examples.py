"""ADR-009 本地示例检查：只检查本文件夹的示例、参考实现、链接与个人数据守卫。

不是部署闸门，不验证任何人格行为，也不连接 Mongo/DSH/模型。
运行：python docs/development_plans/ADR-009-persona_residency/examples/check_examples.py
"""
from datetime import timedelta
from pathlib import Path
import json
import re
import sys
import unittest

HERE = Path(__file__).resolve().parent
ADR = HERE.parent
sys.path.insert(0, str(HERE))
import affect_reference as ar  # noqa: E402

try:
    import jsonschema
except ImportError:  # 项目依赖里有 jsonschema；缺失时只跳过 schema 用例并明示
    jsonschema = None


def load(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def affect_case():
    fixture = load('affect-events.example.json')
    model = load('persona-model.example.json')['affect']
    return model, fixture


def legacy_oracle(model, events, amendments, moment):
    """独立写法的"旧账本"口径：关闭即按事件时刻回算（retroactive），作废整条清零。

    只对 moment ≥ 全部事件时刻有效（它不排除未来事件）。用于证明参考实现的
    retroactive 模式与一类常见旧账本脚本逐点一致。
    """
    voided = {a['target'] for a in amendments if a['op'] == 'void'}
    closed = {a['target'] for a in amendments if a['op'] == 'close'}
    fixed_ts = {a['target']: a['value'] for a in amendments if a['op'] == 'fix_ts'}
    fixed_kind = {a['target']: a['value'] for a in amendments if a['op'] == 'fix_kind'}
    val = arl = 0.0
    for event in events:
        start = ar.parse_ts(fixed_ts.get(event['id'], event['ts']))
        hours = max(0.0, (moment - start).total_seconds() / 3600.0)
        kind = fixed_kind.get(event['id'], event.get('kind') or '')
        if event.get('half'):
            half = float(event['half'])
        else:
            half = float(model['kinds'].get(kind, {}).get('half_h', model['default_half_h']))
        half_arl = float(event.get('half_arl') or model['arl_half_h'])
        hold = bool(event.get('open')) and event['id'] not in closed
        decay = 1.0 if hold else 0.5 ** (hours / half)
        if event['id'] in voided:
            continue
        val += float(event['val']) * decay
        arl += float(event['arl']) * 0.5 ** (hours / half_arl)
    clamp = model['clamp']
    return (max(clamp['val'][0], min(clamp['val'][1], val)),
            max(clamp['arl'][0], min(clamp['arl'][1], arl)))


def slug(heading):
    """GitHub 风格锚点：小写，去掉非字母数字/下划线/连字符/空格，空格变连字符。"""
    text = re.sub(r'[^\w\- ]', '', heading.strip().lower())
    return text.replace(' ', '-')


class Examples(unittest.TestCase):
    def test_json_examples_parse(self):
        for path in HERE.glob('*.json'):
            json.loads(path.read_text(encoding='utf-8'))

    @unittest.skipIf(jsonschema is None, 'jsonschema 未安装')
    def test_model_example_matches_schema(self):
        jsonschema.validate(load('persona-model.example.json'), load('persona-model.schema.json'))

    @unittest.skipIf(jsonschema is None, 'jsonschema 未安装')
    def test_model_schema_refuses_private_defaults(self):
        model = load('persona-model.example.json')
        schema = load('persona-model.schema.json')
        for bad in ({**model, 'rhythm': {'settle_at': '04:30', 'timezone': 'UTC'}},
                    {**model, 'policy_keys': {**model['policy_keys'], 'rhythm.timezone': {'type': 'string', 'what': 'x'}}}):
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(bad, schema)

    @unittest.skipIf(jsonschema is None, 'jsonschema 未安装')
    def test_decision_examples_match_delta_schema(self):
        schema = load('decision-delta.schema.json')
        jsonschema.Draft7Validator.check_schema(schema)
        for example in schema['examples']:
            jsonschema.validate(example, schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({'affect_ops': [{'op': 'void', 'event_id': 'ev-demo-1'}]}, schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({'affect': [{'val': 1, 'arl': 1, 'why': 'x'}]}, schema)

    def test_affect_expected_values(self):
        model, fixture = affect_case()
        for row in fixture['expected']:
            state = ar.project({**model, 'close_mode': row['close_mode']}, fixture['events'], fixture['amendments'], row['at'])
            self.assertAlmostEqual(state['val'], row['val'], delta=1e-9, msg=row)
            self.assertAlmostEqual(state['arl'], row['arl'], delta=1e-9, msg=row)
            self.assertEqual(state['open_count'], row['open_count'], msg=row)

    def test_retroactive_matches_independent_legacy_oracle(self):
        model, fixture = affect_case()
        events, amendments = fixture['events'], fixture['amendments']
        last = max(ar.parse_ts(e['ts']) for e in events)
        legacy_model = {**model, 'close_mode': 'retroactive'}
        for step in range(100):
            moment = last + timedelta(minutes=101 * step)
            state = ar.project(legacy_model, events, amendments, moment)
            expected = legacy_oracle(model, events, amendments, moment)
            self.assertAlmostEqual(state['val'], expected[0], delta=1e-6)
            self.assertAlmostEqual(state['arl'], expected[1], delta=1e-6)

    def test_close_modes_differ_and_future_events_are_excluded(self):
        model, fixture = affect_case()
        mid = [row for row in fixture['expected'] if 'note' in row]
        self.assertEqual(len({row['close_mode'] for row in mid}), 2)
        self.assertNotAlmostEqual(mid[0]['val'], mid[1]['val'], delta=1e-6)
        moment = ar.parse_ts(mid[0]['at'])
        later = [e for e in fixture['events'] if ar.parse_ts(e['ts']) > moment]
        self.assertTrue(later, '夹具应包含晚于中途时刻的事件')
        with_later = ar.project({**model, 'close_mode': 'from_close'}, fixture['events'], fixture['amendments'], moment)
        without = ar.project({**model, 'close_mode': 'from_close'},
                             [e for e in fixture['events'] if e not in later],
                             [a for a in fixture['amendments'] if a['target'] not in {e['id'] for e in later}], moment)
        self.assertAlmostEqual(with_later['val'], without['val'], delta=1e-9)

    def test_projection_visibility(self):
        model, fixture = affect_case()
        last = max(ar.parse_ts(e['ts']) for e in fixture['events'])
        state = ar.project(model, fixture['events'], fixture['amendments'], last)
        public = json.dumps(ar.describe(model, state, 'public'), ensure_ascii=False)
        private = json.dumps(ar.describe(model, state, 'owner_private'), ensure_ascii=False)
        for event in fixture['events']:
            self.assertNotIn(event['why'], public)
        for key in ('"val"', '"arl"', 'contributions', 'event_id'):
            self.assertNotIn(key, public)
        self.assertIn('contributions', private)
        for kind, spec in model['kinds'].items():
            if spec.get('tendency_visibility') != 'public':
                self.assertNotIn(spec['tendency'], public)

    def test_reference_gates(self):
        model, _ = affect_case()
        event = {'id': 'x', 'ts': '2026-01-01T00:00:00Z', 'val': 1, 'arl': 1, 'open': False}
        with self.assertRaises(ValueError):
            ar.project(model, [event], [{'target': 'x', 'op': 'void', 'at': '2026-01-01T01:00:00Z', 'why': ''}], '2026-01-02T00:00:00Z')
        with self.assertRaises(ValueError):
            ar.project(model, [event], [{'target': 'x', 'op': 'close', 'at': '2026-01-01T01:00:00Z'}], '2026-01-02T00:00:00Z')
        with self.assertRaises(ValueError):
            ar.project(model, [{**event, 'ts': '2026-01-01T00:00:00'}], [], '2026-01-02T00:00:00Z')

    def test_markdown_links_and_anchors(self):
        files = list(ADR.rglob('*.md'))
        anchors = {}
        for file in files:
            text = file.read_text(encoding='utf-8')
            anchors[file.resolve()] = {slug(h) for h in re.findall(r'^#{1,6} (.+)$', text, re.M)}
        for file in files:
            text = file.read_text(encoding='utf-8')
            for target in re.findall(r'\]\(([^)\s]+)\)', text):
                if '://' in target:
                    continue
                path, _, anchor = target.partition('#')
                resolved = (file.parent / path).resolve() if path else file.resolve()
                self.assertTrue(resolved.exists(), '%s → %s' % (file.name, target))
                if anchor and resolved.suffix == '.md':
                    self.assertIn(anchor, anchors[resolved], '%s → %s' % (file.name, target))

    def test_no_personal_data_patterns(self):
        long_number = re.compile(r'(?<![\d.])\d{7,}(?![\d.])')  # 小数部分不算
        private_ip = re.compile(r'\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b')
        email = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
        zone = re.compile(r'\b(?:Africa|America|Antarctica|Asia|Atlantic|Australia|Europe|Indian|Pacific)/[A-Za-z_]+')
        for file in ADR.rglob('*'):
            if not file.is_file() or file.suffix not in ('.md', '.json', '.py', '.ts'):
                continue
            text = file.read_text(encoding='utf-8')
            for match in long_number.finditer(text):
                self.assertEqual(len(match.group()), 64, '%s: 疑似账号类长数字' % file.name)  # 只允许 64 位占位哈希
            self.assertIsNone(private_ip.search(text), '%s: 私有地址' % file.name)
            self.assertIsNone(email.search(text), '%s: 邮箱' % file.name)
            self.assertIsNone(zone.search(text), '%s: 具体时区' % file.name)


if __name__ == '__main__':
    unittest.main()

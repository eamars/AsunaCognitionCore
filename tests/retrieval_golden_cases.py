"""Fixed synthetic corpus and queries for the retrieval golden file (ADR-009 T5.6).

``python tests/retrieval_golden_cases.py --record`` writes tests/fixtures/retrieval_golden.json
from the current ranking. It was recorded at the start of P5, before salience weights existed.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / 'tests/fixtures/retrieval_golden.json'
CORPUS = [
    ('g01', '他说周末想去海边看日出，要早点出门'), ('g02', '海边的风很大，记得带外套'),
    ('g03', '周末的计划改成在家整理书架'), ('g04', '书架上的旧书按颜色排好了'),
    ('g05', '他最喜欢的饮料是热可可，不加糖'), ('g06', '热可可要用牛奶煮才好喝'),
    ('g07', '下周三要交项目报告，还差图表'), ('g08', '项目报告的图表用柱状图更清楚'),
    ('g09', '他养了一只叫团子的猫'), ('g10', '团子最近不爱吃猫粮，换了鱼味的'),
    ('g11', '拼图拼到一半，缺了天空那一块'), ('g12', '一千片的拼图要拼好几个周末'),
    ('g13', '早上先看一眼待办再开始做事'), ('g14', '待办清单里还有给猫打疫苗'),
    ('g15', '他说日出的颜色像热可可'),
]
QUERIES = ['海边日出', '热可可', '项目报告图表', '猫', '拼图周末', '待办']


def seed(store):
    from asuna.config import character_id
    for i, (key, body) in enumerate(CORPUS):
        store.put('memory_units', {'_id': key, 'scope_key': 'scene:dm-a', 'policy_epoch': 1, 'status': 'active',
                                   'character_id': character_id(store.config), 'kind': 'chat_chunk',
                                   'body_markdown': body, 'epistemic_type': 'reported_speech', 'speaker': 'A',
                                   'scene_seq': 100 + i, 'occurred_at': f'2026-01-{i + 1:02d}T00:00:00+00:00',
                                   'source_event_ids': ['src-' + key], 'embedding_status': 'PENDING'})


def rank(retrieval, **kwargs):
    """Lexical-only ranking (the embedding call is disabled) so the golden file is deterministic."""
    def no_vector(*args, **kw):
        raise ConnectionError('golden: vector path disabled')
    retrieval.embed = no_vector
    out = {}
    for query in QUERIES:
        selected, _ = retrieval.search('scene:dm-a', 1, query, **kwargs)
        out[query] = [m['_id'] for m in selected if m['_id'].startswith('g')]
    return out


if __name__ == '__main__' and '--record' in sys.argv:
    sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
    import tempfile
    from conftest import isolated_database, drop_database, WORLD
    from asuna.config import load
    from asuna.evidence import Evidence
    from asuna.retrieval import Retrieval
    from asuna.state import Store
    config = load(); config['character_id'] = 'demo'
    store = Store(config, isolated_database('asuna_v2_test_golden'))
    try:
        store.migrate(); store.seed(WORLD); seed(store)
        retrieval = Retrieval(store, Evidence(Path(tempfile.mkdtemp()) / 'ev'))
        GOLDEN.write_text(json.dumps(rank(retrieval), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('recorded', GOLDEN)
    finally:
        drop_database(config, store.name)

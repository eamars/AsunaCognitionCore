"""A unit the embedding model refuses blocks no other; it is embedded from its opening part, else left to lexical recall."""
import httpx
import pytest

from asuna.retrieval import Retrieval


class FakeService:
    """An embedding endpoint whose context fits `limit` characters; `down` makes it unreachable."""
    def __init__(self, limit, down=False):
        self.limit, self.down, self.calls = limit, down, []

    def request(self, method, url, purpose, body=None, api_key=''):
        texts = body['input']
        self.calls.append(len(texts))
        if self.down:
            raise httpx.ConnectError('down')
        if any(len(text) > self.limit for text in texts):
            request = httpx.Request('POST', url)
            raise httpx.HTTPStatusError('400', request=request, response=httpx.Response(400, request=request))
        return {'data': [{'index': i, 'embedding': [1.0] * 768} for i in range(len(texts))]}


def units(store, bodies):
    for n, body in enumerate(bodies):
        store.db.memory_units.insert_one({'_id': 'mu-%d' % n, 'schema_version': 1, 'revision': 1, 'status': 'active',
                                          'embedding_status': 'PENDING', 'body_markdown': body, 'scope_key': 'scene:dm-a'})


def retrieval(store, service):
    r = Retrieval(store, None)
    r.http = service
    return r


def test_one_refused_unit_blocks_no_other_and_is_embedded_from_its_opening(store):
    units(store, ['短的一条'] * 20 + ['长' * 450])
    service = FakeService(limit=300)                       # the prefix + 450 characters is too long; 200 fits
    retrieval(store, service).index_pending()
    long = store.db.memory_units.find_one({'_id': 'mu-20'})
    assert long['embedding_status'] == 'READY' and long['embedding_opening_chars'] == 200
    assert store.db.memory_units.count_documents({'_id': {'$regex': '^mu-'}, 'embedding_status': 'READY'}) == 21
    assert 'embedding_opening_chars' not in store.db.memory_units.find_one({'_id': 'mu-0'})


def test_a_unit_refused_even_at_its_shortest_opening_is_marked_and_not_retried(store):
    units(store, ['短的一条', '长' * 500])
    service = FakeService(limit=50)                        # even the 100-character opening is too long
    r = retrieval(store, service)
    r.index_pending()
    assert store.db.memory_units.find_one({'_id': 'mu-0'})['embedding_status'] == 'READY'
    assert store.db.memory_units.find_one({'_id': 'mu-1'})['embedding_status'] == 'REFUSED'
    calls = len(service.calls)
    assert r.index_pending() == 0 and len(service.calls) == calls, 'nothing is retried under the same embedding route'


def test_an_unreachable_service_marks_nothing(store):
    units(store, ['短的一条'])
    with pytest.raises(httpx.ConnectError):
        retrieval(store, FakeService(limit=300, down=True)).index_pending()
    assert store.db.memory_units.find_one({'_id': 'mu-0'})['embedding_status'] == 'PENDING'


def test_one_round_of_indexing_covers_her_owner_private_memories(store):
    from asuna import visibility
    from asuna.memory_indexer import MemoryIndexer

    class Evidence:
        def record(self, kind, payload):
            pass

    indexer = MemoryIndexer(store, Evidence(), ['dm-a'])
    seen = []

    def index_pending(scope=None, epoch=None, stopping=None):
        seen.append((scope, epoch))
        indexer.stopping.set()
        return 0

    indexer.retrieval.index_pending = index_pending
    indexer.retrieval.ensure_index = lambda timeout=2: True
    indexer._run()
    private = visibility.owner_private_scope(store.config['chat']['persona'])
    assert (private, 1) in seen and seen[0][0] == store.db.scenes.find_one({'_id': 'dm-a'})['scope_key']

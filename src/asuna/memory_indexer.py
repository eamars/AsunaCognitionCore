"""Index persisted local dialogue off the generation thread; restart scans pending work."""
import threading
import traceback

import httpx

from .config import redact_text
from .memory import MemoryService
from .retrieval import Retrieval


class MemoryIndexer:
    def __init__(self, store, evidence, scene_id):
        self.store, self.evidence, self.scene_id = store, evidence, scene_id
        self.stopping = threading.Event()
        self.retrieval = Retrieval(store, evidence)
        self.retrieval.http.client.timeout = httpx.Timeout(10, connect=5)
        self.worker = threading.Thread(target=self._run, name='asuna-memory', daemon=True)

    def start(self):
        self.worker.start()
        return self

    def _run(self):
        try:
            index_ready = False
            while not self.stopping.is_set():
                try:
                    scene = self.store.db.scenes.find_one({'_id': self.scene_id})
                    chunks = MemoryService(self.store).chunk(self.scene_id)
                    count = self.retrieval.index_pending(scope=scene['scope_key'], epoch=scene['policy_epoch'], stopping=self.stopping)
                    if not index_ready:
                        index_ready = self.retrieval.ensure_index(timeout=2)
                    if chunks or count:
                        self.evidence.record('memory.indexed', {'scene_id': self.scene_id,
                            'chunk_ids': [m['_id'] for m in chunks], 'indexed': count, 'index_ready': index_ready})
                except Exception:
                    self.evidence.record('memory.index_error', {'scene_id': self.scene_id,
                        'traceback': redact_text(traceback.format_exc(), self.store.config)})
                self.stopping.wait(2)
        finally:
            self.retrieval.close()

    def close(self):
        self.stopping.set()
        self.worker.join(timeout=30)
        self.evidence.record('memory.stopped', {'worker_stopped': not self.worker.is_alive(),
                                               'pending_retried_on_restart': True})

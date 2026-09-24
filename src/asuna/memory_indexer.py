"""Index persisted local dialogue off the generation thread; restart scans pending work."""
import threading
import traceback

import httpx

from .config import redact_text
from .memory import MemoryService
from .retrieval import Retrieval


class MemoryIndexer:
    def __init__(self, store, evidence, scene_id, *, summary_lane=None, summary_scene=None, summary_scenes=None, summary_can_run=lambda: True):
        self.store, self.evidence, self.scene_id = store, evidence, scene_id
        self.scene_ids = [scene_id] if isinstance(scene_id, str) else list(scene_id)
        self.stopping = threading.Event()
        self.retrieval = Retrieval(store, evidence)
        self.retrieval.http.client.timeout = httpx.Timeout(10, connect=5)
        self.worker = threading.Thread(target=self._run, name='asuna-memory', daemon=True)
        self.summarizer = None
        # P2: 摘要跟着场景走——本机私聊和每个已授权群都要有自己的节奏与归属，
        # 不再只绑一个 scene_id（summary_scene 保留兼容旧接线）。
        scenes = list(summary_scenes) if summary_scenes else ([summary_scene] if summary_scene else [])
        if summary_lane and scenes:
            from .dialogue_summary import DialogueSummarizer
            self.summarizer = DialogueSummarizer(store, evidence, summary_lane, scenes, summary_can_run)

    def start(self):
        if self.summarizer:
            self.summarizer.initialize()
        self.worker.start()
        return self

    def _run(self):
        try:
            index_ready = False
            cursor = 0
            while not self.stopping.is_set():
                try:
                    scene_id = self.scene_ids[cursor % len(self.scene_ids)]
                    cursor += 1
                    scene = self.store.db.scenes.find_one({'_id': scene_id})
                    chunks = MemoryService(self.store).chunk(scene_id)
                    count = self.retrieval.index_pending(scope=scene['scope_key'], epoch=scene['policy_epoch'], stopping=self.stopping)
                    if not index_ready:
                        index_ready = self.retrieval.ensure_index(timeout=2)
                    if chunks or count:
                        self.evidence.record('memory.indexed', {'scene_id': scene_id,
                            'chunk_ids': [m['_id'] for m in chunks], 'indexed': count, 'index_ready': index_ready})
                except Exception:
                    self.evidence.record('memory.index_error', {'scene_id': self.scene_id,
                        'traceback': redact_text(traceback.format_exc(), self.store.config)})
                if self.summarizer and scene_id in self.summarizer.scene_ids:
                    try:
                        # 轮转到哪个场景就判断哪个场景：触发点由该场景自己的节奏算。
                        self.summarizer.tick(scene_id)
                    except Exception:
                        self.evidence.record('summary.error', {'scene_id': scene_id,
                            'traceback': redact_text(traceback.format_exc(), self.store.config)})
                self.stopping.wait(2)
        finally:
            self.retrieval.close()

    def close(self):
        self.stopping.set()
        self.worker.join(timeout=30)
        self.evidence.record('memory.stopped', {'worker_stopped': not self.worker.is_alive(),
                                               'pending_retried_on_restart': True})

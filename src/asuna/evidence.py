from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid
import httpx
from .config import validate_endpoint


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode()


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())


class Evidence:
    """One immutable directory per attempt. Persistence failures propagate before I/O."""
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=False)
        self.lock = threading.Lock()
        self.seq = 0
        self.previous = '0' * 64

    def record(self, kind: str, payload: dict) -> str:
        with self.lock:
            self.seq += 1
            event = {'seq': self.seq, 'type': kind, 'payload': payload, 'prev_hash': self.previous, 'time_ns': time.time_ns()}
            event['event_hash'] = sha(canonical(event))
            name = f'{self.seq:05d}-{kind}.json'
            write_json(self.root / name, event)
            self.previous = event['event_hash']
            return name


class LocalHttp:
    """Captures the exact serialized HTTP body submitted to a literal local endpoint."""
    def __init__(self, evidence: Evidence):
        self.evidence = evidence
        self.client = httpx.Client(timeout=httpx.Timeout(180, connect=10), follow_redirects=False, trust_env=False)

    def request(self, method: str, url: str, purpose: str, body=None, api_key: str = '') -> dict:
        validate_endpoint(url)
        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = 'Bearer ' + api_key
        call_id = str(uuid.uuid4())
        request = self.client.build_request(method, url, headers=headers, content=canonical(body) if body is not None else None)
        # Authorization headers are deliberately never persisted.
        ref = self.evidence.record('provider.request', {'call_id': call_id, 'purpose': purpose, 'method': method, 'url': url, 'body_utf8': request.content.decode(), 'body_sha256': sha(request.content), 'token_render_visibility': 'unavailable'})
        start = time.perf_counter()
        try:
            response = self.client.send(request)
            data = response.json()
            self.evidence.record('provider.response', {'call_id': call_id, 'request_ref': ref, 'status_code': response.status_code, 'body': data, 'duration_seconds': time.perf_counter() - start})
            response.raise_for_status()
            return data
        except Exception as exc:
            self.evidence.record('provider.error', {'call_id': call_id, 'type': type(exc).__name__, 'duration_seconds': time.perf_counter() - start})
            raise

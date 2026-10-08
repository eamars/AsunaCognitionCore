"""One running Host per database, across machines (ADR-020 M1).

The file lock in the machine's temp folder (config.database_lock) stops a second Host on one machine. This lease,
a document in the database itself, stops one on another machine. Its holder is this deployment's host id, kept in
the data folder: a restart, a replaced worker or a recreated container is the same holder and takes over at once;
another deployment waits until the lease expires (no renewal for LEASE_SECONDS) and is otherwise refused, told who
holds it. Expiry uses the database server's clock, so clocks on different machines need not agree.

A clean stop deletes the lease. Finding this deployment's own lease at start means the last Host did not stop by
itself: `left_behind` is then about when it was last alive (host_stops).
"""
import os
import socket
import threading
import uuid
from datetime import timedelta

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from .config import DATA
from .state import Denied

LEASE_SECONDS = 90
RENEW_SECONDS = 30
COLLECTION = 'host_leases'


def host_id(root=None):
    """This deployment's identity, created once in its data folder."""
    path = (root or DATA) / 'host-id'
    try:
        return path.read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        value = uuid.uuid4().hex
        path.write_text(value, encoding='utf-8')
        return value


class DatabaseLease:
    def __init__(self, config, *, persona=None, root=None, renew_seconds=RENEW_SECONDS):
        self.client = MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
                                  timeoutMS=10000)
        self.leases = self.client[config['database']][COLLECTION]
        self.me = host_id(root)
        self.holder = {'instance': self.me, 'host': socket.gethostname(), 'persona': persona, 'pid': os.getpid()}
        self.renew_seconds = renew_seconds
        self.stopping = threading.Event()
        self.thread = None
        self.left_behind = None

    def _expiry(self):
        return {'$add': ['$$NOW', LEASE_SECONDS * 1000]}

    def acquire(self):
        mine = self.leases.find_one({'_id': 'host', 'instance': self.me}, {'expires_at': 1})
        if mine and mine.get('expires_at'):
            self.left_behind = mine['expires_at'] - timedelta(seconds=LEASE_SECONDS)
        take = [{'$set': {**self.holder, 'since': '$$NOW', 'expires_at': self._expiry()}}]
        free_or_mine = {'$or': [{'$lt': ['$expires_at', '$$NOW']}, {'$eq': ['$instance', self.me]}]}
        if self.leases.update_one({'_id': 'host', '$expr': free_or_mine}, take).matched_count:
            return self                 # expired, or this deployment's own
        try:
            # No lease yet: insert one (an upsert may not filter with $expr). One that exists is someone else's.
            self.leases.update_one({'_id': 'host', 'instance': {'$exists': False}}, take, upsert=True)
        except DuplicateKeyError:
            held = self.leases.find_one({'_id': 'host'}) or {}
            raise Denied('DATABASE_IN_USE: %s on %s holds it until %s' % (
                held.get('persona'), held.get('host'), held.get('expires_at'))) from None
        return self

    def _renew(self):
        while not self.stopping.wait(self.renew_seconds):
            try:
                self.leases.update_one({'_id': 'host', 'instance': self.me},
                                       [{'$set': {'expires_at': self._expiry()}}])
            except Exception:
                pass                    # a missed renewal is retried; the lease outlives three of them

    def __enter__(self):
        self.acquire()
        self.thread = threading.Thread(target=self._renew, name='asuna-database-lease', daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=5)
        try:
            self.leases.delete_one({'_id': 'host', 'instance': self.me})
        finally:
            self.client.close()

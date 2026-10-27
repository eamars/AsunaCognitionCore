"""Scoped, hash-verified GridFS storage for bounded-document overflow.

Bucket `artifact_blobs` in the configured database (GridFS creates `.files`, `.chunks` and their indexes on the first
upload); the `artifacts` collection holds each blob's scope, size, SHA256, source ids and GridFS id. An upload writes
an audit intent, reads the bytes back to verify them, then commits the manifest; a failed check deletes the blob.
Reads need the operator view and a matching scope. Scoped erasure deletes the GridFS records, then marks each of the
scope's rows `storage` `erased` (ADR-105): whatever looks such a row up by its id answers with `ERASED_WORDS`, never
"not found". Ordinary BSON records stay under 1 MiB: callers store larger content here explicitly and keep the
reference; nothing is silently truncated. Back up both collections with the database. `put_stream` stores a file of
any size from an open handle: it hashes while it copies and verifies by reading back in pieces, never holding the
whole file in memory.
"""
import hashlib
import uuid
from gridfs import GridFSBucket
from .evidence import sha
from .state import Denied, now

STREAM_PIECE = 1024 * 1024          # what put_stream reads and verifies at a time
ERASED = 'erased'                   # a row's storage once a privacy erasure deleted its bytes (ADR-105)
# ADR-105's one sentence: the kind as she reads it (张图, 个文件), then when, on her clock.
ERASED_WORDS = '这%s被隐私清除删过（%s），字节已经不在了，拿不回来；不是没有内容。'
BYTES_MISSING = ('ARTIFACT_BYTES_MISSING: 这份登记着的字节不在存储里了（程序的问题，不是你的错）；不是没有内容。'
                 '重试也一样：不用这份，照实写进结果')


def erased(row):
    """Whether a privacy erasure deleted this row's bytes."""
    return (row or {}).get('storage') == ERASED


def erased_words(store, row, scene_id=None):
    """ADR-105's sentence for an erased row, its time on the clock of the conversation it is said in."""
    from . import local_time
    what = '张图' if (row or {}).get('kind') == 'image' else '个文件'
    return ERASED_WORDS % (what, local_time.stamp((row or {}).get('erased_at'), local_time.zone_of(store, scene_id)))


def refuse_erased(store, row, scene_id=None):
    """Raise the sentence for an erased row; the caller has already checked the row is in its fence, so the words say
    nothing about a row the caller may not see."""
    if erased(row):
        raise Denied('ARTIFACT_ERASED: ' + erased_words(store, row, scene_id))


class _Hashing:
    """A read-only handle that hashes and counts what is read through it."""

    def __init__(self, handle):
        self.handle, self.digest, self.size = handle, hashlib.sha256(), 0

    def read(self, size=-1):
        data = self.handle.read(size)
        self.digest.update(data)
        self.size += len(data)
        return data


class BlobStore:
    def __init__(self,store):self.store=store;self.bucket=GridFSBucket(store.db,bucket_name='artifact_blobs')

    def _scope_known(self,scope):
        # owner-private:<persona> holds source snapshots and job reports (ADR-009 §2.2); reads stay operator-only.
        if scope not in ('operator','global-safe') and not scope.startswith('owner-private:') and not self.store.db.scenes.find_one({'scope_key':scope}):raise Denied('ARTIFACT_SCOPE_UNKNOWN: 要存进的对话范围已经不存在；不是参数的问题，重试也一样：不存这份，照实写进结果')

    def put_stream(self,handle,scope:str,kind:str,*,source_ids=(),media_type=None,fields=None):
        """Store what an open binary handle holds, hashing while it copies; the stored bytes are read back in pieces
        and checked against that hash before the manifest is written. `fields`: more manifest fields (a name)."""
        self._scope_known(scope)
        key='blob-'+uuid.uuid4().hex
        self.store.audit(key,'artifact.upload_intent',{'kind':kind,'streamed':True},scope)
        source=_Hashing(handle)
        blob_id=self.bucket.upload_from_stream(key,source,metadata={'scope_key':scope,'kind':kind,'source_ids':list(source_ids)})
        try:
            digest,size=source.digest.hexdigest(),source.size
            check,seen=hashlib.sha256(),0
            stored=self.bucket.open_download_stream(blob_id)
            while True:
                piece=stored.read(STREAM_PIECE)
                if not piece:break
                check.update(piece);seen+=len(piece)
            if seen!=size or check.hexdigest()!=digest:raise ValueError('ARTIFACT_STORED_BYTES_MISMATCH: 存进去的字节读回来对不上，这次没有存；可以再试一次，还不行就照实写进结果')
            self.store.db['artifact_blobs.files'].update_one({'_id':blob_id},{'$set':{'metadata.sha256':digest}})
            doc={**(fields or {}),'_id':key,'scope_key':scope,'state':'DONE','kind':kind,'storage':'gridfs','gridfs_id':str(blob_id),'sha256':digest,'size':size,'source_ids':list(source_ids),'created_at':now()}
            if media_type:doc['media_type']=str(media_type)[:80]
            self.store.put('artifacts',doc,stream=key)
        except BaseException:
            self.bucket.delete(blob_id);raise
        return {'artifact_id':key,'sha256':digest,'size':size,'storage':'gridfs'}

    def put(self,data:bytes,scope:str,kind:str,*,source_ids=(),media_type=None):
        # created_at / media_type 只是给「本轮可引用」那份清单用的说明（新的在前、格式看得见）；
        # 真要以字节为准时仍然现读现认魔数，不拿这两个字段当依据。
        self._scope_known(scope)
        key='blob-'+uuid.uuid4().hex;digest=sha(data)
        self.store.audit(key,'artifact.upload_intent',{'sha256':digest,'size':len(data),'kind':kind},scope)
        blob_id=self.bucket.upload_from_stream(key,data,metadata={'scope_key':scope,'sha256':digest,'kind':kind,'source_ids':list(source_ids)})
        try:
            # Read the stored stream before permitting any dependent operation.
            observed=self.bucket.open_download_stream(blob_id).read()
            if len(observed)!=len(data) or sha(observed)!=digest:raise ValueError('ARTIFACT_STORED_BYTES_MISMATCH: 存进去的字节读回来对不上，这次没有存；可以再试一次，还不行就照实写进结果')
            doc={'_id':key,'scope_key':scope,'state':'DONE','kind':kind,'storage':'gridfs','gridfs_id':str(blob_id),'sha256':digest,'size':len(data),'source_ids':list(source_ids),'created_at':now()}
            if media_type:doc['media_type']=str(media_type)[:40]
            self.store.put('artifacts',doc,stream=key)
        except BaseException:
            self.bucket.delete(blob_id);raise
        return {'artifact_id':key,'sha256':digest,'size':len(data),'storage':'gridfs'}

    def put_once(self,data:bytes,scope:str,kind:str,*,source_ids=()):
        """Content-addressed: the same bytes in the same scope are stored once."""
        existing=self.store.db.artifacts.find_one({'sha256':sha(data),'scope_key':scope,'kind':kind,'state':'DONE','storage':'gridfs'})
        if existing:return {'artifact_id':existing['_id'],'sha256':existing['sha256'],'size':existing['size'],'storage':'gridfs','deduplicated':True}
        return self.put(data,scope,kind,source_ids=source_ids)

    def _readable(self,key,scope):
        """The row of `key` if its bytes may be read in `scope`: refused when it is not there or not in the scope, and,
        only then, with ADR-105's sentence when an erasure deleted its bytes."""
        item=self.store.db.artifacts.find_one({'_id':key,'state':'DONE'})
        if not item or item['scope_key'] not in ('global-safe',scope):raise Denied('ARTIFACT_SCOPE_DENIED: 没有这份文件，或它不在这个对话的范围里；照抄这个对话里给出的 artifact_id')
        scene=self.store.db.scenes.find_one({'scope_key':item['scope_key']},{'_id':1})
        refuse_erased(self.store,item,(scene or {}).get('_id'))
        if item.get('storage')!='gridfs':raise Denied('ARTIFACT_SCOPE_DENIED: 没有这份文件，或它不在这个对话的范围里；照抄这个对话里给出的 artifact_id')
        return item

    def _open(self,item):
        from bson import ObjectId
        from gridfs import NoFile
        try:return self.bucket.open_download_stream(ObjectId(item['gridfs_id']))
        except NoFile:raise ValueError(BYTES_MISSING) from None

    def get(self,key,scope,*,operator=False):
        if not operator:raise Denied('ARTIFACT_OPERATOR_VIEW_REQUIRED')
        item=self._readable(key,scope)
        data=self._open(item).read()
        if len(data)!=item['size'] or sha(data)!=item['sha256']:raise ValueError('ARTIFACT_HASH_MISMATCH: 存着的这份文件和登记的校验值对不上（存储损坏）；不是参数的问题，重试也一样：不用这份，照实写进结果')
        return data

    def get_range(self,key,scope,offset,length,*,operator=False):
        """`length` bytes from `offset` of a stored blob (fewer at its end), read with a seek: a piece of a large file
        without reading the rest. The whole file's hash is the reader's to check."""
        if not operator:raise Denied('ARTIFACT_OPERATOR_VIEW_REQUIRED')
        stream=self._open(self._readable(key,scope))
        stream.seek(int(offset))
        return stream.read(int(length))

    def erase_scope(self,scope,deletion=None):
        """Delete every stored byte of `scope`, then mark each of its rows whose bytes are gone (`gridfs`, and
        `removed`: an expired file must not be fetched again either) `erased`, by the row's own scope, so a row whose
        bytes were already missing is marked too. The row keeps its name, size, sender and when (ADR-105). Run again
        after a stop, it finishes both. Returns the number of GridFS files deleted."""
        count=0
        for item in self.store.db.artifact_blobs.files.find({'metadata.scope_key':scope},{'_id':1}):
            self.bucket.delete(item['_id']);count+=1
        self.store.db.artifacts.update_many({'scope_key':scope,'storage':{'$in':['gridfs','removed']}},
                                            {'$set':{'storage':ERASED,'erased_at':now(),'deletion_id':deletion},
                                             '$unset':{'gridfs_id':''}})
        return count

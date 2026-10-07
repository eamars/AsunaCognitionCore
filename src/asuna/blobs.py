"""Scoped, hash-verified GridFS storage for bounded-document overflow.

Bucket `artifact_blobs` in the configured database (GridFS creates `.files`, `.chunks` and their indexes on the first
upload); the `artifacts` collection holds each blob's scope, size, SHA256, source ids and GridFS id. An upload writes
an audit intent, reads the bytes back to verify them, then commits the manifest; a failed check deletes the blob.
Reads need the operator view and a matching scope. Scoped erasure deletes the GridFS records before redacting the
manifests. Ordinary BSON records stay under 1 MiB: callers store larger content here explicitly and keep the
reference; nothing is silently truncated. Back up both collections with the database.
"""
import uuid
from gridfs import GridFSBucket
from .evidence import sha
from .state import Denied, now


class BlobStore:
    def __init__(self,store):self.store=store;self.bucket=GridFSBucket(store.db,bucket_name='artifact_blobs')

    def put(self,data:bytes,scope:str,kind:str,*,source_ids=(),media_type=None):
        # created_at / media_type 只是给「本轮可引用」那份清单用的说明（新的在前、格式看得见）；
        # 真要以字节为准时仍然现读现认魔数，不拿这两个字段当依据。
        # owner-private:<persona> holds source snapshots and job reports (ADR-009 §2.2); reads stay operator-only.
        if scope not in ('operator','global-safe') and not scope.startswith('owner-private:') and not self.store.db.scenes.find_one({'scope_key':scope}):raise Denied('ARTIFACT_SCOPE_UNKNOWN: 要存进的对话范围已经不存在；不是参数的问题，重试也一样：不存这份，照实写进结果')
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

    def get(self,key,scope,*,operator=False):
        if not operator:raise Denied('ARTIFACT_OPERATOR_VIEW_REQUIRED')
        item=self.store.db.artifacts.find_one({'_id':key,'state':'DONE','storage':'gridfs'})
        if not item or item['scope_key'] not in ('global-safe',scope):raise Denied('ARTIFACT_SCOPE_DENIED: 没有这份文件，或它不在这个对话的范围里；照抄这个对话里给出的 artifact_id')
        from bson import ObjectId
        data=self.bucket.open_download_stream(ObjectId(item['gridfs_id'])).read()
        if len(data)!=item['size'] or sha(data)!=item['sha256']:raise ValueError('ARTIFACT_HASH_MISMATCH: 存着的这份文件和登记的校验值对不上（存储损坏）；不是参数的问题，重试也一样：不用这份，照实写进结果')
        return data

    def erase_scope(self,scope):
        count=0
        for item in self.store.db.artifact_blobs.files.find({'metadata.scope_key':scope},{'_id':1}):
            self.bucket.delete(item['_id']);count+=1
        return count

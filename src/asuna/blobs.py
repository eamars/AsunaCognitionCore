"""Scoped, hash-verified GridFS storage for bounded-document overflow."""
import uuid
from gridfs import GridFSBucket
from .evidence import sha
from .state import Denied


class BlobStore:
    def __init__(self,store):self.store=store;self.bucket=GridFSBucket(store.db,bucket_name='artifact_blobs')

    def put(self,data:bytes,scope:str,kind:str,*,source_ids=()):
        if scope not in ('operator','global-safe') and not self.store.db.scenes.find_one({'scope_key':scope}):raise Denied('ARTIFACT_SCOPE_UNKNOWN')
        key='blob-'+uuid.uuid4().hex;digest=sha(data)
        self.store.audit(key,'artifact.upload_intent',{'sha256':digest,'size':len(data),'kind':kind},scope)
        blob_id=self.bucket.upload_from_stream(key,data,metadata={'scope_key':scope,'sha256':digest,'kind':kind,'source_ids':list(source_ids)})
        try:
            # Read the stored stream before permitting any dependent operation.
            observed=self.bucket.open_download_stream(blob_id).read()
            if len(observed)!=len(data) or sha(observed)!=digest:raise ValueError('ARTIFACT_STORED_BYTES_MISMATCH')
            self.store.put('artifacts',{'_id':key,'scope_key':scope,'state':'DONE','kind':kind,'storage':'gridfs','gridfs_id':str(blob_id),'sha256':digest,'size':len(data),'source_ids':list(source_ids)},stream=key)
        except BaseException:
            self.bucket.delete(blob_id);raise
        return {'artifact_id':key,'sha256':digest,'size':len(data),'storage':'gridfs'}

    def get(self,key,scope,*,operator=False):
        if not operator:raise Denied('ARTIFACT_OPERATOR_VIEW_REQUIRED')
        item=self.store.db.artifacts.find_one({'_id':key,'state':'DONE','storage':'gridfs'})
        if not item or item['scope_key'] not in ('global-safe',scope):raise Denied('ARTIFACT_SCOPE_DENIED')
        from bson import ObjectId
        data=self.bucket.open_download_stream(ObjectId(item['gridfs_id'])).read()
        if len(data)!=item['size'] or sha(data)!=item['sha256']:raise ValueError('ARTIFACT_HASH_MISMATCH')
        return data

    def erase_scope(self,scope):
        count=0
        for item in self.store.db.artifact_blobs.files.find({'metadata.scope_key':scope},{'_id':1}):
            self.bucket.delete(item['_id']);count+=1
        return count

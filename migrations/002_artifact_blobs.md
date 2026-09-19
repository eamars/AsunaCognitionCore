# Scoped large artifacts

`BlobStore` uses PyMongo GridFSBucket in the configured isolated database, bucket `artifact_blobs`. GridFS owns `artifact_blobs.files` and `artifact_blobs.chunks` and their standard indexes; they are created on the first real upload. `artifacts` stores scope, byte size, SHA256, source IDs and GridFS identifier.

Uploads write an audit intent, read back and verify stored bytes, then commit the manifest. Failed verification deletes the blob. Reads require the operator view and matching scope. Scoped erasure deletes file/chunk records before redacting manifests. Include both collections in database backups; never copy them into an old database.

Ordinary BSON records remain limited to 1 MiB. Provider bodies above that threshold use this store and retain full local audit evidence; general application callers must store oversized content explicitly and reference the manifest. No silent truncation is performed.

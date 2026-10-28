"""A unit run reaches no database server (ADR-104).

Every MongoDB client the run makes, in the test process and in every Python process it starts with its environment
(this folder is on their PYTHONPATH, ASUNA_UNIT_RUN=1), is an in-process stand-in (mongomock) over one shared store,
whatever address it is given: no socket is ever opened. It is a stand-in for the code that still reads MongoDB
directly, removed when the unit run moves to the store's in-memory adapter; it is never the reference of what a query
means.
"""
import os

if os.environ.get('ASUNA_UNIT_RUN') == '1':
    import mongomock
    import mongomock.gridfs
    import pymongo
    from mongomock.store import ServerStore

    _STORE = ServerStore()

    class InProcessClient(mongomock.MongoClient):
        """A client over the run's one in-process store; the address is kept, never connected to."""
        unit_run = True

        class options:                  # what pymongo's GridFS reads of a client: no operation timeout set
            timeout = None

        def __init__(self, host=None, port=None, *args, **kwargs):
            kwargs.pop('_store', None)
            super().__init__(host, port, *args, _store=_STORE, **kwargs)

    pymongo.MongoClient = InProcessClient
    mongomock.gridfs.enable_gridfs_integration()

    # What the stand-in does not have, it does not pretend to check: a collection's `$jsonSchema` validator is kept by
    # MongoDB only; the tests of what it refuses are in the harness's skip list.
    _create_collection = mongomock.database.Database.create_collection

    def create_collection(self, name, validator=None, **kwargs):
        return _create_collection(self, name, **kwargs)
    mongomock.database.Database.create_collection = create_collection

    # `$lookup` by localField/foreignField with a pipeline of `$project` stages only (MongoDB 5's concise form, the
    # one the core uses): the plain lookup, then each joined record projected. Any other pipeline stays refused.
    import mongomock.aggregate as _aggregate
    _lookup = _aggregate._PIPELINE_HANDLERS['$lookup']

    def lookup(in_collection, database, options):
        pipeline = options.get('pipeline')
        if pipeline is None or 'let' in options or 'localField' not in options or \
                any(set(stage) != {'$project'} for stage in pipeline):
            return _lookup(in_collection, database, options)
        joined = _lookup(in_collection, database, {k: v for k, v in options.items() if k != 'pipeline'})
        for doc in joined:
            for stage in pipeline:
                doc[options['as']] = _aggregate._handle_project_stage(doc[options['as']], database, stage['$project'])
        return joined
    _aggregate._PIPELINE_HANDLERS['$lookup'] = lookup

    # `$strLenCP`: a string's length in code points, which is what Python's len counts; a non-string is refused, as
    # MongoDB refuses it.
    _string_operator = _aggregate._Parser._handle_string_operator

    def string_operator(self, operator, values):
        if operator != '$strLenCP':
            return _string_operator(self, operator, values)
        value = self.parse(values[0] if isinstance(values, list) and len(values) == 1 else values)
        if not isinstance(value, str):
            raise mongomock.OperationFailure('$strLenCP requires a string argument, found: %s' % type(value).__name__)
        return len(value)
    _aggregate._Parser._handle_string_operator = string_operator

    # pymongo 4.16's bulk UpdateOne/ReplaceOne hand the builder `sort=None`; one with a real sort stays refused.
    _builder = mongomock.collection.BulkOperationBuilder
    for _name in ('add_update', 'add_replace'):
        def _without_sort(self, *args, _plain=getattr(_builder, _name), sort=None, **kwargs):
            if sort is not None:
                raise NotImplementedError('the stand-in has no sorted bulk update')
            return _plain(self, *args, **kwargs)
        setattr(_builder, _name, _without_sort)

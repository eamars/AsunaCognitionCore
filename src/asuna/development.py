"""Schemas for the native Host publication floor; no second publisher."""
DEVELOPMENT_TOOLS = [
    {'name':'development_files','description':'Inspect the persistent candidate connected to this Asuna project.', 'parameters':{}},
    {'name':'development_read','description':'Read a UTF-8 project file from the candidate.',
     'parameters':{'path':{'type':'string','required':True}}},
    {'name':'development_write','description':'Write a UTF-8 project file in the candidate; changes are not active until publish.',
     'parameters':{'path':{'type':'string','required':True},'text':{'type':'string','required':True},'overwrite':{'type':'boolean'}}},
    {'name':'development_run','description':'Run a command in the candidate and return raw stdout, stderr and exit status, including failures.',
     'parameters':{'argv':{'type':'array','items':{'type':'string'},'required':True}}},
    {'name':'development_database_read','description':'Read unredacted records from the existing real Asuna database, bound to this local owner development task. No public database endpoint.',
     'parameters':{'collection':{'type':'string','required':True},
                   'filter':{'type':'object','additionalProperties':True},
                   'projection':{'type':'object','additionalProperties':True},
                   'skip':{'type':'integer'},'limit':{'type':'integer'}}},
    {'name':'development_publish','description':'Freeze this candidate, perform minimum non-consuming boot probe, and activate a bootable snapshot. Returns the actual probe result.',
     'parameters':{'reason':{'type':'string'}}},
]
DEVELOPMENT_NAMES = {tool['name'] for tool in DEVELOPMENT_TOOLS}
# ADR-009 §7.4: a persona runs her own published jobs from an owner development task.
# Granted with development tools; the result carries status, counts and report ids only.
# Read and analyse only (ADR-011 §5.2): her identity data is written by the character brain alone.
PERSONA_JOB_TOOLS = [
    {'name': 'persona_job_run', 'description': 'Run one of the selected persona package\'s published jobs in the sandbox, '
     'read and analyse only: it is always a dry run, so documents, parameters, memories and mood are never written from here '
     '(the character writes those herself). Returns status, exit code, counts and report artifact ids only; reports are read in the memory tab.',
     'parameters': {'job': {'type': 'string', 'required': True},
                    'args': {'type': 'object', 'additionalProperties': True}}},
]
for _tool in DEVELOPMENT_TOOLS:
    _tool['parameters']['project'] = {'type': 'string',
        'description': 'Authorized project ID; defaults to the selected persona project. Use core for cognition runtime changes.'}
DEVELOPMENT_TOOLS[0]['parameters'].update({
    'prefix': {'type': 'string', 'description': 'Optional relative path prefix'},
    'offset': {'type': 'integer'}, 'limit': {'type': 'integer', 'description': 'Page size, maximum 100'},
})

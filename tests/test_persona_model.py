

def test_every_key_a_package_may_default_is_in_the_schema_with_its_limits():
    """A package may default a core-writable key, and the schema validates the package: the two lists must agree
    (ADR-077 fact check: four heartbeat keys were declared but refused by the schema)."""
    from asuna import persona_model
    for key, spec in persona_model.CORE_WRITABLE_KEYS.items():
        node = persona_model.SCHEMA
        for part in key.split('.'):
            node = (node.get('properties') or {}).get(part)
            assert node is not None, '%s is declared but the schema has no %s' % (key, part)
        types = node['type'] if isinstance(node['type'], list) else [node['type']]
        assert spec['type'] in types, key
        assert (node.get('minimum'), node.get('maximum')) == (spec.get('min'), spec.get('max')), key


def test_the_words_a_package_gives_are_never_policy_keys():
    """ADR-110: a persona's words (read from the model only) change by publishing the package, inside the schema's
    bounds; declared as a policy key, a set_policy value would be ignored without a word."""
    import pytest
    from asuna import persona_model
    for key in persona_model.PACKAGE_WORDS:
        node = persona_model.SCHEMA
        for part in key.split('.'):
            node = (node.get('properties') or {}).get(part)
        assert node and node['type'] == 'string' and node.get('maxLength'), key
        model = {'model_version': 1, 'persona': {'id': 'p', 'display_name': 'p'},
                 'policy_keys': {key: {'type': 'string', 'what': 'x'}}}
        with pytest.raises(persona_model.PersonaModelError, match='policy_keys may not declare'):
            persona_model.validate(model, 'p')

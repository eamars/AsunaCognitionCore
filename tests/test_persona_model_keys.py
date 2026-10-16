"""Her review tag is a persona-model value (ADR-071): the schema allows it, so a persona package that sets it loads.
Found by her before publishing (2026-10-16): without it the model failed only at the next restart's load."""
import jsonschema

from asuna import persona_model


def test_her_review_tag_is_a_persona_model_value():
    model = {'model_version': 1, 'persona': {'id': 'p', 'display_name': 'P'}, 'self_review': {'tag': '标签'}}
    jsonschema.validate(model, persona_model.SCHEMA)
    assert persona_model.effective(model, 'self_review.tag') == '标签'

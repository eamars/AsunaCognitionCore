"""A turn of hers that fails in the program is told to the developer (once a day per failure, counted) and to her
(once, at her next turn there) (ADR-076 R4)."""

from asuna import faults

TRACE = 'Traceback (most recent call last):\n  File "x.py", line 1\nasuna.state.Denied: NATIVE_BINDING_IDENTITY_CHANGED'


def test_a_failure_is_named_by_its_code_or_else_by_its_class():
    assert faults.cause(TRACE) == 'NATIVE_BINDING_IDENTITY_CHANGED'
    assert faults.cause('Traceback\nKeyError: \'x\'') == 'KeyError'
    assert faults.cause('') == 'unknown'



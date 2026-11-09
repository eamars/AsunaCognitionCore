"""ADR-119 F1: a picture read that fails is never an empty list. `offer` raises, and the turn's block says it was not
read (context.py, outbound_media.OFFER_UNREAD) instead of disappearing, which reads as "no picture"."""
import pytest

from asuna import outbound_media


def test_a_failed_picture_read_raises_instead_of_offering_nothing(monkeypatch):
    def broken(*args, **kwargs):
        raise ConnectionError('store down')
    monkeypatch.setattr(outbound_media, 'target_allowed', lambda *a: (True, None))
    monkeypatch.setattr(outbound_media, 'own_only', lambda *a: True)
    monkeypatch.setattr(outbound_media, '_images', broken)
    with pytest.raises(ConnectionError):
        outbound_media.offer(object(), {}, {'_id': 's', 'scope_key': 'scene:s'}, 'public')
    for words in (outbound_media.OFFER_UNREAD, outbound_media.OWN_UNREAD):
        assert '不是「没有图」' in words and '也不代表' in words

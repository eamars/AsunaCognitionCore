"""Her words where only reply speaks (ADR-064 phase 2): a FakeTurn call that sends them as text parts."""


def said(*texts, **options):
    return ('reply', {'parts': [{'kind': 'text', 'text': text} for text in texts], **options})

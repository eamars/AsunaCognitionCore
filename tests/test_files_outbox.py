"""ADR-092: files to a QQ group through the outbox -- registration from a task folder, the offer, speak's file part,
the claim against the adapter's declared limit, the bytes in pieces, the receipt and her record, and the 7 days the
bytes are kept. Failure paths first."""

import re


from asuna import outbound_files


def test_the_type_comes_from_the_bytes():
    sniff = outbound_files.sniff
    docx = b'PK\x03\x04' + b'\x00' * 26 + b'[Content_Types].xml' + b'\x00' * 40 + b'word/document.xml'
    assert sniff(docx) == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    assert sniff(b'PK\x03\x04' + b'\x00' * 26 + b'[Content_Types].xml xl/workbook.xml').endswith('spreadsheetml.sheet')
    assert sniff(b'PK\x03\x04' + b'\x00' * 26 + b'mimetypeapplication/epub+zip') == 'application/epub+zip'
    assert sniff(b'PK\x03\x04plain zip') == 'application/zip'
    cases = {b'%PDF-1.7': 'application/pdf', b'\x89PNG\r\n\x1a\nxx': 'image/png', b'\xff\xd8\xffxx': 'image/jpeg',
             b'GIF89a': 'image/gif', b'RIFF\x00\x00\x00\x00WEBPVP8 ': 'image/webp', b'\x1f\x8b\x08': 'application/gzip',
             b"7z\xbc\xaf\x27\x1c\x00": 'application/x-7z-compressed', b'Rar!\x1a\x07\x00': 'application/vnd.rar',
             b'ID3\x04': 'audio/mpeg', b'\xff\xfb\x90': 'audio/mpeg', b'\x00\x00\x00\x18ftypmp42': 'video/mp4',
             b'\x00\x00\x00\x18ftypM4A ': 'audio/mp4', b'OggS\x00': 'audio/ogg', b'RIFF\x00\x00\x00\x00WAVEfmt ': 'audio/wav'}
    for head, want in cases.items():
        assert sniff(head) == want, (head, sniff(head))
    assert sniff('<?xml version="1.0"?>\n<svg xmlns="x"></svg>'.encode(), whole=True) == 'image/svg+xml'
    assert sniff(b'<!DOCTYPE html><html></html>', whole=True) == 'text/html'
    assert sniff(b'{"a": [1, 2]}', whole=True) == 'application/json'
    assert sniff(b'{not json', whole=True) == 'text/plain'
    assert sniff('中文的一段话'.encode(), whole=True) == 'text/plain'
    assert sniff('中文'.encode()[:-1]) == 'text/plain'                  # a character cut at the sample's end
    assert sniff('中文'.encode()[:-1], whole=True) is None              # but not at the file's end
    assert sniff(b'\xff\xfe\x00\x00weird') is None and sniff(b'\xff\xf1\x50') is None      # AAC is not MP3


def test_a_file_that_did_not_go_says_why_in_her_words_never_in_a_code():
    from asuna import own_mute
    words = outbound_files.failure_words
    receipt = lambda **response: {'platform_receipt': {'response': response}}
    assert words(receipt(reason=own_mute.REASON, platform='sendMsg result 120')) == own_mute.FAILED_WORDS
    assert words({'failure': 'FILE_BYTES_EXPIRED', 'failure_detail': '字节过期了'}) == '没发出去：字节过期了'
    assert words({'failure': 'CHANNEL_DOES_NOT_DECLARE_FILE'}) == '没发出去：这条腿发不了文件'
    assert words(receipt(reason='file_private_target_not_supported')) == '没发出去：文件只发得进群，私聊发不了'
    assert words(receipt(reason='file_fetch_file_bytes_expired')) == '没发出去：适配器没取到文件的字节（不是你的错）'
    for reason in [*outbound_files.ADAPTER_WORDS, 'file_something_new', '']:
        said = words(receipt(reason=reason))
        assert said.startswith('没发出去：') and not re.search(r'[a-z]+_[a-z_]+', said), (reason, said)



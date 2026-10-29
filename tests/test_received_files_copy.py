"""ADR-102 sections 7 and 8, only what would fail silently and costly: a copy in /task/received cannot be started as
a program, a hostile name cannot leave the folder, the copies go with the bytes (expiry and erasure), and a file
forwarded from /task keeps where it came from."""


from asuna import received_files as rf


def test_a_hostile_name_stays_in_the_folder_and_is_never_a_device():
    assert rf.safe_name('..\\..\\Windows\\evil.txt') == 'evil.txt'
    assert rf.safe_name('../../etc/passwd') == 'passwd'
    assert rf.safe_name('CON.txt') == '_CON.txt' and rf.safe_name('nul') == '_nul'
    assert rf.safe_name('a?b:c.txt') == 'a_b_c.txt' and rf.safe_name('notes. ') == 'notes'
    long = rf.safe_name('长' * 200 + '.txt')
    assert len(long.encode('utf-8')) <= rf.NAME_BYTES and long.endswith('.txt')



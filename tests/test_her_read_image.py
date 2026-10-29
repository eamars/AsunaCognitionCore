"""Both brains share read_image (ADR-011 §5.3 as amended): she looks at a picture in her own turn, under the same
fences and storage as the action brain, when her own route takes images and the conversation has one to pull."""




def test_an_expired_link_says_retrying_cannot_help_and_a_server_error_may_pass():
    from asuna.vision import _fetch_failed
    expired = str(_fetch_failed(400, '{"retcode":-5503007,"retmsg":"download url has expired"}'))
    assert expired.startswith('IMAGE_FETCH_FAILED: 图片主机回了 HTTP 400') and '重试也一样' in expired
    assert '过一会儿再试一次' in str(_fetch_failed(503))



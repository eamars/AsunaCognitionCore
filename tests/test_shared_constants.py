"""ADR-119 F6: a fact both sides need has one Python source; where a side cannot import it (the plugin's JavaScript,
a channel package that stays independent), that side keeps a copy and this test says when the copy drifts. A secret
pattern that drifted would let a credential be saved as plain text with nothing said."""
import re

from asuna import channels, native_settings, sandbox
from asuna.config import CHANNEL_PORT, ROOT


def read(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


def number(relative, pattern):
    found = re.search(pattern, read(relative))
    assert found, '%s: %s not found' % (relative, pattern)
    return int(found.group(1))


def test_the_plugin_refuses_the_same_secret_keys_the_worker_does():
    found = re.search(r'const SECRET_KEY = /(.+)/i;', read('packages/cognition-core/src/settings.js'))
    assert found and found.group(1) == native_settings.SECRET_KEY.pattern


def test_the_plugin_defaults_to_the_worker_s_channel_port():
    assert number('packages/cognition-core/src/index.js', r'deployment\.channel_port \?\? (\d+)') == CHANNEL_PORT


def test_every_channel_client_keeps_the_channel_api_s_text_limit():
    assert number('packages/channels/dsh-peer/src/bridge.js', r'const TEXT_LIMIT = (\d+);') == channels.MAX_TEXT
    assert number('packages/channels/qq-bot/src/bridge.js', r'const TEXT_LIMIT = (\d+);') == channels.MAX_TEXT
    assert number('packages/channels/napcat-qq/integration/qqadapter/inbound.py', r'\nMAX_TEXT = (\d+)') == channels.MAX_TEXT


def test_the_plugin_refuses_the_same_argv_length_the_sandbox_does():
    assert number('packages/cognition-core/src/floor.js', r"args\.argv\.join\(''\)\.length > (\d+)") == sandbox.ARGV_CHARS

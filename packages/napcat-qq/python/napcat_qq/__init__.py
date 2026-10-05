"""QQ through NapCat, as a channel kind of the Asuna core (asuna/channel_kinds.py).

The core names no platform. Everything it needs to know about QQ ids, the adapter's text
conventions and the adapter's derived settings is here; the adapter itself is in ../../integration.
"""
import re

KIND = 'qq'                       # scene ids qq:<bot>:<dm|group>:<target>; person ids qq:<account>
TITLE = 'QQ'                      # the sidebar workspace its conversations live in
# Only the media hosts this deployment has actually received QQ images from (stored inbound metadata):
# the NT media host, and the group-picture CDN that older clients' pictures still come from.
IMAGE_HOSTS = ('multimedia.nt.qq.com.cn', 'gchat.qpic.cn')

ACCOUNT = re.compile(r'[0-9]{4,20}')
# The adapter writes a real @ in inbound text as @<account>; her outbound @ reaches it as @qq:<account>.
INBOUND_MENTION = re.compile(r'@(\d{5,12})')
SCENE = re.compile(r'qq:([^:]+):(dm|group):(.+)')


def person_id(account):
    return KIND + ':' + str(account)


def account_of(person):
    """The account inside a qq:<account> person id, else None."""
    head, _, account = str(person or '').partition(':')
    return account if head == KIND and ACCOUNT.fullmatch(account) else None


def scene_id(bot, kind, target):
    return '%s:%s:%s:%s' % (KIND, bot, kind, target)


def scene_parts(scene):
    """(bot account, 'dm' or 'group', target) of a QQ scene id, else None."""
    match = SCENE.fullmatch(str(scene or ''))
    return match.groups() if match else None


def outbound_mention(account):
    return '@' + person_id(account)


def adapter_config(adapter, channel):
    """Fill the adapter's derived settings from the channel it serves (host token is set by the core)."""
    adapter.setdefault('napcat', {})['account_id'] = channel['account_id']
    adapter.update(admission=channel['admission'], blocked_senders=channel.get('blocked_senders', []),
                   blocked_groups=channel.get('blocked_groups', []))
    adapter['routes'], adapter['allowed_private_user_ids'], adapter['allowed_group_ids'] = {}, [], []
    for route_id, route in channel.get('routes', {}).items():
        target = route['target']
        if target['type'] == 'dm':
            adapter['allowed_private_user_ids'].append(target['id'])
            adapter['routes'][route_id] = {'message_type': 'private', 'sender_id': route['sender_id'], 'target': target}
        elif target['type'] == 'group':
            adapter['allowed_group_ids'].append(target['id'])
            adapter['routes'][route_id] = {'message_type': 'group', 'allowed_sender_ids': list(route['members']),
                                           'target': target}
        else:
            raise ValueError('INVALID_CHANNEL_TARGET')
    return adapter


def strip_derived(adapter):
    """Remove what adapter_config derives, so exported settings keep only what the owner set."""
    for key in ('routes', 'allowed_private_user_ids', 'allowed_group_ids', 'admission',
                'blocked_senders', 'blocked_groups'):
        adapter.pop(key, None)
    adapter.get('napcat', {}).pop('account_id', None)
    return adapter


# integration_test runs an unreviewed adapter against live NapCat. Through these guards it may read (OneBot
# actions by name) and nothing else: no send, set, delete or upload, and none of the session secrets. QQ messages
# leave only through the outbox and the published adapter. The core's relay holds the NapCat token for the run.
READ_ONLY_ACTIONS = ('get_*', '_get_*', '.get_*', 'nc_get_*', 'can_*', 'fetch_*')
SECRET_ACTIONS = ('get_cookies', 'get_credentials', 'get_csrf_token', 'get_clientkey', '*rkey*')


def test_guards(adapter):
    from urllib.parse import urlsplit
    napcat = adapter.get('napcat') or {}
    try:
        port = urlsplit(napcat.get('url') or '').port
    except ValueError:
        port = None
    if not port:
        return []
    return [{'port': port, 'field': 'action', 'allow': READ_ONLY_ACTIONS, 'deny': SECRET_ACTIONS,
             'credential': ('napcat', 'token'), 'correlate': 'echo',
             'refusal': {'status': 'failed', 'retcode': 1403, 'data': None,
                         'message': 'integration_test reaches QQ read-only; sending goes through the outbox'}}]

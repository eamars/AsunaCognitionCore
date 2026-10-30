"""The channel server over HTTP, driven by the NapCat adapter's own client (HostApi, Admission): what a double of the
core cannot show (body sizes, status mapping, paths). The core's rules are tested in test_channel_admission.py."""
import pytest

from asuna.channels import Channels
from test_channel_admission import BOT, controller, desk  # noqa: F401


def test_the_adapters_own_client_over_the_real_channel_server(desk):
    """Over HTTP, with the adapter's HostApi and Admission: what a unit double of the core cannot show (body sizes,
    status mapping, the paths)."""
    import sys
    from asuna.channels import ChannelServer
    from asuna.config import ROOT
    adapter = ROOT / 'packages' / 'channels' / 'napcat-qq' / 'integration'
    sys.path[:0] = [str(adapter), str(adapter / 'vendor')]
    from qqadapter import admission as asking
    from qqadapter.hostapi import HostApi
    from qqadapter.journal import Counters
    store = desk('automatic')
    for index in range(3500):                                   # a list larger than one response the client reads
        store.config['channels']['acme']['routes']['auto-dm-u%04d' % index] = {
            'scene_id': 's%d' % index, 'target': {'type': 'dm', 'id': 'u%04d' % index}}
    channels = Channels(controller(store))
    server = ChannelServer(channels, port=0)
    try:
        host = HostApi({'base_url': 'http://127.0.0.1:%d' % server.server.server_port, 'token': store.config['channels']['acme']['token'],
                        'channel_id': 'acme'})
        counters = Counters()
        door = asking.Admission(host, BOT, counters)
        assert len(door.routes()) == 3501
        assert door.ask(('dm', 'carolyn')).route_id == 'auto-dm-carolyn'
        assert door.ask_routes(['crew', 'nowhere'])['crew'].admitted and not door.ask_routes(['nowhere'])['nowhere'].admitted
        assert door.cached(('dm', 'carolyn')) is not None
        leave = {'account_id': BOT, 'conversation': {'type': 'group', 'id': 'tribe'}, 'sender_id': 'dana'}
        assert host.post_departure(leave).kind == 'accepted'                      # unchanged: nobody admitted there
        claim = host.claim_outbox(0, timeout=5)
        assert claim.kind == 'empty' and claim.obj['epoch'] == channels.epoch
        door.observe(claim)
        assert door.cached(('dm', 'carolyn')) is not None, 'the same start of the core: what was kept stays'
        channels.epoch = 'a-new-start'
        door.observe(host.claim_outbox(0, timeout=5))
        assert door.cached(('dm', 'carolyn')) is None, 'a new start of the core: what was kept is dropped'
        store_wrong = HostApi({'base_url': 'http://127.0.0.1:%d' % server.server.server_port, 'token': 'wrong-token-' * 3,
                               'channel_id': 'acme'})
        with pytest.raises(asking.AdmissionAway):                                  # the key not taken is the core's, not the line's
            asking.Admission(store_wrong, BOT, Counters()).ask(('dm', 'carolyn'))
        old = host._request('POST', '/v1/channels/acme/nothing', {})
        assert old.kind == 'reject' and old.code == 404 and old.obj['error'] == 'UNKNOWN_CHANNEL_ENDPOINT'
    finally:
        server.close()

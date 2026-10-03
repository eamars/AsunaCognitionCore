#!/usr/bin/env python3
"""NapCat/OneBot v11 adapter entry point for the managed integration runner.

  python3 /app/adapter.py --selftest   read-only checks, no send, no fake inbound
  python3 /app/adapter.py --service    long running: inbound + outbox + receipts
"""
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
for path in (os.path.join(HERE, "vendor"), HERE):
    if os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Asuna QQ adapter (NapCat forward WebSocket)")
    parser.add_argument("--service", action="store_true", help="run the long-lived adapter")
    parser.add_argument("--selftest", action="store_true", help="run checks and exit")
    parser.add_argument("--config", default=None, help="config path (default $ASUNA_INTEGRATION_CONFIG or /integration/config.json)")
    parser.add_argument("--data-dir", default=os.environ.get("ASUNA_INTEGRATION_DATA", "/data"))
    parser.add_argument("--claim-wait", type=int, default=20, help="outbox long-poll seconds (<=25)")
    parser.add_argument("--ack-timeout", type=float, default=15.0, help="seconds to wait for a platform response")
    parser.add_argument("--offline", action="store_true",
                        help="with --selftest: skip the live checks that claim from the real outbox")
    parser.add_argument("--no-verify", action="store_true",
                        help="with --service: skip the post-send get_msg read-back (observation only)")
    parser.add_argument("--verify-delay", type=float, default=0.8,
                        help="seconds to wait before the post-send read-back (0 = no wait)")
    parser.add_argument("--peer-mode", choices=("full", "store", "off"), default="full",
                        help="with --service: full = identity directory and carry it in raw, "
                             "store = directory and logs only, off = disabled")
    parser.add_argument("--media-mode", choices=("full", "annotate", "off"), default=None,
                        help="override adapter.media_mode: full = report media segments and accept "
                             "media-only messages, annotate = only messages that already have text, "
                             "off = 0.3.0 behaviour (media counted, text-less messages dropped)")
    parser.add_argument("--peers", action="store_true",
                        help="print the peer identity directory from --data-dir and exit")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)

    if args.peers:
        from qqadapter.peers import PeerDirectory
        print(json.dumps(PeerDirectory(args.data_dir).dump(), ensure_ascii=False, indent=2, sort_keys=True), flush=True)
        return 0

    from qqadapter import config as config_mod

    if args.version:
        from qqadapter import __version__
        print("adapter %s" % __version__)
        return 0
    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as exc:
        print("CONFIG_ERROR %s" % exc, flush=True)
        return 2
    if args.media_mode:
        cfg.media_mode = args.media_mode

    claim_wait = max(1, min(int(args.claim_wait), 25))
    if args.selftest:
        from qqadapter import selftest as selftest_mod
        return selftest_mod.run(cfg, args.data_dir, live=not args.offline)
    if args.service:
        from qqadapter.service import Adapter
        return Adapter(cfg, args.data_dir, claim_wait=claim_wait, ack_timeout=args.ack_timeout,
                       verify=not args.no_verify, verify_delay=max(0.0, args.verify_delay),
                       peer_mode=args.peer_mode).run()
    parser.print_help()
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.stderr.write("ADAPTER_FATAL %s" % traceback.format_exc()[-2000:])
        sys.exit(70)

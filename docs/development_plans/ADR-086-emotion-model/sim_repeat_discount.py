"""ADR-086 stage 2: the mood bands hour by hour on the real ledger, today and under a same-kind repeat discount.

Read-only. From the checkout root:
    python docs/development_plans/ADR-086-emotion-model/sim_repeat_discount.py [--start 2026-10-27T00:00]
        [--end 2026-11-03T00:00] [--positive 0.7] [--negative 0.85] [--window 24] [--hold 72] [--persona local-xiaoman]
        [--model packages/personas/xiaoman/persona-model.json]
Times are UTC whole hours; the window is [start, end), and `--end` defaults to the last whole hour before now, never
later: an hour in the future would only show the decay of what is recorded so far, and change on the next run. Prints
what it read (window, events, amendments), then the band hours, the top band's share and the longest unbroken run for
the baseline (no discount, no hold: stage 1) and for the numbers given. The weights are the core's own
(`affect.repeat_weights`, the same pass `project()` runs); only the model's numbers change.
"""
import argparse
import collections
import datetime as dt
import json
import sys

sys.path.insert(0, 'src')
from asuna import affect                       # noqa: E402
from asuna.config import load                  # noqa: E402
from asuna.policy import PolicyStore           # noqa: E402
from asuna.state import Store                  # noqa: E402


def bands(model, events, amendments, start, hours):
    count, last, run, best = collections.Counter(), None, 0, 0
    for hour in range(hours):
        at = (start + dt.timedelta(hours=hour)).isoformat()
        band = (affect.first_rule(model['bands'], affect.project(model, events, amendments, at)) or {}).get('label')
        count[band] += 1
        run = run + 1 if band == last else 1
        last, best = band, max(best, run)
    top = count.most_common(1)[0][1]
    return dict(count.most_common()), '%d%% top' % round(100 * top / hours), 'longest %dh' % best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default='2026-10-27T00:00')
    ap.add_argument('--end')
    ap.add_argument('--positive', type=float, default=0.7)
    ap.add_argument('--negative', type=float, default=0.85)
    ap.add_argument('--window', type=float, default=24)
    ap.add_argument('--hold', type=float, default=72)
    ap.add_argument('--persona', default='local-xiaoman')
    ap.add_argument('--model', default='packages/personas/xiaoman/persona-model.json')
    a = ap.parse_args()
    config = load('config/local.json')
    config['persona_model'] = json.load(open(a.model, encoding='utf-8'))
    store = Store(config)
    persona_model = config['persona_model']
    ledger = affect.AffectLedger(store, a.persona, persona_model, PolicyStore(store, a.persona, persona_model).params())
    events, amendments = list(ledger.events()), list(ledger.amendments())
    utc = dt.timezone.utc
    start = dt.datetime.fromisoformat(a.start).replace(tzinfo=utc)
    now = dt.datetime.now(utc).replace(minute=0, second=0, microsecond=0)
    end = min(dt.datetime.fromisoformat(a.end).replace(tzinfo=utc), now) if a.end else now
    hours = int((end - start).total_seconds() // 3600)
    print('window %s .. %s UTC (%d h); events %d, amendments %d' % (start.isoformat()[:16], end.isoformat()[:16], hours,
                                                                     len(events), len(amendments)))
    off = {**ledger.model, 'repeat_discount': {'positive': 1.0, 'negative': 1.0, 'window_h': a.window}, 'open_hold_h': None}
    on = {**ledger.model, 'repeat_discount': {'positive': a.positive, 'negative': a.negative, 'window_h': a.window},
          'open_hold_h': a.hold}
    print('baseline (off)          ', *bands(off, events, amendments, start, hours))
    print('%.2f / %.2f / %gh, hold %gh' % (a.positive, a.negative, a.window, a.hold), *bands(on, events, amendments, start, hours))


if __name__ == '__main__':
    main()

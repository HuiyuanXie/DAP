#!/usr/bin/env python3
"""One live JSON probe; optionally one online society round. Uses the configured gateway."""
import argparse
from dap.provider import APIProvider, ProviderError
from dap.simulation import Simulation, obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round', action='store_true', help='Also run one bounded society round.')
    args = parser.parse_args()
    try:
        provider = APIProvider()
        print('Testing:', provider.model, 'via', provider.base_url, flush=True)
        result = provider.decide('connectivity', 'probe',
                                 {'instruction': 'Return exactly the JSON object {"ok": true}.'},
                                 obj(ok={'type': 'boolean'}))
        if not result['ok']:
            raise ProviderError('API responded but the connectivity decision did not pass.')
        print('PASS: authenticated request and valid JSON decision.', flush=True)
        if args.round:
            sim = Simulation(provider, rounds=1, setting='bounded')
            snapshot = sim.step()
            if snapshot['failed']:
                failure = next(e for e in reversed(snapshot['events']) if e['kind'] == 'Run stopped')
                print('Partial trace:', sim.persist(), flush=True)
                raise ProviderError(failure['data']['error'])
            print('PASS: one live society round completed.', flush=True)
            print('Metrics:', snapshot['metrics'], flush=True)
            print('Trace:', sim.persist(), flush=True)
        print('API calls:', provider.calls, 'total tokens:', provider.tokens, flush=True)
    except ProviderError as exc:
        parser.exit(1, 'FAIL: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()

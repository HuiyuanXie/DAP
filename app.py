#!/usr/bin/env python3
"""Local browser UI and CLI. Requires only Python 3.9+ standard library."""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from dap.provider import ROOT, OpenAIProvider, ProviderError
from dap.simulation import DemoProvider, Simulation


def make_simulation(mode='demo', setting='bounded', rounds=4, seed=7, communication=True, model=None):
    if mode not in ('demo', 'openai'):
        raise ValueError('Mode must be demo or openai.')
    if type(communication) is not bool:
        raise ValueError('Communication must be true or false.')
    if model is not None and (not isinstance(model, str) or not 1 <= len(model) <= 100):
        raise ValueError('Invalid model name.')
    provider = DemoProvider() if mode == 'demo' else OpenAIProvider(model=model)
    return Simulation(provider, setting=setting, rounds=rounds, seed=seed, communication=communication)


class AppState:
    def __init__(self):
        self.simulation = make_simulation()
        self.running = False
        self.lock = threading.RLock()

    def snapshot(self):
        with self.lock:
            return dict(self.simulation.snapshot(), running=self.running)

    def advance(self, all_rounds):
        with self.lock:
            if self.running:
                raise ValueError('A run is already in progress.')
            if self.simulation.snapshot()['complete']:
                raise ValueError('This run is complete. Start a new society.')
            self.running = True

        def work():
            try:
                self.simulation.step()
                while all_rounds and not self.simulation.snapshot()['complete']:
                    self.simulation.step()
            finally:
                with self.lock:
                    self.running = False

        threading.Thread(target=work, daemon=True).start()


def serve(port):
    state = AppState()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def local_request(self):
            host = self.headers.get('Host', '')
            allowed = {'127.0.0.1:' + str(self.server.server_port),
                       'localhost:' + str(self.server.server_port)}
            if host not in allowed:
                self.reply(403, {'error': 'Use the local server address.'})
                return False
            origin = self.headers.get('Origin')
            if origin and origin not in {'http://' + h for h in allowed}:
                self.reply(403, {'error': 'Cross-origin requests are disabled.'})
                return False
            return True

        def reply(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.local_request():
                return
            path = urlparse(self.path).path
            if path == '/api/state':
                self.reply(200, state.snapshot())
            elif path == '/api/export':
                self.reply(200, state.simulation.snapshot())
            elif path == '/':
                body = (ROOT / 'web' / 'index.html').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(body)
            else:
                self.reply(404, {'error': 'Not found.'})

        def do_POST(self):
            if not self.local_request():
                return
            try:
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Use application/json.')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError('Invalid request size.')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Expected an object.')
                path = urlparse(self.path).path
                if path == '/api/new':
                    with state.lock:
                        if state.running:
                            raise ValueError('Wait for the current round to finish.')
                        allowed = {'mode', 'setting', 'rounds', 'seed', 'communication', 'model'}
                        if set(data) - allowed:
                            raise ValueError('Unknown configuration field.')
                        state.simulation = make_simulation(**data)
                elif path in ('/api/step', '/api/run'):
                    state.advance(path == '/api/run')
                else:
                    self.reply(404, {'error': 'Not found.'})
                    return
                self.reply(200, state.snapshot())
            except (ValueError, ProviderError) as exc:
                self.reply(400, {'error': str(exc)})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print('Devolved Agent Parliament: http://127.0.0.1:' + str(server.server_port), flush=True)
    print('Demo mode is selected by default. Press Ctrl+C to stop.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', action='store_true', help='Run without the browser UI.')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--mode', choices=['demo', 'openai'], default='demo')
    parser.add_argument('--setting', choices=['bounded', 'constitutional', 'fixed'], default='bounded')
    parser.add_argument('--rounds', type=int, default=4)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--model', default=None, help='Overrides OPENAI_MODEL for CLI runs.')
    parser.add_argument('--no-communication', action='store_true')
    args = parser.parse_args()
    if not args.cli:
        serve(args.port)
        return
    try:
        sim = make_simulation(args.mode, args.setting, args.rounds, args.seed,
                              not args.no_communication, args.model)
        while not sim.snapshot()['complete']:
            result = sim.step()
            print('Round', result['round'], json.dumps(result['metrics']), flush=True)
        print('Trace:', sim.persist())
        if sim.failed:
            parser.exit(1, 'Run stopped. See the saved trace for the error.\n')
    except (ValueError, ProviderError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()

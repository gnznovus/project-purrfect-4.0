"""Real HTTP chat benchmark; no response cache or prompt-specific routing.

Run inside the existing purra container (see docs/performance/REPORT.md).
The production HTTP handler runs on a private loopback port. The model wrapper
observes all calls, including legacy fallbacks invisible to baseline --debug.
"""
import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from importlib.metadata import version
from pathlib import Path

from purrfect import local_api
from purrfect.ollama import OllamaModel


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--corpus', type=Path, default=Path(__file__).with_name('corpus.json'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--cold', action='store_true', help='Unload the selected model before the cold sample')
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error('--rounds must be positive')
    corpus_bytes = args.corpus.read_bytes()
    corpus = json.loads(corpus_bytes)
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in Path(local_api.__file__).parent.glob('*.py')}
    calls = []

    class MeasuredModel(OllamaModel):
        async def complete(self, system, user, **kwargs):
            record = {'system_chars': len(system), 'user_chars': len(user)}
            started = time.perf_counter()
            try:
                result = await super().complete(system, user, **kwargs)
                record.update(metrics=getattr(result, 'metrics', {}), raw=str(result))
                return result
            except Exception as error:
                record['error'] = type(error).__name__
                raise
            finally:
                record['wall_ms'] = round((time.perf_counter() - started) * 1000, 2)
                calls.append(record)

    local_api.OllamaModel = MeasuredModel
    os.environ['PURRA_BRAIN_MODE'] = 'ollama'
    # Isolate the benchmark from durable Sophia data; fixtures supply registered
    # evidence and normal leases remain processed by the production handler.
    os.environ.pop('SOPHIRA_DB_PATH', None)
    model_name = os.environ.get('PURRA_OLLAMA_MODEL', 'llama3.2:3b')
    model_url = os.environ.get('PURRA_OLLAMA_URL', 'http://ollama:11434')

    def ollama(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(model_url + path, data=data,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.load(response)

    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    threading.Thread(target=local_api.serve, args=('127.0.0.1', port), daemon=True).start()
    for _ in range(100):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/health', timeout=1):
                break
        except OSError:
            time.sleep(.05)
    else:
        raise RuntimeError('Benchmark HTTP handler did not start')

    def sample(case, sid):
        payload = {'session_id': sid, 'message': case['message'],
                   'selection': case.get('selection'), 'inventory': corpus['inventory'],
                   'context': case.get('context', {}), 'debug': True}
        payload.update(case.get('payload', {}))
        offset = len(calls)
        started = time.perf_counter()
        req = urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat',
              data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=240) as response:
            answer = json.load(response)
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        errors = []
        for key, expected in case.get('expect', {}).items():
            actual = answer
            for part in key.split('.'):
                actual = actual.get(part) if isinstance(actual, dict) else None
            if actual not in expected:
                errors.append(f'{key}: expected one of {expected!r}, got {actual!r}')
        if answer.get('status') == 'unsupported' and case.get('selection') != 'other':
            errors.append('Free text must not authorize unsupported rejection')
        allowed = {s['product_id'] for s in payload['inventory']['signals']
                   if any(a['key'] == s['key'] for a in payload['inventory']['active'])}
        for source in answer.get('sources', []):
            if source.get('product_id') not in allowed | {'wordpress', None}:
                errors.append('Source from inactive/unregistered product')
        result = {'id': case['id'], 'category': case['category'], 'message': case['message'],
                  'e2e_ms': elapsed, 'model_calls': len(calls) - offset,
                  'calls': calls[offset:], 'answer': answer, 'failures': errors}
        print(json.dumps({'id': case['id'], 'ms': elapsed, 'calls': result['model_calls'],
                          'failures': errors}), flush=True)
        return result

    cold = None
    if args.cold:
        ollama('/api/generate', {'model': model_name, 'keep_alive': 0})
        cold = sample(corpus['cases'][0], 'benchmark-cold')
    # Warm the model and graph separately from measured normal requests. This is
    # a distinct input, not a repeated measured prompt.
    sample({'id': 'warmup', 'category': 'warmup', 'message': 'Hello, Purr. Ready to talk?'}, 'benchmark-warmup')
    samples = []
    for round_number in range(args.rounds):
        for case in corpus['cases']:
            samples.append(sample(case, f'bench-{round_number}-{case["id"]}'))
    normal = [s for s in samples if s['category'] != 'boundary']
    values = [s['e2e_ms'] for s in normal]
    report = {
        'label': args.label, 'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
                    if shutil.which('git') else 'git unavailable in container',
        'source_sha256': source_hashes,
        'corpus_sha256': hashlib.sha256(corpus_bytes).hexdigest(),
        'environment': {'platform': platform.platform(), 'python': platform.python_version(),
            'dependencies': {p: version(p) for p in ('httpx', 'langgraph', 'langgraph-checkpoint-sqlite')},
            'ollama_version': ollama('/api/version'), 'ollama_ps': ollama('/api/ps'),
            'model': model_name, 'model_url': model_url},
        'summary': {'normal_n': len(normal), 'p50_ms': percentile(values, .50),
                    'p95_ms': percentile(values, .95),
                    'under_5000_fraction': sum(v < 5000 for v in values) / len(values),
                    'correct_normal_n': sum(not s['failures'] for s in normal),
                    'all_failures': sum(bool(s['failures']) for s in samples),
                    'max_model_calls': max(s['model_calls'] for s in samples)},
        'cold': cold, 'samples': samples,
    }
    output = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(output + '\n', encoding='utf-8')
    else:
        print('REPORT_JSON:' + json.dumps(report, ensure_ascii=False), flush=True)
    print(json.dumps(report['summary']), flush=True)


if __name__ == '__main__':
    main()

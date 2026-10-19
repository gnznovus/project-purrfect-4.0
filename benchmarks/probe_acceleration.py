"""Probe the installed native Ollama; emits measurements, not acceptance claims."""
import asyncio
import json
import time
import urllib.request
from pathlib import Path

from purrfect.ollama import OllamaModel
from purrfect.stateful_langgraph import understand_message


def main():
    url = 'http://127.0.0.1:11435'
    model = OllamaModel(base_url=url)
    corpus = json.loads(Path(__file__).with_name('corpus.json').read_text())
    catalog = {p['product_id']: p['product_id'] for p in corpus['inventory']['signals']}
    catalog.update(wordpress='General WordPress', other='Other')
    measurements = []
    for message in ('Hello Purr, how are you?', 'I need help finding my way around.',
                    'How can I edit blocks in mock-layout?'):
        diagnostics = []
        started = time.perf_counter()
        result = understand_message(model, message, {}, catalog, diagnostics)
        measurements.append({'message': message, 'wall_ms': round((time.perf_counter()-started)*1000, 2),
                             'decision': result, 'diagnostics': diagnostics})
    with urllib.request.urlopen(url + '/api/ps') as response:
        ps = json.load(response)
    with urllib.request.urlopen(url + '/api/version') as response:
        server_version = json.load(response)
    report = {'version': server_version, 'ps': ps, 'measurements': measurements}
    destination = Path(__file__).resolve().parents[1] / 'docs/performance/native-acceleration.json'
    destination.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    # Release only the model loaded by this dedicated probe server.
    payload = json.dumps({'model': model.model, 'keep_alive': 0}).encode()
    with urllib.request.urlopen(urllib.request.Request(url + '/api/generate', data=payload,
            headers={'Content-Type': 'application/json'})) as response:
        response.read()


if __name__ == '__main__':
    main()

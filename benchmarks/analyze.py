"""Summarize recorded measurements without dropping failed or slow requests."""
import csv
import json
from pathlib import Path

from chat_latency import percentile


def main():
    folder = Path(__file__).resolve().parents[1] / 'docs/performance'
    names = ['baseline', 'candidate-structured', 'candidate-routing', 'candidate-compact',
             'candidate-concise', 'optimized', 'holdout', 'candidate-meaning',
             'compact-confirmation-before-scope-guard', 'holdout-before-scope-guard']
    reports = {name: json.loads((folder / f'{name}.json').read_text(encoding='utf-8-sig'))
               for name in names}
    assert reports['baseline']['corpus_sha256'] == reports['optimized']['corpus_sha256']
    summaries = {}
    rows = []
    for name, report in reports.items():
        normal = [s for s in report['samples'] if s['category'] != 'boundary']
        stats = dict(report['summary'])
        stats['cold_ms'] = report['cold']['e2e_ms'] if report['cold'] else None
        stats['cold_load_ms'] = (sum(c.get('metrics', {}).get('load_ms', 0)
                                    for c in report['cold']['calls']) if report['cold'] else None)
        for metric in ['prompt_eval_ms', 'eval_ms', 'eval_count', 'load_ms']:
            totals = [sum(call.get('metrics', {}).get(metric, 0) for call in s['calls']) for s in normal]
            stats['p50_' + metric] = percentile(totals, .5)
            stats['p95_' + metric] = percentile(totals, .95)
        summaries[name] = stats
        print(name, json.dumps(stats))
        for index, s in enumerate(report['samples']):
            rows.append({'run': name, 'index': index, 'id': s['id'], 'category': s['category'],
                'e2e_ms': s['e2e_ms'], 'model_calls': s['model_calls'],
                'output_tokens': sum(c.get('metrics', {}).get('eval_count', 0) for c in s['calls']),
                'failures': '; '.join(s['failures'])})
        # Expand the original reports for easy local review; no samples removed.
        (folder / f'{name}.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    (folder / 'comparison.json').write_text(json.dumps(summaries, indent=2)+'\n', encoding='utf-8')
    with (folder / 'samples.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == '__main__':
    main()

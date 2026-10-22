"""P0 acquisition acceptance: configured inputs, replay and isolated partial failures."""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from src.ingest.public import REGISTRY, SUBMISSIONS, load_config, run_batch, select_filings
from src.ingest.sec import CacheMiss, SecClient


class Response:
    status_code = 200
    headers = {}

    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


class Session:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, **kwargs):
        self.calls.append(url)
        assert kwargs['allow_redirects'] is False
        return Response(self.routes[url])


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr('src.ingest.sec.time.sleep', lambda _: None)
    config = {'comps': {'tickers': ['ONE', 'MISSING', 'TWO'], 'forms': ['10-K', '10-Q'],
                       'after': '2025-01-01', 'before': '2026-10-16', 'earnings_8k_quarters': 4},
              'ingest': {'public': {'mode': 'replay', 'run_id': 'toy', 'user_agent': 'Toy test@example.edu',
                                   'requests_per_second': 4, 'timeout_s': 5, 'max_attempts': 1}}}
    params = tmp_path / 'params.yaml'
    params.write_text(yaml.safe_dump(config))
    routes = {REGISTRY: json.dumps({'0': {'ticker': 'ONE', 'cik_str': 1},
                                  '1': {'ticker': 'TWO', 'cik_str': 2}}).encode()}
    for n in (1, 2):
        cik = f'{n:010}'
        accs = [f'{cik}-26-000001', f'{cik}-26-000002']
        cols = {'accessionNumber': accs, 'form': ['10-K', '10-Q'],
                'filingDate': ['2026-02-01', '2026-05-01'], 'reportDate': ['2025-12-31', '2026-03-31'],
                'primaryDocument': ['annual.htm', 'quarter.htm'], 'isInlineXBRL': [1, 1], 'items': ['', '']}
        routes[f'{SUBMISSIONS}CIK{cik}.json'] = json.dumps({'cik': n, 'name': f'Company {n}',
             'filings': {'recent': cols, 'files': []}}).encode()
        routes[f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'] = json.dumps({'cik': n, 'facts': {}}).encode()
        for i, acc in enumerate(accs):
            filename = cols['primaryDocument'][i]
            base = f'https://www.sec.gov/Archives/edgar/data/{n}/{acc.replace("-", "")}'
            routes[f'{base}/{filename}'] = b'<html>test filing</html>'
            submission = f'ACCESSION NUMBER: {acc}\nCENTRAL INDEX KEY: {n}\nCONFORMED PERIOD OF REPORT: 20251231\nFILED AS OF DATE: 20260201\n'
            for name, body in [(filename, '<html>test filing</html>'), ('test.xsd', '<schema/>')]:
                submission += f'<DOCUMENT>\n<FILENAME>{name}\n<TEXT>{body}</TEXT>\n</DOCUMENT>\n'
            routes[f'{base}/{acc}.txt'] = submission.encode()
    return params, routes


def test_new_companies_partial_failure_and_network_free_replay(setup, tmp_path):
    params, routes = setup
    cache = tmp_path / 'cache'
    session = Session(routes)
    client = SecClient(cache, 'Toy test@example.edu', mode='record', session=session)
    states, metrics = run_batch(params, tmp_path / 'out', client=client, mode='record')
    assert [s['status'] for s in states] == ['completed', 'failed', 'completed']
    assert metrics['documents_acquired'] == 4
    acquired = (tmp_path / 'out/toy/manifest.jsonl').read_bytes()
    for line in acquired.splitlines():
        entry = json.loads(line)
        assert hashlib.sha256(Path(entry['source_path']).read_bytes()).hexdigest() == entry['sha256']
    class NoNetwork:
        def get(self, *args, **kwargs):
            pytest.fail('replay attempted network')
    replay = SecClient(cache, 'Toy test@example.edu', mode='replay', session=NoNetwork())
    states, metrics = run_batch(params, tmp_path / 'out', client=replay, mode='replay')
    assert metrics['network_requests'] == 0
    assert metrics['cache_hits'] > 0
    assert (tmp_path / 'out/toy/manifest.jsonl').read_bytes() == acquired
    assert [s['status'] for s in states] == ['completed', 'failed', 'completed']


def test_resume_and_reject_different_inputs_in_same_run(setup, tmp_path):
    params, routes = setup
    session = Session(routes)
    client = SecClient(tmp_path / 'cache', 'Toy test@example.edu', mode='record', session=session)
    run_batch(params, tmp_path / 'out', client=client)
    first = len(session.calls)
    run_batch(params, tmp_path / 'out', client=client)
    assert len(session.calls) == first
    with pytest.raises(ValueError, match='different inputs'):
        run_batch(params, tmp_path / 'out', client=client, tickers=['ONE'])


def test_missing_and_corrupt_caches_fail_without_network(tmp_path):
    client = SecClient(tmp_path, 'Toy test@example.edu')
    with pytest.raises(CacheMiss):
        client.get(REGISTRY)
    key = hashlib.sha256(REGISTRY.encode()).hexdigest()
    (tmp_path / key).write_bytes(b'bad')
    (tmp_path / f'{key}.json').write_text(json.dumps({'url': REGISTRY, 'sha256': '0' * 64}))
    with pytest.raises(ValueError, match='corrupt'):
        client.get(REGISTRY)
    with pytest.raises(ValueError, match='SEC hosts'):
        client.get('https://example.com/private')


def test_earnings_selection_filters_items_and_deduplicates_quarters():
    config = {'earnings_8k_quarters': 2}
    rows = [{'accessionNumber': str(n), 'form': '8-K', 'items': items,
             'reportDate': report, 'filingDate': report} for n, items, report in [
                 (1, '9.01', '2026-08-01'), (2, '2.02,9.01', '2026-07-20'),
                 (3, '2.02', '2026-07-10'), (4, '2.02', '2026-04-20')]]
    assert [r['accessionNumber'] for _, r in select_filings(rows, config, 'earnings')] == ['2', '4']


def test_invalid_configuration_rejected(setup):
    params, _ = setup
    with pytest.raises(ValueError, match='tickers or CIKs'):
        load_config(params, ['../private'])

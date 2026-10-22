"""Acquire configurable public-company filings and earnings, preserving partial work."""

import argparse
import hashlib
import json
import re
import resource
import time
from datetime import date
from pathlib import Path

import requests
import yaml

from src.download import DOCUMENT_RE, FILENAME_RE, unpack_submission
from src.ingest.sec import SecClient, atomic_write, write_json

REGISTRY = 'https://www.sec.gov/files/company_tickers.json'
SUBMISSIONS = 'https://data.sec.gov/submissions/'


def load_config(params_path, tickers=None):
    params = yaml.safe_load(Path(params_path).read_text())
    comps, ingest = dict(params['comps']), dict(params['ingest']['public'])
    if tickers is not None:
        comps['tickers'] = tickers
    if not comps['tickers'] or set(comps['forms']) != {'10-K', '10-Q'}:
        raise ValueError('configure at least one company and forms 10-K / 10-Q')
    comps['tickers'] = list(dict.fromkeys(str(t).strip().upper() for t in comps['tickers']))
    if any(not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,14}', t) for t in comps['tickers']):
        raise ValueError('companies must be tickers or CIKs, not paths')
    history = {str(k).strip().upper(): list(dict.fromkeys(str(c).zfill(10) for c in v))
               for k, v in comps.get('historical_ciks', {}).items()}
    if any(not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,14}', ticker) for ticker in history) or any(
            not re.fullmatch(r'\d{10}', cik) or int(cik) == 0
            for ciks in history.values() for cik in ciks):
        raise ValueError('historical_ciks must map tickers to positive 10-digit SEC CIKs')
    comps['historical_ciks'] = history
    if date.fromisoformat(comps['after']) > date.fromisoformat(comps['before']):
        raise ValueError('after must not exceed before')
    if not isinstance(comps['earnings_8k_quarters'], int) or not 1 <= comps['earnings_8k_quarters'] <= 20:
        raise ValueError('earnings_8k_quarters must be between 1 and 20')
    return {'comps': comps, 'public': ingest}


def resolve_company(query, client):
    if query.isdigit():
        if len(query) > 10 or int(query) == 0:
            raise ValueError('CIK must be a positive number of at most 10 digits')
        return query.zfill(10)
    registry = client.json(REGISTRY)
    matches = [str(v['cik_str']).zfill(10) for v in registry.values() if v['ticker'].upper() == query]
    if len(set(matches)) != 1:
        raise ValueError(f'unknown or ambiguous SEC ticker {query}')
    return matches[0]


def filing_rows(columns):
    count = len(columns.get('accessionNumber', []))
    if any(len(values) != count for values in columns.values()):
        raise ValueError('SEC submissions columns have inconsistent lengths')
    return [{key: values[i] for key, values in columns.items()} for i in range(count)]


def company_filings(cik, config, client):
    rows, info = [], None
    ciks = [cik, *config.get('historical_ciks', {}).get(config.get('_ticker', ''), [])]
    for source_cik in dict.fromkeys(ciks):
        submission = client.json(f'{SUBMISSIONS}CIK{source_cik}.json')
        if int(submission['cik']) != int(source_cik):
            raise ValueError('submissions CIK does not match resolved company')
        if info is None:
            info = submission
        company_rows = filing_rows(submission['filings']['recent'])
        for archive in submission['filings'].get('files', []):
            if archive['filingFrom'] <= config['before'] and archive['filingTo'] >= config['after']:
                name = archive['name']
                if Path(name).name != name or not name.endswith('.json'):
                    raise ValueError('unsafe historical submissions filename')
                company_rows.extend(filing_rows(client.json(SUBMISSIONS + name)))
        for row in company_rows:
            row['_registrant_cik'] = source_cik
        rows.extend(company_rows)
    unique = {}
    for row in rows:
        if config['after'] <= row['filingDate'] <= config['before']:
            unique[row['accessionNumber']] = row
    return info, sorted(unique.values(), key=lambda r: (r['filingDate'], r['accessionNumber']), reverse=True)


def select_filings(rows, config, stage):
    if stage == 'comps':
        return [(form, next((r for r in rows if r['form'] == form and str(r.get('isInlineXBRL')) == '1'), None))
                for form in config['forms']]
    candidates = [r for r in rows if r['form'] == '8-K' and
                  re.search(r'(?<![0-9])2\.02(?![0-9])', r.get('items', ''))]
    selected, quarters = [], set()
    for row in candidates:
        period = date.fromisoformat(row.get('reportDate') or row['filingDate'])
        quarter = (period.year, (period.month - 1) // 3)
        if quarter not in quarters:
            quarters.add(quarter)
            selected.append(('8-K', row))
        if len(selected) >= config['earnings_8k_quarters']:
            break
    return selected


def acquire_filing(cik, row, output, client, stage):
    accession = row['accessionNumber']
    if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession):
        raise ValueError('invalid SEC accession')
    filing_cik = row.get('_registrant_cik', cik)
    filename = row['primaryDocument']
    if Path(filename).name != filename or filename in ('', '.', '..'):
        raise ValueError('unsafe primary document filename')
    base = f'https://www.sec.gov/Archives/edgar/data/{int(filing_cik)}/{accession.replace("-", "")}'
    directory = output / filing_cik / accession
    primary = directory / filename
    atomic_write(primary, client.get(f'{base}/{filename}'))
    submission = directory / 'full-submission.txt'
    atomic_write(submission, client.get(f'{base}/{accession}.txt'))
    exhibits = []
    if stage == 'comps':
        metadata = unpack_submission(submission)
        if (metadata['accession'] != accession or metadata['cik'] != filing_cik
                or metadata['source_file'] != filename):
            raise ValueError('submission header does not match selected accession/CIK')
    else:
        text = submission.read_text(errors='replace')
        for document in DOCUMENT_RE.finditer(text):
            block = document.group(1)
            type_match = re.search(r'<TYPE>\s*([^\r\n]+)', block)
            name = FILENAME_RE.search(block)
            if type_match and type_match.group(1).strip().upper() == 'EX-99.1' and name:
                name = name.group(1).strip()
                if Path(name).name != name or name in ('', '.', '..'):
                    raise ValueError('unsafe exhibit filename')
                target = directory / 'exhibits' / name
                atomic_write(target, client.get(f'{base}/{name}'))
                exhibits.append({'source_path': str(target), 'source_url': f'{base}/{name}',
                    'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                    'source_type': 'edgar_8k_exhibit'})
        if not exhibits:
            raise ValueError('qualifying 8-K has no EX-99.1 exhibit')
    body = primary.read_bytes()
    return {'cik': cik, 'registrant_cik': filing_cik, 'doc_id': accession, 'form': row['form'],
            'filing_date': row['filingDate'], 'report_date': row.get('reportDate', ''),
            'source_url': f'{base}/{filename}', 'source_path': str(primary),
            'sha256': hashlib.sha256(body).hexdigest(), 'deal_id': 'public',
            'source_type': 'edgar_filing',
            'exhibits': exhibits, 'status': 'acquired'}


def run_batch(params_path, output, *, stage='comps', mode=None, tickers=None, run_id=None, client=None):
    config = load_config(params_path, tickers)
    options, comps = config['public'], config['comps']
    run_id = run_id or options['run_id']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', run_id):
        raise ValueError('run_id must contain letters, digits, underscores or hyphens')
    destination = Path(output) / run_id
    effective = {'stage': stage, 'comps': comps, 'public': {k: v for k, v in options.items()
                 if k not in ('mode', 'run_id')}, 'run_id': run_id}
    snapshot = destination / 'config.json'
    if snapshot.exists() and json.loads(snapshot.read_text()) != effective:
        raise ValueError('run_id already has different inputs/settings; choose a new run_id')
    write_json(snapshot, effective)
    client = client or SecClient(destination / 'http_cache', options['user_agent'],
        mode=mode or options['mode'], requests_per_second=options['requests_per_second'],
        timeout_s=options['timeout_s'], max_attempts=options['max_attempts'])
    start, cpu = time.perf_counter(), time.process_time()
    network_before, hits_before = client.network_requests, client.cache_hits
    statuses, manifest = [], []
    summary_path = destination / 'status.json'
    for index, ticker in enumerate(comps['tickers'], 1):
        company = {'input': ticker, 'status': 'running', 'documents': [], 'errors': []}
        statuses.append(company)
        write_json(summary_path, statuses)
        began = time.perf_counter()
        print(f'[{index}/{len(comps["tickers"])}] {ticker}: starting', flush=True)
        try:
            cik = resolve_company(ticker, client)
            company_config = {**comps, '_ticker': ticker}
            info, rows = company_filings(cik, company_config, client)
            company.update(cik=cik, company=info['name'])
            selections = select_filings(rows, comps, stage)
            expected = len(comps['forms']) if stage == 'comps' else comps['earnings_8k_quarters']
            if len(selections) < expected:
                company['errors'].append(f'only {len(selections)} qualifying earnings quarters found; expected {expected}')
            if stage == 'comps':
                try:
                    url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
                    facts = client.get(url)
                    if int(json.loads(facts)['cik']) != int(cik):
                        raise ValueError('companyfacts CIK mismatch')
                    path = destination / cik / 'companyfacts.json'
                    atomic_write(path, facts)
                    company['companyfacts'] = {'path': str(path), 'sha256': hashlib.sha256(facts).hexdigest()}
                except (ValueError, RuntimeError, OSError, requests.RequestException) as error:
                    company['errors'].append(f'companyfacts: {type(error).__name__}: {error}')
            for form, row in selections:
                if row is None:
                    company['documents'].append({'form': form, 'status': 'unavailable',
                        'reason': 'no eligible inline-XBRL filing in the configured filing-date window'})
                    continue
                try:
                    entry = acquire_filing(cik, row, destination, client, stage)
                    entry.update(ticker=ticker, company=info['name'])
                    manifest.append(entry)
                    company['documents'].append(entry)
                except (ValueError, RuntimeError, OSError, requests.RequestException) as error:
                    company['documents'].append({'doc_id': row['accessionNumber'], 'form': form,
                        'status': 'failed', 'reason': f'{type(error).__name__}: {error}'})
                write_json(summary_path, statuses)
            successful = sum(d['status'] == 'acquired' for d in company['documents'])
            company['status'] = 'completed' if successful == expected and not company['errors'] else ('partial' if successful else 'failed')
        except (ValueError, KeyError, RuntimeError, OSError, requests.RequestException) as error:
            company['status'] = 'failed'
            company['errors'].append(f'{type(error).__name__}: {error}')
        company['elapsed_s'] = time.perf_counter() - began
        write_json(summary_path, statuses)
        print(f'{ticker}: {company["status"]}', flush=True)
    atomic_write(destination / 'manifest.jsonl', ''.join(json.dumps(r) + '\n' for r in manifest).encode())
    usage = resource.getrusage(resource.RUSAGE_SELF)
    import sys
    metrics = {'elapsed_s': time.perf_counter() - start, 'cpu_s': time.process_time() - cpu,
        'process_peak_rss_bytes': usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024),
        'network_requests': client.network_requests - network_before,
        'cache_hits': client.cache_hits - hits_before, 'documents_acquired': len(manifest),
        'companies_completed': sum(s['status'] == 'completed' for s in statuses),
        'companies_incomplete': sum(s['status'] != 'completed' for s in statuses),
        'mode': mode or options['mode']}
    write_json(destination / 'measurements.json', metrics)
    return statuses, metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--params', default='params.yaml')
    parser.add_argument('--stage', choices=['comps', 'earnings'], default='comps')
    parser.add_argument('--output', required=True)
    parser.add_argument('--mode', choices=['record', 'replay'])
    parser.add_argument('--tickers', nargs='+')
    parser.add_argument('--run-id')
    args = parser.parse_args()
    statuses, _ = run_batch(args.params, args.output, stage=args.stage, mode=args.mode,
                            tickers=args.tickers, run_id=args.run_id)
    raise SystemExit(any(s['status'] != 'completed' for s in statuses))

if __name__ == '__main__':
    main()

"""Rate-limited SEC requests with atomic, hash-verified record/replay caching."""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests


class CacheMiss(RuntimeError):
    pass


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path, value):
    atomic_write(path, (json.dumps(value, indent=2, allow_nan=False) + '\n').encode())


class SecClient:
    def __init__(self, cache, user_agent, *, mode='replay', requests_per_second=4,
                 timeout_s=60, max_attempts=3, session=None):
        if mode not in ('record', 'replay'):
            raise ValueError('mode must be record or replay')
        if not 0 < requests_per_second < 10 or not 1 <= max_attempts <= 4 or timeout_s <= 0:
            raise ValueError('require rate below 10 requests/s, 1–4 attempts and positive timeout')
        if '@' not in user_agent:
            raise ValueError('SEC User-Agent must identify the team and contact email')
        self.cache, self.mode = Path(cache), mode
        self.user_agent, self.interval = user_agent, 1 / requests_per_second
        self.timeout, self.attempts = timeout_s, max_attempts
        self.session = session or requests.Session()
        self.last_request = 0
        self.network_requests = self.cache_hits = 0

    def get(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in {'www.sec.gov', 'data.sec.gov'}:
            raise ValueError('only HTTPS SEC hosts are allowed')
        if parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError('invalid SEC URL authority')
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache / key
        meta_path = self.cache / f'{key}.json'
        if path.exists() and meta_path.exists():
            body = path.read_bytes()
            meta = json.loads(meta_path.read_text())
            if meta['url'] != url or meta['sha256'] != hashlib.sha256(body).hexdigest():
                raise ValueError(f'corrupt SEC cache for {url}; restore it before retrying')
            self.cache_hits += 1
            return body
        if self.mode == 'replay':
            raise CacheMiss(f'no recorded SEC response for {url}')
        for attempt in range(self.attempts):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            self.network_requests += 1
            try:
                response = self.session.get(url, headers={'User-Agent': self.user_agent,
                    'Accept-Encoding': 'gzip, deflate'}, timeout=self.timeout, allow_redirects=False)
            except (requests.Timeout, requests.ConnectionError):
                if attempt + 1 == self.attempts:
                    raise
                time.sleep(2 ** attempt)
                continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt + 1 < self.attempts:
                try:
                    delay = min(60, max(1, float(response.headers.get('Retry-After', 2 ** attempt))))
                except ValueError:
                    delay = 2 ** attempt
                time.sleep(delay)
                continue
            response.raise_for_status()
            if response.status_code != 200:
                raise RuntimeError(f'expected HTTP 200, got {response.status_code}: {url}')
            body = response.content
            atomic_write(path, body)
            write_json(meta_path, {'url': url, 'sha256': hashlib.sha256(body).hexdigest()})
            return body
        raise RuntimeError('SEC request attempts exhausted')

    def json(self, url):
        return json.loads(self.get(url))

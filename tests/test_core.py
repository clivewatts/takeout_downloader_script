"""Tests for the shared download engine and the web worker.

The download tests run against a local HTTP server, so no network access or
Google account is required.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock
from urllib.parse import urlparse

import pytest
import requests

from dedupe_takeout import SAMPLE_SIZE, dedupe

from takeout import (
    SizeHistory,
    TakeoutDownloader,
    build_file_url,
    extract_cookie_from_curl,
    extract_url_parts,
    get_temp_path,
)

SAMPLE_ZIP = b'PK\x03\x04' + b'\x00' * 8192
PART_PREFIX = '/takeout-20251207T071725Z-3-'


class FakeArchiveHandler(BaseHTTPRequestHandler):
    """Serve a tiny set of archives, with Range support."""

    files = {}
    ranges = []
    paths = []

    def do_GET(self):
        parsed = urlparse(self.path)
        self.paths.append(self.path)
        body = self.files.get(parsed.path)
        if body is None:
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return

        range_header = self.headers.get('Range')
        self.ranges.append(range_header)

        start = 0
        if range_header and range_header.startswith('bytes='):
            start = int(range_header.split('=', 1)[1].split('-', 1)[0])

        if start >= len(body):
            self.send_response(416)
            self.end_headers()
            return

        chunk = body[start:]
        if start:
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{len(body) - 1}/{len(body)}')
        else:
            self.send_response(200)
        self.send_header('Content-Type', 'application/zip')
        self.send_header('Content-Length', str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)

    def do_HEAD(self):
        parsed = urlparse(self.path)
        body = self.files.get(parsed.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()

    def log_message(self, *args):
        pass


class SlowArchiveHandler(BaseHTTPRequestHandler):
    """Stream a large archive slowly so a test can interrupt it."""

    size = 4 * 1024 * 1024
    chunk = 32 * 1024
    delay = 0.02

    def do_GET(self):
        body = b'PK' + b'\x00' * (self.size - 2)
        self.send_response(200)
        self.send_header('Content-Type', 'application/zip')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            for offset in range(0, len(body), self.chunk):
                self.wfile.write(body[offset:offset + self.chunk])
                self.wfile.flush()
                time.sleep(self.delay)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


@pytest.fixture
def slow_archive_server():
    server = ThreadingHTTPServer(('127.0.0.1', 0), SlowArchiveHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def archive_server():
    FakeArchiveHandler.files = {}
    FakeArchiveHandler.ranges = []
    FakeArchiveHandler.paths = []
    server = ThreadingHTTPServer(('127.0.0.1', 0), FakeArchiveHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', FakeArchiveHandler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def make_downloader(tmp_path, base_url, parallel=1):
    downloader = TakeoutDownloader(str(tmp_path), parallel, log_fn=lambda message: None)
    downloader.base_url = f'{base_url}{PART_PREFIX}'
    downloader.extension = '.zip'
    downloader.query_string = 'i=0&authuser=0'
    downloader.cookie = 'SID=test'
    return downloader


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('extension', ['.zip', '.tgz', '.tar.gz'])
def test_extract_url_parts_supports_archive_extensions(extension):
    url = f'https://example.com/download/takeout-20251207T071725Z-3-007{extension}?i=0&authuser=0'
    base, num, ext, query = extract_url_parts(url)
    assert base == 'https://example.com/download/takeout-20251207T071725Z-3-'
    assert num == 7
    assert ext == extension
    assert query == 'i=0&authuser=0'


def test_extract_url_parts_rejects_unknown_extension():
    assert extract_url_parts('https://example.com/download/takeout-20251207T071725Z-3-001.rar')[0] is None


@pytest.mark.parametrize('query, expected_i', [
    ('i=0&authuser=0', '1'),          # i first
    ('authuser=0&i=0', '1'),          # i later
    ('j=abc&i=0&user=1', '1'),
    ('authuser=0', None),             # no i at all
])
def test_build_file_url_updates_index(query, expected_i):
    url = build_file_url('https://example.com/x/takeout-20251207T071725Z-3-', '.zip', query, 2)
    assert url.startswith('https://example.com/x/takeout-20251207T071725Z-3-002.zip')
    if expected_i is not None:
        assert f'i={expected_i}' in url
        assert 'i=0' not in url
    else:
        assert 'i=' not in url


def test_build_file_url_keeps_other_parameters():
    url = build_file_url('https://example.com/x/takeout-20251207T071725Z-3-', '.zip',
                         'j=abc&i=0&user=42&authuser=0', 3)
    assert 'j=abc' in url
    assert 'user=42' in url
    assert 'authuser=0' in url
    assert 'i=2' in url


# ---------------------------------------------------------------------------
# cURL / PowerShell parsing
# ---------------------------------------------------------------------------

def test_extract_cookie_from_chrome_curl():
    curl = ("curl 'https://takeout-download.usercontent.google.com/download/x.zip?i=0' "
            "-H 'authority: example' -H 'cookie: SID=abc; HSID=def' --compressed")
    assert extract_cookie_from_curl(curl) == 'SID=abc; HSID=def'


def test_extract_cookie_from_firefox_curl():
    curl = ("curl 'https://takeout-download.usercontent.google.com/download/x.zip?i=0' "
            "--header 'Cookie: SID=abc; HSID=def'")
    assert extract_cookie_from_curl(curl) == 'SID=abc; HSID=def'


def test_extract_cookie_from_powershell():
    ps = (
        '$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession\n'
        '$session.Cookies.Add((New-Object System.Net.Cookie("SID", "abc", "/", ".google.com")))\n'
        'Invoke-WebRequest -UseBasicParsing -Uri '
        '"https://takeout-download.usercontent.google.com/download/x.zip?i=0" -WebSession $session'
    )
    assert extract_cookie_from_curl(ps) == 'SID=abc'


# ---------------------------------------------------------------------------
# Size history
# ---------------------------------------------------------------------------

def test_size_history_is_atomic_under_concurrency(tmp_path):
    history = SizeHistory(str(tmp_path))
    threads = [
        threading.Thread(target=history.record_size, args=(f'file-{i}.zip', i))
        for i in range(40)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    data = json.loads((tmp_path / '.takeout_sizes.json').read_text())
    assert len(data) == 40
    assert data['file-39.zip'] == 39


# ---------------------------------------------------------------------------
# Download engine
# ---------------------------------------------------------------------------

def test_downloader_end_to_end_counts_missing_parts(tmp_path, archive_server):
    base_url, handler = archive_server
    handler.files = {
        f'{PART_PREFIX}001.zip': SAMPLE_ZIP,
        f'{PART_PREFIX}002.zip': SAMPLE_ZIP + b'part-2',
    }

    downloader = make_downloader(tmp_path, base_url, parallel=2)
    stats = downloader.run(file_count=3)

    assert (tmp_path / 'takeout-20251207T071725Z-3-001.zip').read_bytes() == SAMPLE_ZIP
    assert (tmp_path / 'takeout-20251207T071725Z-3-002.zip').read_bytes() == SAMPLE_ZIP + b'part-2'
    assert not (tmp_path / 'takeout-20251207T071725Z-3-003.zip').exists()
    assert stats.completed_files == 2
    assert stats.not_found_files == 1
    assert stats.failed_files == 0

    # The `i` parameter must follow the part number (0-based) even when it is
    # the first query parameter.
    assert any('001.zip?i=0&authuser=0' in path for path in handler.paths)
    assert any('002.zip?i=1&authuser=0' in path for path in handler.paths)


def test_downloader_resumes_partial_file(tmp_path, archive_server):
    base_url, handler = archive_server
    body = SAMPLE_ZIP + b'-tail'
    handler.files = {f'{PART_PREFIX}001.zip': body}

    downloader = make_downloader(tmp_path, base_url)
    filepath = downloader.get_filepath(1)
    partial = get_temp_path(filepath)
    partial.write_bytes(body[:40])

    stats = downloader.run(file_count=1)

    assert stats.completed_files == 1
    assert filepath.read_bytes() == body
    assert not partial.exists()
    assert 'bytes=40-' in [r for r in handler.ranges if r]


def test_downloader_rejects_non_archive_response(tmp_path, archive_server):
    base_url, handler = archive_server
    handler.files = {f'{PART_PREFIX}001.zip': b'<html>not a zip</html>' * 200}

    downloader = make_downloader(tmp_path, base_url)
    success, error = downloader.download_file(1)

    assert success is False
    assert error == 'NOT_ARCHIVE'
    assert not downloader.get_filepath(1).exists()


@pytest.mark.parametrize('mode', ['shared', 'web', 'tui'])
@pytest.mark.parametrize('scenario', ['oversized', 'complete', 'wrong_offset', 'short_body'])
def test_archive_resume_validation(tmp_path, monkeypatch, mode, scenario):
    import google_takeout_web as web
    from google_takeout_tui import TakeoutTUI

    downloader = make_downloader(tmp_path, 'https://takeout.google.com')
    filepath = downloader.get_filepath(1)
    partial = get_temp_path(filepath)
    url = downloader.get_url(1)
    partial_data = SAMPLE_ZIP[:40]

    def response(status, headers, body=b''):
        reply = requests.Response()
        reply.url = url
        reply.status_code = status
        reply.headers.update(headers)
        reply.iter_content = Mock(return_value=iter([body]))
        reply.close = Mock()
        return reply

    if scenario in ('oversized', 'complete'):
        partial_data = SAMPLE_ZIP + (b'extra' if scenario == 'oversized' else b'')
        headers = {'Content-Length': str(len(SAMPLE_ZIP))}
        get = Mock(side_effect=[response(416, {}), response(200, headers, SAMPLE_ZIP)])
        monkeypatch.setattr(requests, 'head', Mock(return_value=response(200, headers)))
    else:
        start = 41 if scenario == 'wrong_offset' else 40
        headers = {'Content-Range': f'bytes {start}-{len(SAMPLE_ZIP) - 1}/{len(SAMPLE_ZIP)}'}
        get = Mock(return_value=response(206, headers, SAMPLE_ZIP[start:-1]))
    monkeypatch.setattr(requests, 'get', get)
    partial.write_bytes(partial_data)

    if mode == 'web':
        monkeypatch.setitem(web.download_state, 'should_stop', False)
        monkeypatch.setitem(web.download_state, 'files', [])
        monkeypatch.setitem(web.download_state, 'stats', {'bytes_downloaded': 0})
        monkeypatch.setattr(web, 'emit_status', Mock())
        monkeypatch.setattr(web, 'add_log', Mock())
        result = web.download_file(url, filepath, 1, downloader.cookie, downloader.size_history)
        success = result['success']
    elif mode == 'tui':
        app = TakeoutTUI()
        app.downloader = downloader
        monkeypatch.setattr(app, 'call_from_thread', Mock())
        success, _ = app.download_file(1)
    else:
        success, _ = downloader.download_file(1)

    assert get.call_args_list[0].kwargs['headers']['Range'] == f'bytes={len(partial_data)}-'
    if scenario in ('oversized', 'complete'):
        assert success
        assert filepath.read_bytes() == SAMPLE_ZIP
        assert not partial.exists()
        assert get.call_count == (2 if scenario == 'oversized' else 1)
        if scenario == 'oversized':
            assert 'Range' not in get.call_args.kwargs['headers']
    else:
        assert not success
        assert not filepath.exists()
        assert partial.read_bytes() == (partial_data if scenario == 'wrong_offset' else SAMPLE_ZIP[:-1])


def test_dedupe_preserves_archives_that_differ_outside_samples(tmp_path):
    prefix = b'PK' + b'A' * (SAMPLE_SIZE - 2)
    suffix = b'Z' * SAMPLE_SIZE
    original = prefix + b'1' + suffix
    distinct = prefix + b'2' + suffix
    (tmp_path / 'a.zip').write_bytes(original)
    (tmp_path / 'b.zip').write_bytes(distinct)
    (tmp_path / 'c.zip').write_bytes(original)

    assert dedupe(tmp_path) == (1, len(original))
    assert (tmp_path / 'a.zip').read_bytes() == original
    assert (tmp_path / 'b.zip').read_bytes() == distinct
    assert not (tmp_path / 'c.zip').exists()


# ---------------------------------------------------------------------------
# Web worker (regression: completion used to deadlock on state_lock)
# ---------------------------------------------------------------------------

def _reset_web_state():
    import google_takeout_web as web
    with web.state_lock:
        web.download_state['is_running'] = False
        web.download_state['should_stop'] = False
        web.download_state['files'] = []
        web.download_state['log'] = []
        web.download_state['stats'] = {
            'total_files': 0,
            'completed_files': 0,
            'failed_files': 0,
            'skipped_files': 0,
            'not_found_files': 0,
            'bytes_downloaded': 0,
            'start_time': None,
        }


def test_web_run_downloads_finishes_and_does_not_deadlock(tmp_path, archive_server, monkeypatch):
    import google_takeout_web as web

    base_url, handler = archive_server
    handler.files = {
        f'{PART_PREFIX}001.zip': SAMPLE_ZIP,
        f'{PART_PREFIX}002.zip': SAMPLE_ZIP,
    }
    # No Socket.IO server is running in tests.
    monkeypatch.setattr(web.socketio, 'emit', lambda *args, **kwargs: None)
    _reset_web_state()

    url = f'{base_url}{PART_PREFIX}001.zip?i=0&authuser=0'
    with web.state_lock:
        web.download_state['is_running'] = True

    worker = threading.Thread(
        target=web.run_downloads,
        args=('SID=test', url, str(tmp_path), 2, 3),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=20)

    assert not worker.is_alive(), 'run_downloads deadlocked'
    assert web.download_state['is_running'] is False
    stats = web.download_state['stats']
    assert stats['completed_files'] == 2
    assert stats['not_found_files'] == 1
    assert stats['total_files'] == 3
    assert (tmp_path / 'takeout-20251207T071725Z-3-001.zip').exists()
    assert (tmp_path / 'takeout-20251207T071725Z-3-002.zip').exists()


def test_web_download_file_stops_and_keeps_partial(tmp_path, slow_archive_server, monkeypatch):
    import google_takeout_web as web

    monkeypatch.setattr(web.socketio, 'emit', lambda *args, **kwargs: None)
    with web.state_lock:
        web.download_state['should_stop'] = False

    output_path = tmp_path / 'takeout-20251207T071725Z-3-001.zip'
    url = f'{slow_archive_server}{PART_PREFIX}001.zip?i=0'

    timer = threading.Timer(0.3, lambda: web.download_state.__setitem__('should_stop', True))
    timer.start()
    try:
        result = web.download_file(
            url, output_path, 1, 'SID=test', web.SizeHistory(str(tmp_path)), '.zip'
        )
    finally:
        timer.cancel()

    assert result['stopped'] is True
    assert not output_path.exists()
    assert get_temp_path(output_path).exists()


def test_api_stop_requires_a_running_download(monkeypatch):
    import google_takeout_web as web

    monkeypatch.setattr(web.socketio, 'emit', lambda *args, **kwargs: None)
    _reset_web_state()
    client = web.app.test_client()

    assert client.post('/api/stop').status_code == 409

    with web.state_lock:
        web.download_state['is_running'] = True
    response = client.post('/api/stop')

    assert response.status_code == 200
    assert web.download_state['should_stop'] is True
    _reset_web_state()

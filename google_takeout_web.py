#!/usr/bin/env python3
"""
Google Takeout Bulk Downloader - Web Version
A web interface for downloading Google Takeout archives in headless environments.
"""

import os
import re
import sys
import threading
import time
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit

# ============================================================================
# CONFIGURATION
# ============================================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'takeout-downloader-secret')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Default settings
DEFAULT_OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/downloads')
DEFAULT_PARALLEL = int(os.environ.get('PARALLEL_DOWNLOADS', '6'))
DEFAULT_FILE_COUNT = int(os.environ.get('FILE_COUNT', '100'))

# Download state
download_state = {
    'is_running': False,
    'cookie': '',
    'url': '',
    'output_dir': DEFAULT_OUTPUT_DIR,
    'parallel': DEFAULT_PARALLEL,
    'file_count': DEFAULT_FILE_COUNT,
    'files': [],
    'stats': {
        'total_files': 0,
        'completed_files': 0,
        'failed_files': 0,
        'skipped_files': 0,
        'bytes_downloaded': 0,
        'start_time': None,
    },
    'log': [],  # Preserve log messages for reconnecting clients
}
state_lock = threading.Lock()
MAX_LOG_ENTRIES = 500  # Limit log buffer size

# ============================================================================
# DOWNLOAD ENGINE
# ============================================================================

CHUNK_SIZE = 1024 * 1024  # 1MB chunks

def extract_url_parts(url: str) -> tuple:
    """Extract URL parts for Google Takeout pattern."""
    if '?' in url:
        url_path, query_string = url.split('?', 1)
    else:
        url_path, query_string = url, ''
    
    match = re.search(r'(.*takeout-[^-]+-)(\d+)-(\d+)(\.\w+)$', url_path)
    if not match:
        return None, None, None, None, None
    
    base = match.group(1)
    batch_num = int(match.group(2))
    file_num = int(match.group(3))
    ext = match.group(4)
    
    return base, batch_num, file_num, ext, query_string

def extract_cookie_from_curl(curl_text: str) -> str:
    """Extract cookie value from a cURL command or raw cookie string."""
    if 'curl' in curl_text.lower() or "-H 'Cookie:" in curl_text or '-H "Cookie:' in curl_text:
        match = re.search(r"-H\s*['\"]Cookie:\s*([^'\"]+)['\"]", curl_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    if curl_text.lower().startswith('cookie:'):
        return curl_text[7:].strip()
    
    cookie = curl_text.strip()
    if (cookie.startswith("'") and cookie.endswith("'")) or \
       (cookie.startswith('"') and cookie.endswith('"')):
        cookie = cookie[1:-1]
    
    return cookie

def extract_url_from_curl(curl_text: str) -> str:
    """Extract the download URL from a cURL command."""
    match = re.search(r"curl\s+['\"]?(https?://[^'\"\s]+)['\"]?", curl_text, re.IGNORECASE)
    if match:
        url = match.group(1)
        if 'takeout' in url.lower():
            return url
    return None

def create_fast_session(cookie: str) -> requests.Session:
    """Create an optimized session for fast downloads."""
    session = requests.Session()
    
    adapter = HTTPAdapter(
        pool_connections=10,
        pool_maxsize=10,
        max_retries=Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    )
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Encoding': 'identity',
        'Connection': 'keep-alive',
        'Cookie': cookie,
    })
    return session

def emit_status(event: str, data: dict):
    """Emit status update to all connected clients."""
    socketio.emit(event, data)

def add_log(message: str, log_type: str = 'info'):
    """Add a log entry to the buffer and emit to clients."""
    from datetime import datetime
    entry = {
        'time': datetime.now().strftime('%H:%M:%S'),
        'message': message,
        'type': log_type,
    }
    with state_lock:
        download_state['log'].append(entry)
        # Keep log buffer bounded
        if len(download_state['log']) > MAX_LOG_ENTRIES:
            download_state['log'] = download_state['log'][-MAX_LOG_ENTRIES:]
    socketio.emit('log_entry', entry)

def download_file(url: str, output_path: Path, file_index: int, cookie: str) -> dict:
    """Download a single file with progress tracking."""
    session = create_fast_session(cookie)
    filename = output_path.name
    result = {
        'index': file_index,
        'filename': filename,
        'success': False,
        'message': '',
        'auth_failed': False,
        'size': 0,
    }
    
    try:
        with session.get(url, stream=True, allow_redirects=True, timeout=(10, 300)) as r:
            r.raise_for_status()
            
            content_type = r.headers.get('content-type', '')
            if 'text/html' in content_type:
                preview = r.content[:500].decode('utf-8', errors='ignore')
                if 'signin' in preview.lower() or 'login' in preview.lower():
                    result['message'] = 'Auth failed - cookies invalid/expired'
                    result['auth_failed'] = True
                    return result
                result['message'] = 'Got HTML instead of ZIP'
                return result
            
            total_size = int(r.headers.get('content-length', 0))
            
            if total_size < 1000000:
                result['message'] = f'File too small ({total_size} bytes)'
                return result
            
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            emit_status('file_start', {
                'index': file_index,
                'filename': filename,
                'size': total_size,
            })
            
            downloaded = 0
            last_emit_time = time.time()
            
            with open(output_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        chunk_len = len(chunk)
                        downloaded += chunk_len
                        
                        # Update global stats
                        with state_lock:
                            download_state['stats']['bytes_downloaded'] += chunk_len
                        
                        # Emit progress every 500ms
                        now = time.time()
                        if now - last_emit_time >= 0.5:
                            percent = int((downloaded / total_size) * 100) if total_size > 0 else 0
                            emit_status('file_progress', {
                                'index': file_index,
                                'filename': filename,
                                'downloaded': downloaded,
                                'total': total_size,
                                'percent': percent,
                            })
                            last_emit_time = now
            
            result['success'] = True
            result['message'] = 'Complete'
            result['size'] = total_size
            return result
            
    except requests.exceptions.RequestException as e:
        if output_path.exists():
            output_path.unlink()
        result['message'] = str(e)
        return result

def run_downloads(cookie: str, url: str, output_dir: str, parallel: int, file_count: int):
    """Run the download process."""
    global download_state
    
    with state_lock:
        download_state['is_running'] = True
        download_state['stats'] = {
            'total_files': 0,
            'completed_files': 0,
            'failed_files': 0,
            'skipped_files': 0,
            'bytes_downloaded': 0,
            'start_time': datetime.now().isoformat(),
        }
        download_state['files'] = []
        download_state['log'] = []  # Clear log for new session
    
    add_log('Starting downloads...', 'info')
    emit_status('download_started', {'message': 'Starting downloads...'})
    
    # Parse URL
    base_url, batch_num, start_file, extension, query_string = extract_url_parts(url)
    
    if base_url is None:
        add_log('Invalid URL format. Expected: takeout-TIMESTAMP-N-NNN.zip', 'error')
        emit_status('error', {'message': 'Invalid URL format. Expected: takeout-TIMESTAMP-N-NNN.zip'})
        with state_lock:
            download_state['is_running'] = False
        return
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Build download list
    downloads = []
    skipped = 0
    
    # Always start from file 1, regardless of which file the URL points to
    for i in range(1, file_count + 1):
        filename = f"takeout-{batch_num}-{i:03d}{extension}"
        file_path = output_path / filename
        
        if file_path.exists():
            skipped += 1
            continue
        
        current_url = f"{base_url}{batch_num}-{i:03d}{extension}"
        if query_string:
            current_url += f"?{query_string}"
        
        downloads.append({
            'index': len(downloads),
            'url': current_url,
            'path': file_path,
            'filename': filename,
            'status': 'pending',
        })
    
    with state_lock:
        download_state['stats']['total_files'] = len(downloads)
        download_state['stats']['skipped_files'] = skipped
        download_state['files'] = [{'filename': d['filename'], 'status': 'pending'} for d in downloads]
    
    add_log(f'Found {len(downloads)} files to download ({skipped} skipped)', 'info')
    emit_status('download_info', {
        'total': len(downloads),
        'skipped': skipped,
        'batch': batch_num,
        'start_file': start_file,
    })
    
    if not downloads:
        add_log(f'All {skipped} files already exist!', 'success')
        emit_status('download_complete', {
            'message': f'All {skipped} files already exist!',
            'stats': download_state['stats'],
        })
        with state_lock:
            download_state['is_running'] = False
        return
    
    # Run downloads in parallel
    auth_failed = False
    
    with ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = {
            executor.submit(download_file, d['url'], d['path'], d['index'], cookie): d
            for d in downloads
        }
        
        for future in as_completed(futures):
            if auth_failed:
                continue
                
            result = future.result()
            
            with state_lock:
                if result['success']:
                    download_state['stats']['completed_files'] += 1
                    download_state['files'][result['index']]['status'] = 'complete'
                else:
                    download_state['stats']['failed_files'] += 1
                    download_state['files'][result['index']]['status'] = 'failed'
                    
                    if result['auth_failed']:
                        auth_failed = True
            
            # Log file completion
            if result['success']:
                size_str = f"{result['size'] / (1024*1024*1024):.2f} GB" if result['size'] > 0 else ''
                add_log(f"✓ {result['filename']} complete ({size_str})", 'success')
            else:
                add_log(f"✗ {result['filename']}: {result['message']}", 'error')
            
            emit_status('file_complete', {
                'index': result['index'],
                'filename': result['filename'],
                'success': result['success'],
                'message': result['message'],
                'size': result['size'],
            })
            
            # Emit overall stats
            with state_lock:
                emit_status('stats_update', download_state['stats'])
    
    if auth_failed:
        add_log('⚠️ Authentication expired. Please provide a new cookie.', 'warning')
        emit_status('auth_required', {
            'message': 'Authentication expired. Please provide a new cookie.',
        })
    else:
        with state_lock:
            stats = download_state['stats']
            add_log(f"🎉 All downloads finished! {stats['completed_files']} completed, {stats['failed_files']} failed", 'success')
            emit_status('download_complete', {
                'message': 'All downloads finished!',
                'stats': stats,
            })
    
    with state_lock:
        download_state['is_running'] = False

# ============================================================================
# WEB ROUTES
# ============================================================================

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Google Takeout Downloader</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        :root {
            --bg-dark: #1e1e2e;
            --bg-medium: #2d2d3f;
            --bg-light: #3d3d5c;
            --accent: #7c3aed;
            --accent-hover: #8b5cf6;
            --success: #22c55e;
            --warning: #f59e0b;
            --error: #ef4444;
            --text: #f8fafc;
            --text-dim: #94a3b8;
            --border: #4b5563;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: var(--bg-dark);
            color: var(--text);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
        }
        
        header {
            text-align: center;
            margin-bottom: 30px;
        }
        
        h1 {
            font-size: 2rem;
            margin-bottom: 8px;
            background: linear-gradient(135deg, var(--accent), #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .subtitle {
            color: var(--text-dim);
            font-size: 0.95rem;
        }
        
        .card {
            background: var(--bg-medium);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            border: 1px solid var(--border);
        }
        
        .card h2 {
            font-size: 1.1rem;
            margin-bottom: 16px;
            color: var(--text);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .form-group {
            margin-bottom: 16px;
        }
        
        label {
            display: block;
            margin-bottom: 6px;
            color: var(--text-dim);
            font-size: 0.9rem;
        }
        
        input, textarea {
            width: 100%;
            padding: 12px;
            background: var(--bg-dark);
            border: 1px solid var(--border);
            border-radius: 8px;
            color: var(--text);
            font-size: 0.95rem;
            transition: border-color 0.2s;
        }
        
        input:focus, textarea:focus {
            outline: none;
            border-color: var(--accent);
        }
        
        textarea {
            min-height: 100px;
            resize: vertical;
            font-family: monospace;
        }
        
        .row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
        }
        
        button {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .btn-primary {
            background: var(--accent);
            color: white;
        }
        
        .btn-primary:hover:not(:disabled) {
            background: var(--accent-hover);
            transform: translateY(-1px);
        }
        
        .btn-primary:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .btn-danger {
            background: var(--error);
            color: white;
        }
        
        .btn-danger:hover {
            background: #dc2626;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 16px;
        }
        
        .stat-box {
            background: var(--bg-dark);
            padding: 16px;
            border-radius: 8px;
            text-align: center;
        }
        
        .stat-value {
            font-size: 1.8rem;
            font-weight: 700;
            color: var(--accent);
        }
        
        .stat-label {
            color: var(--text-dim);
            font-size: 0.85rem;
            margin-top: 4px;
        }
        
        .stat-box.success .stat-value { color: var(--success); }
        .stat-box.error .stat-value { color: var(--error); }
        .stat-box.warning .stat-value { color: var(--warning); }
        
        .log-container {
            background: var(--bg-dark);
            border-radius: 8px;
            padding: 16px;
            max-height: 400px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 0.85rem;
        }
        
        .log-entry {
            padding: 4px 0;
            border-bottom: 1px solid var(--border);
        }
        
        .log-entry:last-child {
            border-bottom: none;
        }
        
        .log-entry.success { color: var(--success); }
        .log-entry.error { color: var(--error); }
        .log-entry.info { color: var(--text-dim); }
        .log-entry.warning { color: var(--warning); }
        
        .file-list {
            max-height: 300px;
            overflow-y: auto;
        }
        
        .file-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 12px;
            background: var(--bg-dark);
            border-radius: 6px;
            margin-bottom: 8px;
        }
        
        .file-name {
            font-family: monospace;
            font-size: 0.9rem;
        }
        
        .file-status {
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        
        .file-status.pending { background: var(--bg-light); color: var(--text-dim); }
        .file-status.downloading { background: var(--accent); color: white; }
        .file-status.complete { background: var(--success); color: white; }
        .file-status.failed { background: var(--error); color: white; }
        
        .progress-bar {
            width: 100%;
            height: 8px;
            background: var(--bg-dark);
            border-radius: 4px;
            overflow: hidden;
            margin-top: 8px;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--accent), #a855f7);
            transition: width 0.3s ease;
        }
        
        .hidden { display: none; }
        
        .alert {
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 16px;
        }
        
        .alert-error {
            background: rgba(239, 68, 68, 0.2);
            border: 1px solid var(--error);
            color: var(--error);
        }
        
        .alert-success {
            background: rgba(34, 197, 94, 0.2);
            border: 1px solid var(--success);
            color: var(--success);
        }
        
        .help-text {
            font-size: 0.85rem;
            color: var(--text-dim);
            margin-top: 6px;
        }
        
        @media (max-width: 600px) {
            body { padding: 12px; }
            h1 { font-size: 1.5rem; }
            .card { padding: 16px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📦 Google Takeout Downloader</h1>
            <p class="subtitle">Web interface for headless environments</p>
        </header>
        
        <div id="alert-container"></div>
        
        <!-- Configuration Card -->
        <div class="card" id="config-card">
            <h2>⚙️ Configuration</h2>
            
            <div class="form-group">
                <label for="curl-input">cURL Command or Cookie</label>
                <textarea id="curl-input" placeholder="Paste the full cURL command from Chrome DevTools, or just the cookie value..."></textarea>
                <p class="help-text">Right-click a download request in DevTools Network tab → Copy → Copy as cURL</p>
            </div>
            
            <div class="form-group">
                <label for="url-input">Download URL (optional if using cURL)</label>
                <input type="text" id="url-input" placeholder="https://storage.cloud.google.com/takeout-...">
            </div>
            
            <div class="row">
                <div class="form-group">
                    <label for="output-dir">Output Directory</label>
                    <input type="text" id="output-dir" value="{{ output_dir }}">
                </div>
                <div class="form-group">
                    <label for="parallel">Parallel Downloads</label>
                    <input type="number" id="parallel" value="{{ parallel }}" min="1" max="10">
                </div>
                <div class="form-group">
                    <label for="file-count">Max Files</label>
                    <input type="number" id="file-count" value="{{ file_count }}" min="1" max="500">
                </div>
            </div>
            
            <button class="btn-primary" id="start-btn" onclick="startDownload()">
                🚀 Start Download
            </button>
        </div>
        
        <!-- Progress Card -->
        <div class="card hidden" id="progress-card">
            <h2>📊 Download Progress</h2>
            
            <div class="stats-grid">
                <div class="stat-box">
                    <div class="stat-value" id="stat-total">0</div>
                    <div class="stat-label">Total Files</div>
                </div>
                <div class="stat-box success">
                    <div class="stat-value" id="stat-complete">0</div>
                    <div class="stat-label">Completed</div>
                </div>
                <div class="stat-box error">
                    <div class="stat-value" id="stat-failed">0</div>
                    <div class="stat-label">Failed</div>
                </div>
                <div class="stat-box warning">
                    <div class="stat-value" id="stat-skipped">0</div>
                    <div class="stat-label">Skipped</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value" id="stat-size">0 GB</div>
                    <div class="stat-label">Downloaded</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value" id="stat-speed">0 MB/s</div>
                    <div class="stat-label">Speed</div>
                </div>
            </div>
            
            <div class="progress-bar" style="margin-top: 20px;">
                <div class="progress-fill" id="overall-progress" style="width: 0%"></div>
            </div>
        </div>
        
        <!-- Files Card -->
        <div class="card hidden" id="files-card">
            <h2>📁 Files</h2>
            <div class="file-list" id="file-list"></div>
        </div>
        
        <!-- Log Card -->
        <div class="card">
            <h2>📝 Activity Log</h2>
            <div class="log-container" id="log-container">
                <div class="log-entry info">Ready to start...</div>
            </div>
        </div>
    </div>
    
    <script>
        const socket = io();
        let downloadStartTime = null;
        let lastBytesDownloaded = 0;
        let lastSpeedUpdate = Date.now();
        
        function log(message, type = 'info') {
            const container = document.getElementById('log-container');
            const entry = document.createElement('div');
            entry.className = `log-entry ${type}`;
            const time = new Date().toLocaleTimeString();
            entry.textContent = `[${time}] ${message}`;
            container.appendChild(entry);
            container.scrollTop = container.scrollHeight;
        }
        
        function showAlert(message, type = 'error') {
            const container = document.getElementById('alert-container');
            container.innerHTML = `<div class="alert alert-${type}">${message}</div>`;
            setTimeout(() => container.innerHTML = '', 5000);
        }
        
        function formatBytes(bytes) {
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
            return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
        }
        
        function startDownload() {
            const curlInput = document.getElementById('curl-input').value.trim();
            const urlInput = document.getElementById('url-input').value.trim();
            const outputDir = document.getElementById('output-dir').value.trim();
            const parallel = parseInt(document.getElementById('parallel').value);
            const fileCount = parseInt(document.getElementById('file-count').value);
            
            if (!curlInput && !urlInput) {
                showAlert('Please provide a cURL command or cookie and URL');
                return;
            }
            
            document.getElementById('start-btn').disabled = true;
            document.getElementById('progress-card').classList.remove('hidden');
            document.getElementById('files-card').classList.remove('hidden');
            
            downloadStartTime = Date.now();
            lastBytesDownloaded = 0;
            
            log('Starting download...', 'info');
            
            fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    curl_input: curlInput,
                    url: urlInput,
                    output_dir: outputDir,
                    parallel: parallel,
                    file_count: fileCount,
                })
            })
            .then(res => res.json())
            .then(data => {
                if (data.error) {
                    showAlert(data.error);
                    document.getElementById('start-btn').disabled = false;
                }
            })
            .catch(err => {
                showAlert('Failed to start download: ' + err);
                document.getElementById('start-btn').disabled = false;
            });
        }
        
        // Socket event handlers
        
        // Handle state restoration on reconnect/refresh
        socket.on('restore_state', (state) => {
            console.log('Restoring state:', state);
            
            // Show progress cards if there's an active or completed session
            if (state.is_running || state.stats.total_files > 0) {
                document.getElementById('progress-card').classList.remove('hidden');
                document.getElementById('files-card').classList.remove('hidden');
                document.getElementById('start-btn').disabled = state.is_running;
            }
            
            // Restore stats
            document.getElementById('stat-total').textContent = state.stats.total_files;
            document.getElementById('stat-complete').textContent = state.stats.completed_files;
            document.getElementById('stat-failed').textContent = state.stats.failed_files;
            document.getElementById('stat-skipped').textContent = state.stats.skipped_files;
            document.getElementById('stat-size').textContent = formatBytes(state.stats.bytes_downloaded);
            lastBytesDownloaded = state.stats.bytes_downloaded;
            
            // Update progress bar
            const total = state.stats.total_files || 1;
            const completed = state.stats.completed_files + state.stats.failed_files;
            const percent = (completed / total) * 100;
            document.getElementById('overall-progress').style.width = percent + '%';
            
            // Restore file list
            const fileList = document.getElementById('file-list');
            fileList.innerHTML = '';
            state.files.forEach((file, index) => {
                updateFileStatus(index, file.filename, file.status);
            });
            
            // Restore log
            const logContainer = document.getElementById('log-container');
            logContainer.innerHTML = '';
            state.log.forEach(entry => {
                const div = document.createElement('div');
                div.className = `log-entry ${entry.type}`;
                div.textContent = `[${entry.time}] ${entry.message}`;
                logContainer.appendChild(div);
            });
            logContainer.scrollTop = logContainer.scrollHeight;
            
            if (state.is_running) {
                log('Reconnected to active download session', 'info');
            }
        });
        
        // Handle individual log entries
        socket.on('log_entry', (entry) => {
            const container = document.getElementById('log-container');
            const div = document.createElement('div');
            div.className = `log-entry ${entry.type}`;
            div.textContent = `[${entry.time}] ${entry.message}`;
            container.appendChild(div);
            container.scrollTop = container.scrollHeight;
        });
        
        socket.on('download_started', (data) => {
            log(data.message, 'info');
        });
        
        socket.on('download_info', (data) => {
            document.getElementById('stat-total').textContent = data.total;
            document.getElementById('stat-skipped').textContent = data.skipped;
            log(`Found ${data.total} files to download (${data.skipped} skipped)`, 'info');
        });
        
        socket.on('file_start', (data) => {
            log(`Starting: ${data.filename} (${formatBytes(data.size)})`, 'info');
            updateFileStatus(data.index, data.filename, 'downloading');
        });
        
        socket.on('file_progress', (data) => {
            updateFileProgress(data.index, data.percent);
        });
        
        socket.on('file_complete', (data) => {
            if (data.success) {
                log(`✓ ${data.filename} complete (${formatBytes(data.size)})`, 'success');
                updateFileStatus(data.index, data.filename, 'complete');
            } else {
                log(`✗ ${data.filename}: ${data.message}`, 'error');
                updateFileStatus(data.index, data.filename, 'failed');
            }
        });
        
        socket.on('stats_update', (stats) => {
            document.getElementById('stat-complete').textContent = stats.completed_files;
            document.getElementById('stat-failed').textContent = stats.failed_files;
            document.getElementById('stat-size').textContent = formatBytes(stats.bytes_downloaded);
            
            // Calculate speed
            const now = Date.now();
            const elapsed = (now - lastSpeedUpdate) / 1000;
            if (elapsed >= 1) {
                const bytesDelta = stats.bytes_downloaded - lastBytesDownloaded;
                const speed = bytesDelta / elapsed;
                document.getElementById('stat-speed').textContent = formatBytes(speed) + '/s';
                lastBytesDownloaded = stats.bytes_downloaded;
                lastSpeedUpdate = now;
            }
            
            // Update progress bar
            const total = parseInt(document.getElementById('stat-total').textContent) || 1;
            const completed = stats.completed_files + stats.failed_files;
            const percent = (completed / total) * 100;
            document.getElementById('overall-progress').style.width = percent + '%';
        });
        
        socket.on('auth_required', (data) => {
            log('⚠️ ' + data.message, 'warning');
            showAlert(data.message + ' Please update the cookie and restart.', 'error');
            document.getElementById('start-btn').disabled = false;
        });
        
        socket.on('download_complete', (data) => {
            log('🎉 ' + data.message, 'success');
            showAlert(data.message, 'success');
            document.getElementById('start-btn').disabled = false;
        });
        
        socket.on('error', (data) => {
            log('Error: ' + data.message, 'error');
            showAlert(data.message);
            document.getElementById('start-btn').disabled = false;
        });
        
        function updateFileStatus(index, filename, status) {
            const list = document.getElementById('file-list');
            let item = document.getElementById(`file-${index}`);
            
            if (!item) {
                item = document.createElement('div');
                item.id = `file-${index}`;
                item.className = 'file-item';
                item.innerHTML = `
                    <span class="file-name">${filename}</span>
                    <span class="file-status ${status}">${status}</span>
                `;
                list.appendChild(item);
            } else {
                item.querySelector('.file-status').className = `file-status ${status}`;
                item.querySelector('.file-status').textContent = status;
            }
        }
        
        function updateFileProgress(index, percent) {
            const item = document.getElementById(`file-${index}`);
            if (item) {
                const statusEl = item.querySelector('.file-status');
                statusEl.textContent = `${percent}%`;
            }
        }
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(
        HTML_TEMPLATE,
        output_dir=DEFAULT_OUTPUT_DIR,
        parallel=DEFAULT_PARALLEL,
        file_count=DEFAULT_FILE_COUNT,
    )

@app.route('/api/start', methods=['POST'])
def api_start():
    data = request.json
    
    with state_lock:
        if download_state['is_running']:
            return jsonify({'error': 'Download already in progress'})
    
    curl_input = data.get('curl_input', '')
    url = data.get('url', '')
    output_dir = data.get('output_dir', DEFAULT_OUTPUT_DIR)
    parallel = data.get('parallel', DEFAULT_PARALLEL)
    file_count = data.get('file_count', DEFAULT_FILE_COUNT)
    
    # Extract cookie from cURL
    cookie = extract_cookie_from_curl(curl_input) if curl_input else ''
    
    if not cookie:
        return jsonify({'error': 'Could not extract cookie from input'})
    
    # Try to extract URL from cURL if not provided
    if not url and curl_input:
        url = extract_url_from_curl(curl_input)
    
    if not url:
        return jsonify({'error': 'No download URL provided'})
    
    # Start download in background thread
    thread = threading.Thread(
        target=run_downloads,
        args=(cookie, url, output_dir, parallel, file_count),
        daemon=True
    )
    thread.start()
    
    return jsonify({'status': 'started'})

@app.route('/api/status')
def api_status():
    """Get full current state for page refresh/reconnection."""
    with state_lock:
        return jsonify({
            'is_running': download_state['is_running'],
            'stats': download_state['stats'],
            'files': download_state['files'],
            'log': download_state['log'],
        })

@socketio.on('connect')
def handle_connect():
    """Send current state to newly connected/reconnected clients."""
    with state_lock:
        if download_state['is_running'] or download_state['stats']['total_files'] > 0:
            # Send current state to the reconnecting client
            emit('restore_state', {
                'is_running': download_state['is_running'],
                'stats': download_state['stats'],
                'files': download_state['files'],
                'log': download_state['log'],
            })

# ============================================================================
# MAIN
# ============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Google Takeout Downloader - Web Interface')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to (default: 5000)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║         Google Takeout Downloader - Web Interface            ║
╠══════════════════════════════════════════════════════════════╣
║  Open your browser to: http://{args.host}:{args.port:<5}                    ║
║  Press Ctrl+C to stop                                        ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    socketio.run(app, host=args.host, port=args.port, debug=args.debug, allow_unsafe_werkzeug=True)

if __name__ == '__main__':
    main()

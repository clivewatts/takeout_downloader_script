#!/usr/bin/env python3
"""
Google Takeout Bulk Downloader
==============================
Downloads Google Takeout archives. Simple and robust.

Usage:
    python takeout.py                    # TUI mode (default)
    python takeout.py --web              # Web interface
    python takeout.py --web --port 8080  # Web on custom port

Features:
    - Parallel downloads (configurable 1-20)
    - Auto-retry on failure with new cURL
    - Track file sizes to detect incomplete downloads
    - Resume from last good file
"""

import os
import re
import sys
import json
import time
import threading
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Callable
from datetime import datetime
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# =============================================================================
# CONFIGURATION & CONSTANTS
# =============================================================================

VERSION = "4.0.0"
CHUNK_SIZE = 1024 * 1024  # 1MB chunks
DEFAULT_PARALLEL = 1
MAX_PARALLEL = 20
DEFAULT_FILE_COUNT = 100
DEFAULT_OUTPUT_DIR = "./downloads"
SIZE_HISTORY_FILE = ".takeout_sizes.json"

# =============================================================================
# DATA CLASSES  
# =============================================================================

@dataclass
class DownloadStats:
    """Simple download statistics."""
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0
    bytes_downloaded: int = 0
    start_time: Optional[datetime] = None


# =============================================================================
# SIZE HISTORY - Track known file sizes for detecting incomplete downloads
# =============================================================================

class SizeHistory:
    """Track known file sizes to detect incomplete downloads."""
    
    def __init__(self, output_dir: str):
        self.path = Path(output_dir) / SIZE_HISTORY_FILE
        self.sizes: Dict[str, int] = {}
        self.load()
    
    def load(self):
        """Load size history from file."""
        if self.path.exists():
            try:
                with open(self.path) as f:
                    self.sizes = json.load(f)
            except:
                self.sizes = {}
    
    def save(self):
        """Save size history to file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'w') as f:
            json.dump(self.sizes, f, indent=2)
    
    def get_expected_size(self, filename: str) -> Optional[int]:
        """Get expected size for a file, if known."""
        return self.sizes.get(filename)
    
    def record_size(self, filename: str, size: int):
        """Record a successful download size."""
        self.sizes[filename] = size
        self.save()


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def extract_url_parts(url: str) -> Tuple[Optional[str], Optional[int], Optional[str], str]:
    """Extract URL parts for Google Takeout pattern.
    
    Pattern: takeout-TIMESTAMP-BATCH-FILENUM.zip
    Example: takeout-20251207T071725Z-3-003.zip
    
    Returns: (base_url_with_batch, file_num, extension, query_string)
    """
    if '?' in url:
        url_path, query_string = url.split('?', 1)
    else:
        url_path, query_string = url, ''
    
    # Match pattern: takeout-TIMESTAMP-BATCH-FILENUM.zip
    # Example: takeout-20251207T071725Z-3-003.zip
    #          base = everything up to and including "3-"
    #          file_num = 003
    match = re.search(r'(.*takeout-\d{8}T\d{6}Z-\d+-)(\d{3})(\.\w+)$', url_path)
    if not match:
        # Try alternate pattern without timestamp
        match = re.search(r'(.*takeout-[^-]+-\d+-)(\d{3})(\.\w+)$', url_path)
        if not match:
            return None, None, None, ''
    
    base = match.group(1)
    file_num = int(match.group(2))
    ext = match.group(3)
    
    return base, file_num, ext, query_string


def extract_cookie_from_curl(curl_text: str) -> str:
    """Extract cookie value from a cURL command or raw cookie string."""
    # Try to find Cookie header in cURL command
    match = re.search(r"-H\s*['\"]Cookie:\s*([^'\"]+)['\"]", curl_text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    # Handle "Cookie: value" format
    if curl_text.lower().startswith('cookie:'):
        return curl_text[7:].strip()
    
    # Just return as-is (might be raw cookie)
    cookie = curl_text.strip()
    if (cookie.startswith("'") and cookie.endswith("'")) or \
       (cookie.startswith('"') and cookie.endswith('"')):
        cookie = cookie[1:-1]
    
    return cookie


def extract_url_from_curl(curl_text: str) -> Optional[str]:
    """Extract the download URL from a cURL command."""
    match = re.search(r"curl\s+['\"]?(https?://[^'\"\s]+)['\"]?", curl_text, re.IGNORECASE)
    if match:
        url = match.group(1)
        if 'takeout' in url.lower():
            return url
    return None


# =============================================================================
# DOWNLOAD ENGINE - Simple and Robust
# =============================================================================

class TakeoutDownloader:
    """
    Simple downloader that:
    1. Keeps trying to download
    2. On failure, prompts for new cURL
    3. Tracks known sizes to detect incomplete downloads
    4. Cleans up bad zips and resumes from last good
    """
    
    def __init__(self, output_dir: str = DEFAULT_OUTPUT_DIR, parallel: int = DEFAULT_PARALLEL):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.size_history = SizeHistory(output_dir)
        self.cookie = ""
        self.base_url = ""
        self.query_string = ""
        self.extension = ".zip"
        self.file_count = DEFAULT_FILE_COUNT
        self.parallel = min(max(1, parallel), MAX_PARALLEL)  # Clamp to 1-20
        self.should_stop = False
        self.auth_failed = False  # Flag for parallel downloads
        self.stats = DownloadStats()
        self._lock = threading.Lock()  # For thread-safe stats updates
    
    def set_curl(self, curl_text: str) -> bool:
        """Set cookie and URL from cURL command."""
        # Extract cookie
        self.cookie = extract_cookie_from_curl(curl_text)
        if not self.cookie:
            print("✗ Could not extract cookie from cURL")
            return False
        
        # Extract URL
        url = extract_url_from_curl(curl_text)
        if not url:
            print("✗ Could not extract URL from cURL")
            return False
        
        # Parse URL parts
        base, file_num, ext, query = extract_url_parts(url)
        if not base:
            print("✗ Could not parse URL pattern")
            return False
        
        self.base_url = base
        self.extension = ext
        self.query_string = query
        
        print(f"✓ Cookie: {len(self.cookie)} chars")
        print(f"✓ URL pattern: {base}XXX{ext}")
        return True
    
    def get_filename(self, num: int) -> str:
        """Get filename for file number."""
        return f"{self.base_url.split('/')[-1]}{num:03d}{self.extension}"
    
    def get_url(self, num: int) -> str:
        """Get URL for file number."""
        url = f"{self.base_url}{num:03d}{self.extension}"
        if self.query_string:
            url += f"?{self.query_string}"
        return url
    
    def get_filepath(self, num: int) -> Path:
        """Get local file path for file number."""
        return self.output_dir / self.get_filename(num)
    
    def cleanup_bad_files(self) -> int:
        """
        Clean up zero-sized and incomplete files.
        Returns the first file number that needs downloading.
        """
        first_missing = None
        
        for num in range(1, self.file_count + 1):
            filepath = self.get_filepath(num)
            
            if not filepath.exists():
                if first_missing is None:
                    first_missing = num
                continue
            
            size = filepath.stat().st_size
            
            # Zero-sized = definitely bad
            if size == 0:
                print(f"  Deleting zero-sized: {filepath.name}")
                filepath.unlink()
                if first_missing is None:
                    first_missing = num
                continue
            
            # Check against known size
            expected = self.size_history.get_expected_size(filepath.name)
            if expected and size < expected:
                print(f"  Deleting incomplete: {filepath.name} ({size} < {expected})")
                filepath.unlink()
                if first_missing is None:
                    first_missing = num
                continue
            
            # File looks good, record its size
            if not expected:
                self.size_history.record_size(filepath.name, size)
        
        return first_missing if first_missing is not None else 1
    
    def download_file(self, num: int) -> Tuple[bool, str]:
        """
        Download a single file.
        Returns: (success, error_message)
        """
        filepath = self.get_filepath(num)
        url = self.get_url(num)
        
        # Skip if already exists and looks complete
        if filepath.exists():
            size = filepath.stat().st_size
            expected = self.size_history.get_expected_size(filepath.name)
            if size > 0 and (not expected or size >= expected):
                return True, "already exists"
        
        try:
            response = requests.get(
                url,
                headers={
                    'Cookie': self.cookie,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                },
                stream=True,
                timeout=(10, 300),
            )
            
            # Check for auth failure via status
            if response.status_code in (401, 403):
                return False, "AUTH_FAILED"
            
            # Check for redirect to login
            if response.status_code == 302 or 'accounts.google' in response.url:
                return False, "AUTH_FAILED"
            
            response.raise_for_status()
            
            # Check content type
            content_type = response.headers.get('content-type', '')
            if 'text/html' in content_type:
                return False, "AUTH_FAILED"
            
            # Get expected size
            total_size = int(response.headers.get('content-length', 0))
            if total_size < 1000:
                return False, "AUTH_FAILED"  # Too small, probably auth page
            
            # Download to temp file first
            temp_path = filepath.with_suffix('.downloading')
            downloaded = 0
            
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if self.should_stop:
                        temp_path.unlink()
                        return False, "stopped"
                    
                    if chunk:
                        # Check first chunk for ZIP magic
                        if downloaded == 0 and chunk[:2] != b'PK':
                            temp_path.unlink()
                            return False, "AUTH_FAILED"
                        
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # Progress
                        pct = (downloaded / total_size * 100) if total_size else 0
                        print(f"\r  [{filepath.name}] {downloaded/(1024*1024):.1f}MB / {total_size/(1024*1024):.1f}MB ({pct:.0f}%)", end='', flush=True)
            
            print()  # Newline after progress
            
            # Rename to final
            temp_path.rename(filepath)
            
            # Record size for future reference
            self.size_history.record_size(filepath.name, downloaded)
            
            return True, ""
            
        except requests.exceptions.HTTPError as e:
            if e.response and e.response.status_code == 404:
                return False, "NOT_FOUND"
            return False, f"HTTP error: {e}"
        except requests.exceptions.RequestException as e:
            return False, f"Network error: {e}"
    
    def prompt_new_curl(self) -> bool:
        """Prompt user for new cURL command. Returns True if successful."""
        print("\n" + "=" * 60)
        print("🔐 AUTHENTICATION NEEDED")
        print("=" * 60)
        print("\nTo get a new cURL command:")
        print("1. Go to takeout.google.com in your browser")
        print("2. Open DevTools (F12) -> Network tab")
        print("3. Click any download link")
        print("4. Right-click the request -> Copy -> Copy as cURL")
        print("\nPaste the cURL command (or 'q' to quit):")
        print("-" * 60)
        
        try:
            lines = []
            while True:
                line = input()
                if line.strip().lower() == 'q':
                    return False
                lines.append(line)
                # cURL commands can span multiple lines with backslash
                if not line.rstrip().endswith('\\'):
                    break
            
            curl_text = ' '.join(lines)
            if not curl_text.strip():
                return False
            
            return self.set_curl(curl_text)
            
        except (EOFError, KeyboardInterrupt):
            return False
    
    def run(self, file_count: int = DEFAULT_FILE_COUNT) -> DownloadStats:
        """
        Main download loop.
        Keeps trying until all files downloaded or user quits.
        Supports parallel downloads with simple auth retry.
        """
        self.file_count = file_count
        self.stats = DownloadStats(start_time=datetime.now())
        self.should_stop = False
        self.auth_failed = False
        
        print(f"\nGoogle Takeout Downloader v{VERSION}")
        print(f"Output: {self.output_dir}")
        print(f"Max files: {file_count}")
        print(f"Parallel: {self.parallel}")
        print("-" * 60)
        
        # Initial cURL if not set
        if not self.cookie or not self.base_url:
            if not self.prompt_new_curl():
                print("No cURL provided, exiting.")
                return self.stats
        
        while not self.should_stop:
            # Clean up any bad files first
            print(f"\nChecking for incomplete downloads...")
            first_needed = self.cleanup_bad_files()
            
            # Build list of files to download
            to_download = []
            for num in range(first_needed, file_count + 1):
                filepath = self.get_filepath(num)
                if filepath.exists() and filepath.stat().st_size > 0:
                    expected = self.size_history.get_expected_size(filepath.name)
                    if not expected or filepath.stat().st_size >= expected:
                        continue  # Skip existing good files
                to_download.append(num)
            
            if not to_download:
                print("\nAll files downloaded!")
                break
            
            print(f"\nDownloading {len(to_download)} files starting from {to_download[0]}...")
            
            # Reset auth flag
            self.auth_failed = False
            consecutive_404 = 0
            
            if self.parallel == 1:
                # Sequential mode (simpler)
                for num in to_download:
                    if self.should_stop or self.auth_failed:
                        break
                    
                    filepath = self.get_filepath(num)
                    success, error = self.download_file(num)
                    
                    if success:
                        print(f"✓ {filepath.name}")
                        with self._lock:
                            self.stats.completed_files += 1
                        consecutive_404 = 0
                        
                    elif error == "AUTH_FAILED":
                        print(f"\n✗ Auth failed on file {num}")
                        self.auth_failed = True
                        break
                        
                    elif error == "NOT_FOUND":
                        consecutive_404 += 1
                        print(f"✗ {filepath.name} not found (404)")
                        if consecutive_404 >= 3:
                            print(f"\n3 consecutive 404s - assuming done")
                            self.should_stop = True
                            break
                            
                    else:
                        print(f"✗ {filepath.name}: {error}")
                        with self._lock:
                            self.stats.failed_files += 1
                        consecutive_404 = 0
            else:
                # Parallel mode
                with ThreadPoolExecutor(max_workers=self.parallel) as executor:
                    futures = {executor.submit(self.download_file, num): num for num in to_download}
                    
                    for future in as_completed(futures):
                        if self.should_stop or self.auth_failed:
                            # Cancel remaining futures
                            for f in futures:
                                f.cancel()
                            break
                        
                        num = futures[future]
                        filepath = self.get_filepath(num)
                        
                        try:
                            success, error = future.result()
                            
                            if success:
                                print(f"✓ {filepath.name}")
                                with self._lock:
                                    self.stats.completed_files += 1
                                    
                            elif error == "AUTH_FAILED":
                                print(f"\n✗ Auth failed on file {num}")
                                self.auth_failed = True
                                
                            elif error == "NOT_FOUND":
                                print(f"✗ {filepath.name} not found (404)")
                                # Don't track consecutive 404s in parallel mode
                                
                            else:
                                print(f"✗ {filepath.name}: {error}")
                                with self._lock:
                                    self.stats.failed_files += 1
                                    
                        except Exception as e:
                            print(f"✗ {filepath.name}: {e}")
                            with self._lock:
                                self.stats.failed_files += 1
            
            # Handle auth failure - prompt for new cURL and retry
            if self.auth_failed:
                if not self.prompt_new_curl():
                    print("No new cURL provided, stopping.")
                    break
                # Loop will continue and retry remaining files
            else:
                # No auth failure - we're done
                break
        
        # Summary
        print("\n" + "=" * 60)
        print(f"✅ Done!")
        print(f"   Completed: {self.stats.completed_files}")
        print(f"   Skipped:   {self.stats.skipped_files}")
        print(f"   Failed:    {self.stats.failed_files}")
        print("=" * 60)
        
        return self.stats
    
    def stop(self):
        """Stop downloading."""
        self.should_stop = True


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point - TUI by default, --web for web interface."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Google Takeout Bulk Downloader',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # TUI mode (default)
  %(prog)s --web                    # Web interface
  %(prog)s --web --port 8080        # Web on custom port
        """
    )
    
    # Mode selection
    parser.add_argument('--web', action='store_true', 
                       help='Start web interface instead of TUI')
    
    # Web options
    parser.add_argument('--port', type=int, default=5000, 
                       help='Web server port (default: 5000)')
    parser.add_argument('--host', default='0.0.0.0', 
                       help='Web server host (default: 0.0.0.0)')
    
    parser.add_argument('--version', '-v', action='version', 
                       version=f'%(prog)s {VERSION}')
    
    args = parser.parse_args()
    
    if args.web:
        run_web(args.host, args.port)
    else:
        run_tui()


def run_tui():
    """Run terminal UI."""
    try:
        from google_takeout_tui import TakeoutTUI
        app = TakeoutTUI()
        app.run()
    except ImportError as e:
        print(f"TUI mode requires textual: {e}")
        print("Install with: pip install textual rich requests")
        sys.exit(1)


def run_web(host: str, port: int):
    """Run web interface."""
    try:
        from google_takeout_web import create_app
        app, socketio = create_app()
        print(f"\n🌐 Starting web interface on http://{host}:{port}")
        socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
    except ImportError as e:
        print(f"Web mode requires Flask: {e}")
        print("Install with: pip install flask flask-socketio requests")
        sys.exit(1)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
import os
import re
import sys
import time
import subprocess
import requests
from urllib.parse import urlparse
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta

def load_env_file(env_path: Path = None):
    """Load environment variables from .env file."""
    if env_path is None:
        env_path = Path(__file__).parent / '.env'
    
    if not env_path.exists():
        return
    
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)

def extract_cookie_from_curl_early(curl_text: str) -> str:
    """Extract cookie value from a cURL command (early version for arg parsing)."""
    if 'curl' in curl_text or "-H 'Cookie:" in curl_text or '-H "Cookie:' in curl_text:
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

def extract_url_from_curl_early(curl_text: str) -> str:
    """Extract the download URL from a cURL command (early version for arg parsing)."""
    match = re.search(r"curl\s+['\"]?(https?://[^'\"\s]+)['\"]?", curl_text, re.IGNORECASE)
    if match:
        url = match.group(1)
        if 'takeout' in url.lower():
            return url
    return None

def parse_arguments():
    import argparse
    
    # Load .env file first
    load_env_file()
    
    parser = argparse.ArgumentParser(description='Download Google Takeout files using auth cookie')
    parser.add_argument('--cookie', 
                        default=os.environ.get('GOOGLE_COOKIE'),
                        help='Full cookie header string from browser (or set GOOGLE_COOKIE in .env)')
    parser.add_argument('--url', 
                        default=os.environ.get('TAKEOUT_URL'),
                        help='First download URL (or set TAKEOUT_URL in .env)')
    parser.add_argument('--output', 
                        default=os.environ.get('OUTPUT_DIR', './downloads'),
                        help='Output directory (default: ./downloads or OUTPUT_DIR in .env)')
    parser.add_argument('--count', 
                        type=int, 
                        default=int(os.environ.get('FILE_COUNT', '100')),
                        help='Maximum number of files to download (default: 100 or FILE_COUNT in .env)')
    parser.add_argument('--parallel', 
                        type=int, 
                        default=int(os.environ.get('PARALLEL_DOWNLOADS', '6')),
                        help='Number of parallel downloads (default: 6 or PARALLEL_DOWNLOADS in .env)')
    
    args = parser.parse_args()
    
    # Validate required args
    if not args.cookie:
        parser.error('Cookie is required. Set --cookie or GOOGLE_COOKIE in .env')
    
    # Try to extract URL from cookie if it's a cURL command and no URL provided
    if not args.url and args.cookie:
        extracted_url = extract_url_from_curl_early(args.cookie)
        if extracted_url:
            args.url = extracted_url
            print(f"✓ Auto-extracted URL from cURL command")
    
    if not args.url:
        parser.error('URL is required. Set --url, TAKEOUT_URL in .env, or paste full cURL as --cookie')
    
    # Extract actual cookie if full cURL was provided
    if 'curl' in args.cookie.lower():
        args.cookie = extract_cookie_from_curl_early(args.cookie)
    
    return args

def extract_url_parts(url: str) -> tuple[str, int, int, str, str]:
    """Extract URL parts for Google Takeout pattern.
    
    Pattern: takeout-TIMESTAMP-N-NNN.zip?query
    Example: takeout-20251204T101148Z-3-001.zip?j=xxx&i=0&user=xxx
    
    Returns: (base_url, batch_num, file_num, extension, query_string)
    """
    # Split URL and query string
    if '?' in url:
        url_path, query_string = url.split('?', 1)
    else:
        url_path, query_string = url, ''
    
    # Match pattern: takeout-TIMESTAMP-BATCH-FILENUM.zip
    match = re.search(r'(.*takeout-[^-]+-)(\d+)-(\d+)(\.\w+)$', url_path)
    if not match:
        print(f"Error: URL doesn't match expected pattern")
        print(f"Expected: takeout-TIMESTAMP-N-NNN.zip")
        print(f"Got: {url_path}")
        sys.exit(1)
    
    base = match.group(1)  # Everything up to batch number
    batch_num = int(match.group(2))  # The batch number (3 in your case)
    file_num = int(match.group(3))  # The file number (001)
    ext = match.group(4)  # .zip
    
    return base, batch_num, file_num, ext, query_string

def create_session(cookie: str) -> requests.Session:
    """Create a requests session with the provided cookie header."""
    session = requests.Session()
    # Set the full cookie header directly
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Cookie': cookie,
    })
    return session

# Thread-safe print lock
print_lock = threading.Lock()
# Shared cookie that can be updated
cookie_lock = threading.Lock()
current_cookie = None
# Track download statistics
stats_lock = threading.Lock()
download_stats = {
    'start_time': None,
    'bytes_downloaded': 0,
    'files_completed': 0,
    'total_files': 0,
    'total_bytes': 0,
    'auth_start_time': None,  # When current auth session started
}

# Auth timeout warning (Google sessions typically last ~1 hour)
AUTH_WARNING_MINUTES = 45

def safe_print(*args, **kwargs):
    """Thread-safe print."""
    with print_lock:
        print(*args, **kwargs)

def send_notification(title: str, message: str, urgent: bool = False):
    """Send desktop notification (Linux)."""
    try:
        urgency = 'critical' if urgent else 'normal'
        subprocess.run(
            ['notify-send', '-u', urgency, '-a', 'Takeout Downloader', title, message],
            capture_output=True,
            timeout=5
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # notify-send not available or timed out

def play_sound(sound_type: str = 'alert'):
    """Play a sound alert (Linux)."""
    try:
        if sound_type == 'alert':
            # Try paplay (PulseAudio) first
            subprocess.run(
                ['paplay', '/usr/share/sounds/freedesktop/stereo/dialog-warning.oga'],
                capture_output=True,
                timeout=5
            )
        elif sound_type == 'complete':
            subprocess.run(
                ['paplay', '/usr/share/sounds/freedesktop/stereo/complete.oga'],
                capture_output=True,
                timeout=5
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # Try beep as fallback
        try:
            subprocess.run(['beep'], capture_output=True, timeout=2)
        except:
            pass  # No sound available

def update_stats(bytes_downloaded: int = 0, file_completed: bool = False):
    """Update download statistics."""
    with stats_lock:
        download_stats['bytes_downloaded'] += bytes_downloaded
        if file_completed:
            download_stats['files_completed'] += 1

def get_eta() -> str:
    """Calculate estimated time remaining."""
    with stats_lock:
        if not download_stats['start_time'] or download_stats['bytes_downloaded'] == 0:
            return "calculating..."
        
        elapsed = (datetime.now() - download_stats['start_time']).total_seconds()
        if elapsed < 1:
            return "calculating..."
        
        bytes_per_sec = download_stats['bytes_downloaded'] / elapsed
        remaining_bytes = download_stats['total_bytes'] - download_stats['bytes_downloaded']
        
        if bytes_per_sec > 0:
            remaining_secs = remaining_bytes / bytes_per_sec
            if remaining_secs < 60:
                return f"{int(remaining_secs)}s"
            elif remaining_secs < 3600:
                return f"{int(remaining_secs / 60)}m"
            else:
                hours = int(remaining_secs / 3600)
                mins = int((remaining_secs % 3600) / 60)
                return f"{hours}h {mins}m"
        return "unknown"

def check_auth_expiry_warning() -> bool:
    """Check if auth might expire soon and warn user."""
    with stats_lock:
        if download_stats['auth_start_time']:
            elapsed = datetime.now() - download_stats['auth_start_time']
            if elapsed > timedelta(minutes=AUTH_WARNING_MINUTES):
                return True
    return False

def reset_auth_timer():
    """Reset the auth timer when new cookie is provided."""
    with stats_lock:
        download_stats['auth_start_time'] = datetime.now()

def get_current_cookie() -> str:
    """Get the current cookie value (thread-safe)."""
    with cookie_lock:
        return current_cookie

def set_current_cookie(cookie: str):
    """Set the current cookie value (thread-safe)."""
    global current_cookie
    with cookie_lock:
        current_cookie = cookie

def extract_cookie_from_curl(curl_text: str) -> str:
    """Extract cookie value from a cURL command or raw cookie string."""
    # Check if it's a cURL command
    if 'curl' in curl_text or "-H 'Cookie:" in curl_text or '-H "Cookie:' in curl_text:
        # Try to find cookie header with single quotes
        match = re.search(r"-H\s*['\"]Cookie:\s*([^'\"]+)['\"]", curl_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Try alternate format: -H 'cookie: ...'
        match = re.search(r"-H\s*['\"]cookie:\s*([^'\"]+)['\"]", curl_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    # Check if it starts with "cookie:" header format
    if curl_text.lower().startswith('cookie:'):
        return curl_text[7:].strip()
    
    # Assume it's already just the cookie value
    # Clean up quotes if present
    cookie = curl_text.strip()
    if (cookie.startswith("'") and cookie.endswith("'")) or \
       (cookie.startswith('"') and cookie.endswith('"')):
        cookie = cookie[1:-1]
    
    return cookie

def extract_url_from_curl(curl_text: str) -> str:
    """Extract the download URL from a cURL command."""
    # Match URL in curl command: curl 'URL' or curl "URL"
    match = re.search(r"curl\s+['\"]?(https?://[^'\"\s]+)['\"]?", curl_text, re.IGNORECASE)
    if match:
        url = match.group(1)
        # Verify it's a takeout URL
        if 'takeout' in url.lower():
            return url
    return None

def prompt_for_new_cookie(is_warning: bool = False) -> str:
    """Prompt user for new cookie interactively."""
    # Send notification and sound
    if is_warning:
        send_notification(
            "⚠️ Auth Expiring Soon",
            "Google Takeout session may expire soon. Consider refreshing cookie.",
            urgent=False
        )
        play_sound('alert')
        print("\n" + "=" * 60)
        print("⚠️  AUTH MAY EXPIRE SOON")
        print("=" * 60)
        print(f"\nSession has been active for ~{AUTH_WARNING_MINUTES} minutes.")
        print("Google sessions typically expire after ~1 hour.")
        print("\nWould you like to refresh your cookie now? (y/n/q)")
        print("-" * 60)
        
        try:
            response = input().strip().lower()
            if response == 'n':
                return None  # Continue without refresh
            elif response == 'q':
                return 'QUIT'
            # Fall through to cookie prompt
        except (EOFError, KeyboardInterrupt):
            return None
    else:
        send_notification(
            "🔐 Authentication Required",
            "Google Takeout cookie expired. Please provide new cookie.",
            urgent=True
        )
        play_sound('alert')
        print("\n" + "=" * 60)
        print("🔐 AUTHENTICATION EXPIRED")
        print("=" * 60)
    
    print("\nTo get a new cookie:")
    print("1. Open Chrome DevTools (F12) on Google Takeout")
    print("2. Go to Network tab")
    print("3. Click a download link")
    print("4. Right-click the request -> Copy -> Copy as cURL")
    print("\nPaste the ENTIRE cURL command below (or 'q' to quit):")
    print("(You can paste the whole thing, we'll extract the cookie)")
    print("-" * 60)
    
    try:
        # Read multiple lines until we get a complete input
        lines = []
        while True:
            try:
                line = input()
                if line.strip().lower() == 'q':
                    return None
                lines.append(line)
                # Check if we have a complete cURL command or cookie
                full_text = ' '.join(lines)
                # If it looks complete (ends with quote or doesn't have continuation)
                if not line.rstrip().endswith('\\'):
                    break
            except EOFError:
                break
        
        full_text = ' '.join(lines)
        if not full_text.strip():
            return None
            
        cookie = extract_cookie_from_curl(full_text)
        if cookie:
            print(f"\nExtracted cookie ({len(cookie)} chars)")
            return cookie
        else:
            print("\nCouldn't extract cookie from input")
            return None
            
    except KeyboardInterrupt:
        return None

# Chunk size for downloads (8MB for better throughput)
CHUNK_SIZE = 8 * 1024 * 1024

def create_fast_session(cookie: str) -> requests.Session:
    """Create an optimized session for fast downloads."""
    session = requests.Session()
    
    # Configure connection pooling and retries
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
        'Accept-Encoding': 'identity',  # Disable compression for large files
        'Connection': 'keep-alive',
        'Cookie': cookie,
    })
    return session

def download_file(url: str, output_path: Path, file_num: int) -> tuple[int, bool, str, bool]:
    """Download a single file with progress tracking. Returns (file_num, success, message, auth_failed)."""
    cookie = get_current_cookie()
    session = create_fast_session(cookie)
    
    filename = output_path.name
    try:
        with session.get(url, stream=True, allow_redirects=True, timeout=(10, 300)) as r:
            r.raise_for_status()
            
            # Check content type - should be application/zip, not text/html
            content_type = r.headers.get('content-type', '')
            if 'text/html' in content_type:
                preview = r.content[:500].decode('utf-8', errors='ignore')
                if 'signin' in preview.lower() or 'login' in preview.lower():
                    return (file_num, False, f"[{filename}] Auth failed - cookies invalid/expired", True)
                return (file_num, False, f"[{filename}] Got HTML instead of ZIP", False)
            
            total_size = int(r.headers.get('content-length', 0))
            
            # Validate file size - Google Takeout files are typically large
            if total_size < 1000000:  # Less than 1MB is suspicious
                return (file_num, False, f"[{filename}] File too small ({total_size} bytes) - likely not valid")
            
            # Create parent directory if it doesn't exist
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            size_gb = total_size / (1024*1024*1024)
            safe_print(f"[{filename}] Starting ({size_gb:.2f} GB)")
            
            # Use larger buffer for writing
            with open(output_path, 'wb', buffering=CHUNK_SIZE) as f:
                downloaded = 0
                last_percent = 0
                for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        update_stats(bytes_downloaded=len(chunk))
                        if total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            # Only print every 25%
                            if percent >= last_percent + 25:
                                last_percent = percent
                                eta = get_eta()
                                safe_print(f"[{filename}] {percent}% (ETA: {eta})")
            
            update_stats(file_completed=True)
            return (file_num, True, f"[{filename}] Done!", False)
            
    except requests.exceptions.RequestException as e:
        if output_path.exists():
            output_path.unlink()  # Remove partial download
        return (file_num, False, f"[{filename}] Error: {e}", False)

def main():
    args = parse_arguments()
    
    # Initialize the shared cookie and auth timer
    set_current_cookie(args.cookie)
    reset_auth_timer()
    
    # Create output directory if it doesn't exist
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Parse the URL to handle incremental downloads
    base_url, batch_num, start_file, extension, query_string = extract_url_parts(args.url)
    
    print(f"Base URL: {base_url}")
    print(f"Batch: {batch_num}, Starting file: {start_file}")
    print(f"Parallel downloads: {args.parallel}")
    print(f"Starting download of up to {args.count} files to {output_dir}")
    print("-" * 60)
    
    # Build list of downloads to perform
    downloads = []
    skipped = 0
    for i in range(start_file, start_file + args.count):
        filename = f"takeout-{batch_num}-{i:03d}{extension}"
        output_path = output_dir / filename
        
        # Skip if file already exists
        if output_path.exists():
            print(f"Skipping {filename} - already exists")
            skipped += 1
            continue
        
        # Construct the URL
        current_url = f"{base_url}{batch_num}-{i:03d}{extension}"
        if query_string:
            current_url += f"?{query_string}"
        
        downloads.append((i, current_url, output_path))
    
    if not downloads:
        print(f"\nAll {skipped} files already exist!")
        return
    
    print(f"\n{skipped} files skipped (already exist), {len(downloads)} files to download")
    print("-" * 60)
    
    # Initialize stats
    with stats_lock:
        download_stats['start_time'] = datetime.now()
        download_stats['total_files'] = len(downloads)
        # Estimate total bytes (assume 2GB per file)
        download_stats['total_bytes'] = len(downloads) * 2 * 1024 * 1024 * 1024
    
    # Download files in parallel with re-auth support
    success_count = skipped
    failed_count = 0
    remaining_downloads = downloads.copy()
    auth_warning_shown = False
    
    while remaining_downloads:
        failed_this_round = []
        auth_failed = False
        
        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            # Submit download tasks
            futures = {
                executor.submit(download_file, url, path, num): (num, url, path)
                for num, url, path in remaining_downloads
            }
            
            try:
                for future in as_completed(futures):
                    file_num, success, message, is_auth_fail = future.result()
                    safe_print(message)
                    
                    if success:
                        success_count += 1
                        
                        # Check if auth might expire soon (every few files)
                        if not auth_warning_shown and check_auth_expiry_warning():
                            auth_warning_shown = True
                            # Don't block, just warn
                            send_notification(
                                "⚠️ Auth May Expire Soon",
                                f"Session active for {AUTH_WARNING_MINUTES}+ mins. Consider refreshing.",
                                urgent=False
                            )
                            safe_print(f"\n⚠️  Auth session active for {AUTH_WARNING_MINUTES}+ minutes - may expire soon")
                    else:
                        if is_auth_fail:
                            auth_failed = True
                            # Cancel remaining futures
                            for f in futures:
                                f.cancel()
                            break
                        else:
                            failed_count += 1
                            # Track failed downloads for potential retry
                            failed_this_round.append(futures[future])
                            
            except KeyboardInterrupt:
                print("\n\nInterrupted! Waiting for current downloads to finish...")
                executor.shutdown(wait=False, cancel_futures=True)
                break
        
        if auth_failed:
            # Prompt for new cookie
            new_cookie = prompt_for_new_cookie()
            if new_cookie == 'QUIT':
                print("\nQuitting...")
                break
            elif new_cookie:
                set_current_cookie(new_cookie)
                reset_auth_timer()
                auth_warning_shown = False
                print("\nCookie updated! Resuming downloads...")
                print("-" * 60)
                # Rebuild remaining downloads (files not yet downloaded)
                remaining_downloads = [
                    (num, url, path) for num, url, path in downloads
                    if not path.exists()
                ]
                continue
            else:
                print("\nQuitting...")
                break
        else:
            # No auth failure, we're done with this round
            break
    
    # Final notification
    if success_count > 0:
        send_notification(
            "✅ Downloads Complete",
            f"{success_count} files downloaded, {failed_count} failed",
            urgent=False
        )
        play_sound('complete')
    
    print("\n" + "=" * 60)
    print(f"Download complete! {success_count} succeeded, {failed_count} failed")
    print(f"Files saved to: {output_dir}")
    
    # Show final stats
    with stats_lock:
        if download_stats['start_time']:
            elapsed = datetime.now() - download_stats['start_time']
            total_gb = download_stats['bytes_downloaded'] / (1024*1024*1024)
            print(f"Total downloaded: {total_gb:.2f} GB in {elapsed}")
    
    print("=" * 60)

if __name__ == "__main__":
    main()

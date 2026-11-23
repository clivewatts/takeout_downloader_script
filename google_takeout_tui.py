#!/usr/bin/env python3
"""
Google Takeout Bulk Downloader - TUI Version
A beautiful terminal user interface for downloading Google Takeout archives.

Usage:
    python google_takeout_tui.py
    # Or via main script (TUI is the default):
    python takeout.py
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional, Dict
from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Header, Footer, Static, Button, Input, Label, 
    Log, DataTable, TextArea
)
from textual.binding import Binding
from textual import work

import requests

from takeout import (
    TakeoutDownloader, DownloadStats,
    get_magic_bytes, get_temp_path, parse_content_length,
    get_range_total, partial_matches_size,
    VERSION, CHUNK_SIZE, DEFAULT_FILE_COUNT, DEFAULT_OUTPUT_DIR, DEFAULT_PARALLEL,
    MAX_PARALLEL, MAX_FILE_COUNT, MIN_ARCHIVE_SIZE
)


@dataclass
class ActiveDownload:
    """Track an active download."""
    filename: str
    downloaded: int = 0
    total: int = 0
    status: str = "Starting"


class TakeoutTUI(App):
    """A Textual app for Google Takeout downloads with parallel support."""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    #main-container {
        height: 100%;
        padding: 1;
    }
    
    #input-section {
        height: auto;
        padding: 1;
        border: solid $primary;
        margin-bottom: 1;
    }
    
    #curl-input {
        height: 6;
        margin-bottom: 1;
    }
    
    #settings-row {
        height: 3;
        margin-bottom: 1;
    }
    
    #settings-row Input {
        width: 1fr;
        margin-right: 1;
    }
    
    #button-row {
        height: 3;
        align: center middle;
    }
    
    #button-row Button {
        margin: 0 1;
    }
    
    #stats-panel {
        height: 3;
        padding: 1;
        background: $surface-darken-1;
        margin-bottom: 1;
    }
    
    #downloads-section {
        height: 12;
        border: solid $secondary;
        margin-bottom: 1;
    }
    
    #downloads-table {
        height: 100%;
    }
    
    #log-section {
        height: 1fr;
        border: solid $accent;
    }
    
    Log {
        height: 100%;
    }
    """
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "start", "Start"),
        Binding("x", "stop", "Stop"),
        Binding("c", "clear_log", "Clear Log"),
    ]
    
    def __init__(self):
        super().__init__()
        self.downloader: Optional[TakeoutDownloader] = None
        self.is_downloading = False
        self.active_downloads: Dict[str, ActiveDownload] = {}
        self.stats = DownloadStats()
        self.bytes_at_last_update = 0
        self.last_update_time = datetime.now()
        self._lock = threading.Lock()
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with Container(id="main-container"):
            # Input section
            with Vertical(id="input-section"):
                yield Label("[bold]Paste cURL command (bash or PowerShell):[/]")
                yield TextArea(id="curl-input")
                
                with Horizontal(id="settings-row"):
                    yield Input(value=DEFAULT_OUTPUT_DIR, placeholder="Output dir", id="output-input")
                    yield Input(value=str(DEFAULT_FILE_COUNT), placeholder="Max files", id="count-input")
                    yield Input(value=str(DEFAULT_PARALLEL), placeholder=f"Parallel 1-{MAX_PARALLEL}", id="parallel-input")
                
                with Horizontal(id="button-row"):
                    yield Button("▶ Start", id="start-btn", variant="success")
                    yield Button("⏹ Stop", id="stop-btn", variant="error", disabled=True)
                    yield Button("🗑 Clear", id="clear-btn", variant="default")
            
            # Stats panel
            yield Static("", id="stats-panel")
            
            # Active downloads table
            with Vertical(id="downloads-section"):
                yield DataTable(id="downloads-table")
            
            # Log section
            with Vertical(id="log-section"):
                yield Log(highlight=True)
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Called when app is mounted."""
        self.title = f"Google Takeout Downloader v{VERSION}"
        self.sub_title = "TUI Mode - Parallel Downloads"
        
        # Setup downloads table
        table = self.query_one("#downloads-table", DataTable)
        table.add_columns("File", "Progress", "Size", "Status")
        
        self.log_message(f"Google Takeout Downloader v{VERSION}")
        self.log_message("Paste a cURL command and click Start")
        self.log_message("Keys: Q=quit, S=start, X=stop, C=clear")
        
        self.update_stats_display()
    
    def log_message(self, message: str, level: str = "info"):
        """Add a message to the log."""
        log = self.query_one(Log)
        timestamp = datetime.now().strftime("%H:%M:%S")
        log.write_line(f"{timestamp} | {message}")
    
    def update_stats_display(self):
        """Update the stats panel."""
        mb = self.stats.bytes_downloaded / (1024 * 1024)
        
        # Calculate speed
        now = datetime.now()
        elapsed = (now - self.last_update_time).total_seconds()
        if elapsed > 0:
            bytes_diff = self.stats.bytes_downloaded - self.bytes_at_last_update
            speed = (bytes_diff / elapsed) / (1024 * 1024)
        else:
            speed = 0
        
        panel = self.query_one("#stats-panel", Static)
        panel.update(
            f"[bold green]✓ Done:[/] {self.stats.completed_files}  "
            f"[bold red]✗ Failed:[/] {self.stats.failed_files}  "
            f"[bold yellow]⊘ Skip:[/] {self.stats.skipped_files}  "
            f"[bold yellow]? Missing:[/] {self.stats.not_found_files}  "
            f"[bold cyan]↓[/] {mb:.1f} MB  "
            f"[bold magenta]⚡[/] {speed:.1f} MB/s  "
            f"[bold]Active:[/] {len(self.active_downloads)}"
        )
        
        self.bytes_at_last_update = self.stats.bytes_downloaded
        self.last_update_time = now
    
    def update_downloads_table(self):
        """Update the active downloads table."""
        table = self.query_one("#downloads-table", DataTable)
        table.clear()
        
        with self._lock:
            for filename, dl in self.active_downloads.items():
                if dl.total > 0:
                    percent = int((dl.downloaded / dl.total) * 100)
                    progress = f"{percent}%"
                    size_str = f"{dl.downloaded/(1024*1024):.1f}/{dl.total/(1024*1024):.1f} MB"
                else:
                    progress = "..."
                    size_str = "..."
                
                table.add_row(filename[-40:], progress, size_str, dl.status)
    
    def action_quit(self) -> None:
        if self.is_downloading and self.downloader:
            self.downloader.stop()
        self.exit()
    
    def action_start(self) -> None:
        self.start_download()
    
    def action_stop(self) -> None:
        self.stop_download()
    
    def action_clear_log(self) -> None:
        self.query_one(Log).clear()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start-btn":
            self.start_download()
        elif event.button.id == "stop-btn":
            self.stop_download()
        elif event.button.id == "clear-btn":
            self.action_clear_log()
    
    def start_download(self) -> None:
        """Start the download process."""
        if self.is_downloading:
            return
        
        # Get inputs
        curl_text = self.query_one("#curl-input", TextArea).text.strip()
        output_dir = self.query_one("#output-input", Input).value.strip() or DEFAULT_OUTPUT_DIR
        
        try:
            file_count = min(max(1, int(self.query_one("#count-input", Input).value.strip() or DEFAULT_FILE_COUNT)), MAX_FILE_COUNT)
        except ValueError:
            file_count = DEFAULT_FILE_COUNT
        
        try:
            parallel = min(max(1, int(self.query_one("#parallel-input", Input).value.strip() or DEFAULT_PARALLEL)), MAX_PARALLEL)
        except ValueError:
            parallel = DEFAULT_PARALLEL
        
        if not curl_text:
            self.log_message("ERROR: Paste a cURL command first!", "error")
            return
        
        # Create downloader
        self.downloader = TakeoutDownloader(output_dir, parallel, log_fn=self._log_from_anywhere)
        
        if not self.downloader.set_curl(curl_text):
            self.log_message("ERROR: Failed to parse cURL!", "error")
            return
        
        self.log_message(f"Starting: {file_count} files, {parallel} parallel")
        self.log_message(f"Output: {output_dir}")
        
        # Reset state
        self.is_downloading = True
        self.stats = DownloadStats(start_time=datetime.now())
        self.active_downloads.clear()
        
        self.query_one("#start-btn", Button).disabled = True
        self.query_one("#stop-btn", Button).disabled = False
        
        # Start download
        self.run_download(file_count, parallel)

    def _log_from_anywhere(self, message: str) -> None:
        """Write a log line from either the UI thread or a worker thread."""
        try:
            if threading.current_thread() is threading.main_thread():
                self.log_message(message)
            else:
                self.call_from_thread(self.log_message, message)
        except RuntimeError:
            # App is shutting down; the message is not worth crashing over.
            pass

    @work(thread=True)
    def run_download(self, file_count: int, parallel: int) -> None:
        """Run downloads in background thread."""
        if not self.downloader:
            return
        
        self.downloader.file_count = file_count
        self.downloader.should_stop = False
        self.downloader.auth_failed = False
        
        # Clean up bad files
        self.call_from_thread(self.log_message, "Checking files...")
        first_needed = self.downloader.cleanup_bad_files()

        # Build download list
        to_download = []
        skipped = 0
        for num in range(first_needed, file_count + 1):
            filepath = self.downloader.get_filepath(num)
            if filepath.exists() and filepath.stat().st_size > 0:
                expected = self.downloader.size_history.get_expected_size(filepath.name)
                if not expected or filepath.stat().st_size >= expected:
                    skipped += 1
                    continue
            to_download.append(num)
        self.stats.skipped_files = skipped

        self.call_from_thread(self.update_stats_display)

        if not to_download:
            self.call_from_thread(self.log_message, "All files downloaded!")
            self.call_from_thread(self.download_complete)
            return

        self.call_from_thread(self.log_message, f"Downloading {len(to_download)} files...")

        # Parallel downloads
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = {executor.submit(self.download_file, num): num for num in to_download}
            
            for future in as_completed(futures):
                if self.downloader.should_stop or self.downloader.auth_failed:
                    for f in futures:
                        f.cancel()
                    break
                
                num = futures[future]
                filename = self.downloader.get_filename(num)

                # Remove from active
                with self._lock:
                    self.active_downloads.pop(filename, None)

                try:
                    success, error = future.result()
                except Exception as e:
                    self.call_from_thread(self.log_message, f"✗ {filename}: {e}")
                    self.stats.failed_files += 1
                    self.call_from_thread(self.update_stats_display)
                    self.call_from_thread(self.update_downloads_table)
                    continue

                if success:
                    self.call_from_thread(self.log_message, f"✓ {filename}")
                    self.stats.completed_files += 1
                elif error == "AUTH_FAILED":
                    self.call_from_thread(self.log_message, f"✗ {filename}: Auth failed!")
                    self.downloader.auth_failed = True
                elif error == "NOT_FOUND":
                    self.call_from_thread(self.log_message, f"⊘ {filename}: Not found")
                    self.stats.not_found_files += 1
                elif error == "STOPPED":
                    pass
                else:
                    self.call_from_thread(self.log_message, f"✗ {filename}: {error}")
                    self.stats.failed_files += 1

                self.call_from_thread(self.update_stats_display)
                self.call_from_thread(self.update_downloads_table)
        
        if self.downloader.auth_failed:
            self.call_from_thread(self.handle_auth_failure)
        else:
            self.call_from_thread(self.download_complete)
    
    def download_file(self, num: int) -> tuple:
        """Download a single file with progress updates and resume support."""
        if not self.downloader:
            return False, "No downloader"
        
        filepath = self.downloader.get_filepath(num)
        url = self.downloader.get_url(num)
        filename = filepath.name
        
        temp_path = get_temp_path(filepath)
        resume_from = 0
        
        # Check for existing partial download to resume
        if temp_path.exists():
            resume_from = temp_path.stat().st_size
        
        # Add to active downloads
        with self._lock:
            status = f"Resuming from {resume_from/(1024*1024):.1f}MB" if resume_from > 0 else "Connecting"
            self.active_downloads[filename] = ActiveDownload(filename=filename, status=status, downloaded=resume_from)
        self.call_from_thread(self.update_downloads_table)
        
        response = None
        try:
            headers = {
                'Cookie': self.downloader.cookie,
                'Accept-Encoding': 'identity',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            
            # Add Range header for resume
            if resume_from > 0:
                headers['Range'] = f'bytes={resume_from}-'
            
            response = requests.get(
                url,
                headers=headers,
                stream=True,
                timeout=(10, 300),
            )
            
            if response.status_code in (401, 403):
                # Keep partial file for resume
                return False, "AUTH_FAILED"
            
            if response.status_code == 404:
                return False, "NOT_FOUND"
            
            if 'accounts.google' in response.url:
                return False, "AUTH_FAILED"
            
            # 416 = Range Not Satisfiable (file might be complete)
            if response.status_code == 416 and resume_from > 0:
                # Verify with HEAD request
                head_resp = requests.head(
                    url,
                    headers={'Cookie': self.downloader.cookie, 'User-Agent': headers['User-Agent'], 'Accept-Encoding': 'identity'},
                    timeout=10,
                )
                try:
                    if head_resp.status_code == 200:
                        expected_size = parse_content_length(head_resp.headers)
                        if partial_matches_size(temp_path, resume_from, expected_size, self.downloader.extension):
                            os.replace(temp_path, filepath)
                            self.downloader.size_history.record_size(filename, resume_from)
                            return True, "resumed-complete"
                finally:
                    head_resp.close()
                response.close()
                temp_path.unlink(missing_ok=True)
                # Retry without resume
                with self._lock:
                    self.active_downloads[filename] = ActiveDownload(filename=filename, status="Restarting")
                return self.download_file(num)
            
            response.raise_for_status()
            
            content_type = response.headers.get('content-type', '')
            if 'text/html' in content_type:
                return False, "AUTH_FAILED"
            
            # Use Content-Range to verify the archive size on partial responses.
            content_length = parse_content_length(response.headers)
            
            if response.status_code == 206:
                total_size = get_range_total(response.headers, resume_from)
            else:
                total_size = content_length
                if resume_from > 0:
                    # Server doesn't support resume, start fresh
                    resume_from = 0
            
            if total_size < MIN_ARCHIVE_SIZE and resume_from == 0:
                return False, "EMPTY_RESPONSE"
            
            # Update active download info
            with self._lock:
                if filename in self.active_downloads:
                    self.active_downloads[filename].total = total_size
                    self.active_downloads[filename].status = "Downloading"
            
            filepath.parent.mkdir(parents=True, exist_ok=True)
            
            # Open file in append mode for resume, write mode for fresh
            file_mode = 'ab' if resume_from > 0 and response.status_code == 206 else 'wb'
            downloaded = resume_from
            last_update = datetime.now()
            
            with open(temp_path, file_mode) as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if self.downloader.should_stop or self.downloader.auth_failed:
                        # Keep partial file for resume on stop
                        return False, "STOPPED"
                    
                    if chunk:
                        if total_size > 0 and downloaded + len(chunk) > total_size:
                            return False, "Response exceeded the expected archive size"
                        # Check first chunk for archive magic bytes (only on fresh downloads)
                        if downloaded == 0:
                            magic = get_magic_bytes(self.downloader.extension)
                            if magic and chunk[:len(magic)] != magic:
                                temp_path.unlink(missing_ok=True)
                                return False, "NOT_ARCHIVE"
                        
                        f.write(chunk)
                        downloaded += len(chunk)
                        with self._lock:
                            self.stats.bytes_downloaded += len(chunk)
                        
                        # Update progress every 300ms
                        now = datetime.now()
                        if (now - last_update).total_seconds() >= 0.3:
                            with self._lock:
                                if filename in self.active_downloads:
                                    self.active_downloads[filename].downloaded = downloaded
                            self.call_from_thread(self.update_downloads_table)
                            self.call_from_thread(self.update_stats_display)
                            last_update = now
            
            if total_size > 0 and downloaded != total_size:
                return False, "Downloaded size does not match the expected archive size"

            os.replace(temp_path, filepath)
            self.downloader.size_history.record_size(filename, downloaded)
            
            return True, ""
            
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return False, "NOT_FOUND"
            # Keep partial file for resume
            return False, str(e)
        except requests.exceptions.RequestException as e:
            # Keep partial file for resume
            return False, str(e)
        except (OSError, ValueError) as e:
            return False, f"Local error: {e}"
        finally:
            if response is not None:
                response.close()
    
    def handle_auth_failure(self):
        """Handle authentication failure."""
        self.log_message("⚠️ AUTH EXPIRED - paste new cURL and click Start")
        self.is_downloading = False
        self.query_one("#start-btn", Button).disabled = False
        self.query_one("#stop-btn", Button).disabled = True
        self.active_downloads.clear()
        self.update_downloads_table()
    
    def download_complete(self):
        """Handle download completion."""
        self.is_downloading = False
        self.query_one("#start-btn", Button).disabled = False
        self.query_one("#stop-btn", Button).disabled = True
        self.active_downloads.clear()
        self.update_downloads_table()
        
        mb = self.stats.bytes_downloaded / (1024 * 1024)
        self.log_message(
            f"Done! ✓{self.stats.completed_files} ✗{self.stats.failed_files} "
            f"⊘{self.stats.skipped_files} | {mb:.1f} MB"
        )
    
    def stop_download(self) -> None:
        """Stop the download process."""
        if self.downloader:
            self.downloader.stop()
            self.log_message("Stopping...")


def main():
    app = TakeoutTUI()
    app.run()


if __name__ == "__main__":
    main()

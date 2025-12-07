#!/usr/bin/env python3
"""
Google Takeout Bulk Downloader - TUI Version
A beautiful terminal user interface for downloading Google Takeout archives.

Usage:
    python google_takeout_tui.py
    # Or via main script:
    python takeout.py --tui
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
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
    TakeoutDownloader, SizeHistory, DownloadStats,
    extract_url_parts, extract_cookie_from_curl, extract_url_from_curl,
    VERSION, CHUNK_SIZE, DEFAULT_FILE_COUNT, DEFAULT_OUTPUT_DIR, DEFAULT_PARALLEL, MAX_PARALLEL
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
                yield Label("[bold]Paste cURL command:[/]")
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
            file_count = int(self.query_one("#count-input", Input).value.strip() or DEFAULT_FILE_COUNT)
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
        self.downloader = TakeoutDownloader(output_dir, parallel)
        
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
    
    @work(thread=True)
    def run_download(self, file_count: int, parallel: int) -> None:
        """Run downloads in background thread."""
        if not self.downloader:
            return
        
        self.downloader.file_count = file_count
        self.downloader.should_stop = False
        self.downloader.auth_failed = False
        
        while not self.downloader.should_stop:
            # Clean up bad files
            self.call_from_thread(self.log_message, "Checking files...")
            first_needed = self.downloader.cleanup_bad_files()
            
            # Build download list
            to_download = []
            for num in range(first_needed, file_count + 1):
                filepath = self.downloader.get_filepath(num)
                if filepath.exists() and filepath.stat().st_size > 0:
                    expected = self.downloader.size_history.get_expected_size(filepath.name)
                    if not expected or filepath.stat().st_size >= expected:
                        self.stats.skipped_files += 1
                        continue
                to_download.append(num)
            
            self.call_from_thread(self.update_stats_display)
            
            if not to_download:
                self.call_from_thread(self.log_message, "All files downloaded!")
                break
            
            self.call_from_thread(self.log_message, f"Downloading {len(to_download)} files...")
            self.downloader.auth_failed = False
            
            # Parallel downloads
            with ThreadPoolExecutor(max_workers=parallel) as executor:
                futures = {executor.submit(self.download_file, num): num for num in to_download}
                
                for future in as_completed(futures):
                    if self.downloader.should_stop or self.downloader.auth_failed:
                        for f in futures:
                            f.cancel()
                        break
                    
                    num = futures[future]
                    try:
                        success, error = future.result()
                        filename = self.downloader.get_filename(num)
                        
                        # Remove from active
                        with self._lock:
                            self.active_downloads.pop(filename, None)
                        
                        if success:
                            self.call_from_thread(self.log_message, f"✓ {filename}")
                            self.stats.completed_files += 1
                        elif error == "AUTH_FAILED":
                            self.call_from_thread(self.log_message, f"✗ {filename}: Auth failed!")
                            self.downloader.auth_failed = True
                        elif error == "NOT_FOUND":
                            self.call_from_thread(self.log_message, f"⊘ {filename}: Not found")
                        else:
                            self.call_from_thread(self.log_message, f"✗ {filename}: {error}")
                            self.stats.failed_files += 1
                        
                        self.call_from_thread(self.update_stats_display)
                        self.call_from_thread(self.update_downloads_table)
                        
                    except Exception as e:
                        self.call_from_thread(self.log_message, f"✗ Error: {e}")
                        self.stats.failed_files += 1
            
            if self.downloader.auth_failed:
                self.call_from_thread(self.handle_auth_failure)
                break
            else:
                break
        
        self.call_from_thread(self.download_complete)
    
    def download_file(self, num: int) -> tuple:
        """Download a single file with progress updates."""
        if not self.downloader:
            return False, "No downloader"
        
        filepath = self.downloader.get_filepath(num)
        url = self.downloader.get_url(num)
        filename = filepath.name
        
        # Add to active downloads
        with self._lock:
            self.active_downloads[filename] = ActiveDownload(filename=filename, status="Connecting")
        self.call_from_thread(self.update_downloads_table)
        
        try:
            response = requests.get(
                url,
                headers={
                    'Cookie': self.downloader.cookie,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                },
                stream=True,
                timeout=(10, 300),
            )
            
            if response.status_code in (401, 403):
                return False, "AUTH_FAILED"
            
            if response.status_code == 404:
                return False, "NOT_FOUND"
            
            if 'accounts.google' in response.url:
                return False, "AUTH_FAILED"
            
            response.raise_for_status()
            
            content_type = response.headers.get('content-type', '')
            if 'text/html' in content_type:
                return False, "AUTH_FAILED"
            
            total_size = int(response.headers.get('content-length', 0))
            if total_size < 1000:
                return False, "AUTH_FAILED"
            
            # Update active download info
            with self._lock:
                if filename in self.active_downloads:
                    self.active_downloads[filename].total = total_size
                    self.active_downloads[filename].status = "Downloading"
            
            filepath.parent.mkdir(parents=True, exist_ok=True)
            temp_path = filepath.with_suffix('.downloading')
            
            downloaded = 0
            last_update = datetime.now()
            
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if self.downloader.should_stop:
                        temp_path.unlink()
                        return False, "Stopped"
                    
                    if chunk:
                        if downloaded == 0 and chunk[:2] != b'PK':
                            temp_path.unlink()
                            return False, "AUTH_FAILED"
                        
                        f.write(chunk)
                        downloaded += len(chunk)
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
            
            temp_path.rename(filepath)
            self.downloader.size_history.record_size(filename, downloaded)
            
            return True, ""
            
        except requests.exceptions.HTTPError as e:
            if e.response and e.response.status_code == 404:
                return False, "NOT_FOUND"
            return False, str(e)
        except requests.exceptions.RequestException as e:
            return False, str(e)
    
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

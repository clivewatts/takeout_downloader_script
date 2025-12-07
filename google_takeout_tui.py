#!/usr/bin/env python3
"""
Google Takeout Bulk Downloader - TUI Version
A beautiful terminal user interface for downloading Google Takeout archives.

Usage:
    python google_takeout_tui.py
    # Or via main script:
    python takeout.py --tui
"""

import asyncio
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Static, Button, Input, Label, 
    ProgressBar, Log, DataTable, Rule
)
from textual.binding import Binding
from textual.message import Message
from textual import work

from takeout import (
    TakeoutDownloader, SizeHistory, DownloadStats,
    extract_url_parts, extract_cookie_from_curl, extract_url_from_curl,
    VERSION, CHUNK_SIZE, DEFAULT_FILE_COUNT, DEFAULT_OUTPUT_DIR, DEFAULT_PARALLEL, MAX_PARALLEL
)

# =============================================================================
# CUSTOM WIDGETS
# =============================================================================

class StatsPanel(Static):
    """Panel showing download statistics."""
    
    def __init__(self):
        super().__init__()
        self.completed = 0
        self.failed = 0
        self.skipped = 0
        self.bytes_downloaded = 0
        self.current_file = ""
        self.speed = 0.0
    
    def compose(self) -> ComposeResult:
        yield Static(id="stats-content")
    
    def update_stats(self, completed: int, failed: int, skipped: int, 
                     bytes_dl: int, current: str = "", speed: float = 0.0):
        self.completed = completed
        self.failed = failed
        self.skipped = skipped
        self.bytes_downloaded = bytes_dl
        self.current_file = current
        self.speed = speed
        self.refresh_display()
    
    def refresh_display(self):
        mb = self.bytes_downloaded / (1024 * 1024)
        content = self.query_one("#stats-content", Static)
        content.update(
            f"[bold green]✓ Completed:[/] {self.completed}  "
            f"[bold red]✗ Failed:[/] {self.failed}  "
            f"[bold yellow]⊘ Skipped:[/] {self.skipped}  "
            f"[bold cyan]↓ Downloaded:[/] {mb:.1f} MB  "
            f"[bold magenta]⚡ Speed:[/] {self.speed:.1f} MB/s"
        )


class FileProgress(Static):
    """Shows progress for current file."""
    
    def __init__(self):
        super().__init__()
        self.current_filename = ""
        self.current_percent = 0
        self.total_size = 0
        self.bytes_downloaded = 0
    
    def compose(self) -> ComposeResult:
        yield Static("", id="file-name")
        yield ProgressBar(total=100, show_eta=False, id="file-progress")
        yield Static("", id="file-size")
    
    def update_progress(self, filename: str, percent: int, downloaded: int, total: int):
        self.current_filename = filename
        self.current_percent = percent
        self.bytes_downloaded = downloaded
        self.total_size = total
        
        name_widget = self.query_one("#file-name", Static)
        progress_widget = self.query_one("#file-progress", ProgressBar)
        size_widget = self.query_one("#file-size", Static)
        
        name_widget.update(f"[bold]{filename}[/]" if filename else "Waiting...")
        progress_widget.update(progress=percent)
        
        if total > 0:
            dl_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            size_widget.update(f"{dl_mb:.1f} / {total_mb:.1f} MB ({percent}%)")
        else:
            size_widget.update("")
    
    def clear(self):
        self.update_progress("", 0, 0, 0)


# =============================================================================
# MAIN TUI APP
# =============================================================================

class TakeoutTUI(App):
    """A Textual app for Google Takeout downloads."""
    
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
    
    #input-section Label {
        margin-bottom: 1;
    }
    
    #curl-input {
        height: 3;
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
    
    #progress-section {
        height: auto;
        min-height: 8;
        padding: 1;
        border: solid $secondary;
        margin-bottom: 1;
    }
    
    StatsPanel {
        height: 3;
        padding: 1;
        background: $surface-darken-1;
        margin-bottom: 1;
    }
    
    FileProgress {
        height: 5;
        padding: 1;
        background: $surface-darken-1;
    }
    
    #log-section {
        height: 1fr;
        border: solid $accent;
    }
    
    Log {
        height: 100%;
    }
    
    .status-ok {
        color: $success;
    }
    
    .status-error {
        color: $error;
    }
    
    .status-warning {
        color: $warning;
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
        self.download_thread: Optional[threading.Thread] = None
        self.bytes_at_last_update = 0
        self.last_update_time = datetime.now()
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with Container(id="main-container"):
            # Input section
            with Vertical(id="input-section"):
                yield Label("[bold]Paste cURL command:[/]")
                yield Input(placeholder="curl 'https://takeout-download...' -H 'Cookie: ...'", id="curl-input")
                
                with Horizontal(id="settings-row"):
                    yield Input(value=DEFAULT_OUTPUT_DIR, placeholder="Output directory", id="output-input")
                    yield Input(value=str(DEFAULT_FILE_COUNT), placeholder="Max files", id="count-input")
                    yield Input(value=str(DEFAULT_PARALLEL), placeholder="Parallel (1-20)", id="parallel-input")
                
                with Horizontal(id="button-row"):
                    yield Button("▶ Start", id="start-btn", variant="success")
                    yield Button("⏹ Stop", id="stop-btn", variant="error", disabled=True)
                    yield Button("🗑 Clear", id="clear-btn", variant="default")
            
            # Progress section
            with Vertical(id="progress-section"):
                yield StatsPanel()
                yield FileProgress()
            
            # Log section
            with Vertical(id="log-section"):
                yield Log(highlight=True, markup=True)
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Called when app is mounted."""
        self.title = f"Google Takeout Downloader v{VERSION}"
        self.sub_title = "TUI Mode"
        self.log_message(f"[bold cyan]Google Takeout Downloader v{VERSION}[/]")
        self.log_message("Paste a cURL command and click Start to begin downloading.")
        self.log_message("Press [bold]Q[/] to quit, [bold]S[/] to start, [bold]X[/] to stop.")
    
    def log_message(self, message: str, level: str = "info"):
        """Add a message to the log."""
        log = self.query_one(Log)
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if level == "error":
            log.write_line(f"[dim]{timestamp}[/] [red]{message}[/]")
        elif level == "warning":
            log.write_line(f"[dim]{timestamp}[/] [yellow]{message}[/]")
        elif level == "success":
            log.write_line(f"[dim]{timestamp}[/] [green]{message}[/]")
        else:
            log.write_line(f"[dim]{timestamp}[/] {message}")
    
    def action_quit(self) -> None:
        """Quit the app."""
        if self.is_downloading and self.downloader:
            self.downloader.stop()
        self.exit()
    
    def action_start(self) -> None:
        """Start download via keyboard."""
        self.start_download()
    
    def action_stop(self) -> None:
        """Stop download via keyboard."""
        self.stop_download()
    
    def action_clear_log(self) -> None:
        """Clear the log."""
        log = self.query_one(Log)
        log.clear()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
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
        curl_input = self.query_one("#curl-input", Input)
        output_input = self.query_one("#output-input", Input)
        count_input = self.query_one("#count-input", Input)
        parallel_input = self.query_one("#parallel-input", Input)
        
        curl_text = curl_input.value.strip()
        output_dir = output_input.value.strip() or DEFAULT_OUTPUT_DIR
        
        try:
            file_count = int(count_input.value.strip() or DEFAULT_FILE_COUNT)
        except ValueError:
            file_count = DEFAULT_FILE_COUNT
        
        try:
            parallel = min(max(1, int(parallel_input.value.strip() or DEFAULT_PARALLEL)), MAX_PARALLEL)
        except ValueError:
            parallel = DEFAULT_PARALLEL
        
        if not curl_text:
            self.log_message("Please paste a cURL command first!", "error")
            return
        
        # Create downloader
        self.downloader = TakeoutDownloader(output_dir, parallel)
        
        # Parse cURL
        if not self.downloader.set_curl(curl_text):
            self.log_message("Failed to parse cURL command!", "error")
            return
        
        self.log_message(f"[bold]Starting download...[/]")
        self.log_message(f"Output: {output_dir}")
        self.log_message(f"Max files: {file_count}, Parallel: {parallel}")
        
        # Update UI
        self.is_downloading = True
        self.query_one("#start-btn", Button).disabled = True
        self.query_one("#stop-btn", Button).disabled = False
        
        # Reset stats
        stats_panel = self.query_one(StatsPanel)
        stats_panel.update_stats(0, 0, 0, 0)
        
        # Start download in background
        self.run_download(file_count)
    
    @work(thread=True)
    def run_download(self, file_count: int) -> None:
        """Run download in background thread."""
        if not self.downloader:
            return
        
        self.downloader.file_count = file_count
        self.downloader.stats = DownloadStats(start_time=datetime.now())
        self.downloader.should_stop = False
        self.downloader.auth_failed = False
        
        while not self.downloader.should_stop:
            # Clean up bad files
            self.call_from_thread(self.log_message, "Checking for incomplete downloads...")
            first_needed = self.downloader.cleanup_bad_files()
            
            # Build list of files to download
            to_download = []
            for num in range(first_needed, file_count + 1):
                filepath = self.downloader.get_filepath(num)
                if filepath.exists() and filepath.stat().st_size > 0:
                    expected = self.downloader.size_history.get_expected_size(filepath.name)
                    if not expected or filepath.stat().st_size >= expected:
                        self.downloader.stats.skipped_files += 1
                        continue
                to_download.append(num)
            
            if not to_download:
                self.call_from_thread(self.log_message, "[bold green]All files downloaded![/]", "success")
                break
            
            self.call_from_thread(
                self.log_message, 
                f"Downloading {len(to_download)} files starting from {to_download[0]}..."
            )
            
            self.downloader.auth_failed = False
            
            # Download files sequentially (simpler for TUI updates)
            for num in to_download:
                if self.downloader.should_stop or self.downloader.auth_failed:
                    break
                
                filepath = self.downloader.get_filepath(num)
                filename = filepath.name
                
                # Update UI with current file
                self.call_from_thread(self.update_current_file, filename, 0, 0, 0)
                
                # Download with progress callback
                success, error = self.download_with_progress(num)
                
                if success:
                    self.call_from_thread(self.log_message, f"✓ {filename}", "success")
                    self.downloader.stats.completed_files += 1
                elif error == "AUTH_FAILED":
                    self.call_from_thread(self.log_message, f"✗ {filename}: Auth failed!", "error")
                    self.downloader.auth_failed = True
                elif error == "NOT_FOUND":
                    self.call_from_thread(self.log_message, f"✗ {filename}: Not found", "warning")
                else:
                    self.call_from_thread(self.log_message, f"✗ {filename}: {error}", "error")
                    self.downloader.stats.failed_files += 1
                
                # Update stats
                self.call_from_thread(self.update_stats_display)
            
            # Handle auth failure
            if self.downloader.auth_failed:
                self.call_from_thread(self.handle_auth_failure)
                # Wait for new cURL (user will click Start again)
                break
            else:
                break
        
        # Done
        self.call_from_thread(self.download_complete)
    
    def download_with_progress(self, num: int) -> tuple:
        """Download a file with progress updates."""
        import requests
        
        if not self.downloader:
            return False, "No downloader"
        
        filepath = self.downloader.get_filepath(num)
        url = self.downloader.get_url(num)
        filename = filepath.name
        
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
            
            # Check for auth failure
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
            
            # Download with progress
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
                        # Check first chunk for ZIP magic
                        if downloaded == 0 and chunk[:2] != b'PK':
                            temp_path.unlink()
                            return False, "AUTH_FAILED"
                        
                        f.write(chunk)
                        downloaded += len(chunk)
                        self.downloader.stats.bytes_downloaded += len(chunk)
                        
                        # Update progress every 200ms
                        now = datetime.now()
                        if (now - last_update).total_seconds() >= 0.2:
                            percent = int((downloaded / total_size) * 100) if total_size > 0 else 0
                            
                            # Calculate speed
                            elapsed = (now - self.last_update_time).total_seconds()
                            if elapsed > 0:
                                bytes_diff = self.downloader.stats.bytes_downloaded - self.bytes_at_last_update
                                speed = (bytes_diff / elapsed) / (1024 * 1024)
                            else:
                                speed = 0
                            
                            self.call_from_thread(
                                self.update_current_file, 
                                filename, percent, downloaded, total_size
                            )
                            self.call_from_thread(self.update_stats_display, speed)
                            
                            self.bytes_at_last_update = self.downloader.stats.bytes_downloaded
                            self.last_update_time = now
                            last_update = now
            
            # Rename to final
            temp_path.rename(filepath)
            self.downloader.size_history.record_size(filename, downloaded)
            
            return True, ""
            
        except requests.exceptions.HTTPError as e:
            if e.response and e.response.status_code == 404:
                return False, "NOT_FOUND"
            return False, str(e)
        except requests.exceptions.RequestException as e:
            return False, str(e)
    
    def update_current_file(self, filename: str, percent: int, downloaded: int, total: int):
        """Update the current file progress display."""
        file_progress = self.query_one(FileProgress)
        file_progress.update_progress(filename, percent, downloaded, total)
    
    def update_stats_display(self, speed: float = 0.0):
        """Update the stats panel."""
        if not self.downloader:
            return
        
        stats = self.downloader.stats
        stats_panel = self.query_one(StatsPanel)
        stats_panel.update_stats(
            stats.completed_files,
            stats.failed_files,
            stats.skipped_files,
            stats.bytes_downloaded,
            speed=speed
        )
    
    def handle_auth_failure(self):
        """Handle authentication failure."""
        self.log_message("[bold red]⚠️ Authentication expired![/]", "error")
        self.log_message("Please paste a new cURL command and click Start to continue.", "warning")
        self.is_downloading = False
        self.query_one("#start-btn", Button).disabled = False
        self.query_one("#stop-btn", Button).disabled = True
        
        # Clear current file progress
        file_progress = self.query_one(FileProgress)
        file_progress.clear()
    
    def download_complete(self):
        """Handle download completion."""
        self.is_downloading = False
        self.query_one("#start-btn", Button).disabled = False
        self.query_one("#stop-btn", Button).disabled = True
        
        # Clear current file progress
        file_progress = self.query_one(FileProgress)
        file_progress.clear()
        
        if self.downloader:
            stats = self.downloader.stats
            mb = stats.bytes_downloaded / (1024 * 1024)
            self.log_message(
                f"[bold]Done![/] Completed: {stats.completed_files}, "
                f"Failed: {stats.failed_files}, Skipped: {stats.skipped_files}, "
                f"Downloaded: {mb:.1f} MB",
                "success"
            )
    
    def stop_download(self) -> None:
        """Stop the download process."""
        if self.downloader:
            self.downloader.stop()
            self.log_message("Stopping download...", "warning")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run the TUI app."""
    app = TakeoutTUI()
    app.run()


if __name__ == "__main__":
    main()

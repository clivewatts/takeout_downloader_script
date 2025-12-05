#!/usr/bin/env python3
"""
Google Takeout Bulk Downloader - GUI Version
A modern, user-friendly interface for downloading Google Takeout archives.
"""

import os
import re
import sys
import threading
import queue
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================================
# STYLING & THEME
# ============================================================================

class ModernStyle:
    """Modern color scheme and styling."""
    # Colors
    BG_DARK = "#1e1e2e"
    BG_MEDIUM = "#2d2d3f"
    BG_LIGHT = "#3d3d5c"
    ACCENT = "#7c3aed"
    ACCENT_HOVER = "#8b5cf6"
    SUCCESS = "#22c55e"
    WARNING = "#f59e0b"
    ERROR = "#ef4444"
    TEXT = "#f8fafc"
    TEXT_DIM = "#94a3b8"
    BORDER = "#4b5563"
    
    # Fonts
    FONT_FAMILY = "Segoe UI"
    FONT_SIZE = 10
    FONT_SIZE_LARGE = 12
    FONT_SIZE_SMALL = 9

# ============================================================================
# DOWNLOAD ENGINE (adapted from CLI version)
# ============================================================================

CHUNK_SIZE = 8 * 1024 * 1024  # 8MB chunks

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
    # Match URL in curl command: curl 'URL' or curl "URL"
    match = re.search(r"curl\s+['\"]?(https?://[^'\"\s]+)['\"]?", curl_text, re.IGNORECASE)
    if match:
        url = match.group(1)
        # Verify it's a takeout URL
        if 'takeout' in url.lower():
            return url
    return None

def extract_from_curl(curl_text: str) -> tuple[str, str]:
    """Extract both cookie and URL from a cURL command.
    Returns (cookie, url) - either may be None if not found.
    """
    cookie = extract_cookie_from_curl(curl_text)
    url = extract_url_from_curl(curl_text)
    return cookie, url

def create_session(cookie: str) -> requests.Session:
    """Create an optimized session for downloads."""
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

# ============================================================================
# MAIN APPLICATION
# ============================================================================

class TakeoutDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Google Takeout Bulk Downloader")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        
        # Set dark theme
        self.root.configure(bg=ModernStyle.BG_DARK)
        
        # Configure ttk styles
        self.setup_styles()
        
        # State variables
        self.is_downloading = False
        self.should_stop = False
        self.current_cookie = tk.StringVar()
        self.current_url = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.home() / "Downloads" / "takeout"))
        self.file_count = tk.IntVar(value=100)
        self.parallel_downloads = tk.IntVar(value=4)
        
        # Statistics
        self.stats = {
            'completed': 0,
            'failed': 0,
            'total': 0,
            'bytes_downloaded': 0,
            'start_time': None
        }
        
        # Message queue for thread-safe UI updates
        self.msg_queue = queue.Queue()
        
        # Load .env if exists
        self.load_env()
        
        # Build UI
        self.create_widgets()
        
        # Start queue processor
        self.process_queue()
    
    def setup_styles(self):
        """Configure ttk styles for modern look."""
        style = ttk.Style()
        
        # Try to use clam theme as base
        try:
            style.theme_use('clam')
        except:
            pass
        
        # Configure styles
        style.configure('TFrame', background=ModernStyle.BG_DARK)
        style.configure('TLabel', 
                       background=ModernStyle.BG_DARK, 
                       foreground=ModernStyle.TEXT,
                       font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE))
        style.configure('Header.TLabel',
                       font=(ModernStyle.FONT_FAMILY, 18, 'bold'),
                       foreground=ModernStyle.TEXT)
        style.configure('Subheader.TLabel',
                       font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE_LARGE),
                       foreground=ModernStyle.TEXT_DIM)
        style.configure('TEntry',
                       fieldbackground=ModernStyle.BG_MEDIUM,
                       foreground=ModernStyle.TEXT,
                       insertcolor=ModernStyle.TEXT)
        style.configure('TButton',
                       background=ModernStyle.ACCENT,
                       foreground=ModernStyle.TEXT,
                       font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE))
        style.map('TButton',
                 background=[('active', ModernStyle.ACCENT_HOVER)])
        style.configure('Success.TButton',
                       background=ModernStyle.SUCCESS)
        style.configure('Danger.TButton',
                       background=ModernStyle.ERROR)
        style.configure('TProgressbar',
                       background=ModernStyle.ACCENT,
                       troughcolor=ModernStyle.BG_MEDIUM)
        style.configure('TSpinbox',
                       fieldbackground=ModernStyle.BG_MEDIUM,
                       foreground=ModernStyle.TEXT)
    
    def create_widgets(self):
        """Create all UI widgets."""
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        self.create_header(main_frame)
        
        # Configuration section
        self.create_config_section(main_frame)
        
        # Progress section
        self.create_progress_section(main_frame)
        
        # Log section
        self.create_log_section(main_frame)
        
        # Control buttons
        self.create_controls(main_frame)
    
    def create_header(self, parent):
        """Create header section."""
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill=tk.X, pady=(0, 20))
        
        # Title
        title = ttk.Label(header_frame, text="📦 Google Takeout Downloader", style='Header.TLabel')
        title.pack(anchor=tk.W)
        
        # Subtitle
        subtitle = ttk.Label(header_frame, 
                            text="Bulk download your Google Takeout archives with ease",
                            style='Subheader.TLabel')
        subtitle.pack(anchor=tk.W)
    
    def create_config_section(self, parent):
        """Create configuration inputs."""
        config_frame = ttk.Frame(parent)
        config_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Cookie input
        cookie_frame = ttk.Frame(config_frame)
        cookie_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(cookie_frame, text="🍪 Cookie / cURL:").pack(anchor=tk.W)
        
        cookie_input_frame = ttk.Frame(cookie_frame)
        cookie_input_frame.pack(fill=tk.X, pady=2)
        
        self.cookie_entry = tk.Text(cookie_input_frame, height=3, wrap=tk.WORD,
                                    bg=ModernStyle.BG_MEDIUM, fg=ModernStyle.TEXT,
                                    insertbackground=ModernStyle.TEXT,
                                    relief=tk.FLAT, padx=8, pady=8,
                                    font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE))
        self.cookie_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Bind to detect when user pastes cURL
        self.cookie_entry.bind('<KeyRelease>', self.on_cookie_change)
        self.cookie_entry.bind('<<Paste>>', lambda e: self.root.after(100, self.on_cookie_change))
        
        # Add scrollbar
        cookie_scroll = ttk.Scrollbar(cookie_input_frame, command=self.cookie_entry.yview)
        cookie_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.cookie_entry.config(yscrollcommand=cookie_scroll.set)
        
        # Paste hint
        self.cookie_hint = ttk.Label(cookie_frame, 
                 text="Paste entire cURL command - URL will be auto-extracted!",
                 foreground=ModernStyle.TEXT_DIM,
                 font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE_SMALL))
        self.cookie_hint.pack(anchor=tk.W)
        
        # URL input
        url_frame = ttk.Frame(config_frame)
        url_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(url_frame, text="🔗 First Download URL (auto-filled from cURL):").pack(anchor=tk.W)
        
        self.url_entry = tk.Entry(url_frame, textvariable=self.current_url,
                                  bg=ModernStyle.BG_MEDIUM, fg=ModernStyle.TEXT,
                                  insertbackground=ModernStyle.TEXT,
                                  relief=tk.FLAT, font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE))
        self.url_entry.pack(fill=tk.X, pady=2, ipady=8)
        
        self.url_hint = ttk.Label(url_frame, text="Or paste URL manually if not using cURL",
                 foreground=ModernStyle.TEXT_DIM,
                 font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE_SMALL))
        self.url_hint.pack(anchor=tk.W)
        
        # Output directory
        dir_frame = ttk.Frame(config_frame)
        dir_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(dir_frame, text="📁 Output Directory:").pack(anchor=tk.W)
        
        dir_input_frame = ttk.Frame(dir_frame)
        dir_input_frame.pack(fill=tk.X, pady=2)
        
        self.dir_entry = tk.Entry(dir_input_frame, textvariable=self.output_dir,
                                  bg=ModernStyle.BG_MEDIUM, fg=ModernStyle.TEXT,
                                  insertbackground=ModernStyle.TEXT,
                                  relief=tk.FLAT, font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE))
        self.dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8)
        
        browse_btn = tk.Button(dir_input_frame, text="Browse...", 
                              command=self.browse_directory,
                              bg=ModernStyle.BG_LIGHT, fg=ModernStyle.TEXT,
                              relief=tk.FLAT, padx=15, pady=8,
                              font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE))
        browse_btn.pack(side=tk.RIGHT, padx=(10, 0))
        
        # Options row
        options_frame = ttk.Frame(config_frame)
        options_frame.pack(fill=tk.X, pady=10)
        
        # File count
        count_frame = ttk.Frame(options_frame)
        count_frame.pack(side=tk.LEFT, padx=(0, 30))
        
        ttk.Label(count_frame, text="📄 Max Files:").pack(side=tk.LEFT)
        count_spin = tk.Spinbox(count_frame, from_=1, to=9999, width=6,
                               textvariable=self.file_count,
                               bg=ModernStyle.BG_MEDIUM, fg=ModernStyle.TEXT,
                               buttonbackground=ModernStyle.BG_LIGHT,
                               relief=tk.FLAT,
                               font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE))
        count_spin.pack(side=tk.LEFT, padx=5)
        
        # Parallel downloads
        parallel_frame = ttk.Frame(options_frame)
        parallel_frame.pack(side=tk.LEFT)
        
        ttk.Label(parallel_frame, text="⚡ Parallel Downloads:").pack(side=tk.LEFT)
        parallel_spin = tk.Spinbox(parallel_frame, from_=1, to=10, width=4,
                                  textvariable=self.parallel_downloads,
                                  bg=ModernStyle.BG_MEDIUM, fg=ModernStyle.TEXT,
                                  buttonbackground=ModernStyle.BG_LIGHT,
                                  relief=tk.FLAT,
                                  font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE))
        parallel_spin.pack(side=tk.LEFT, padx=5)
    
    def create_progress_section(self, parent):
        """Create progress display."""
        progress_frame = ttk.Frame(parent)
        progress_frame.pack(fill=tk.X, pady=10)
        
        # Stats row
        stats_frame = ttk.Frame(progress_frame)
        stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Status label
        self.status_label = ttk.Label(stats_frame, text="Ready to download",
                                      font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE_LARGE))
        self.status_label.pack(side=tk.LEFT)
        
        # Stats on right
        self.stats_label = ttk.Label(stats_frame, text="",
                                     foreground=ModernStyle.TEXT_DIM)
        self.stats_label.pack(side=tk.RIGHT)
        
        # Overall progress bar
        self.overall_progress = ttk.Progressbar(progress_frame, mode='determinate', length=400)
        self.overall_progress.pack(fill=tk.X, pady=5)
        
        # Progress details
        self.progress_detail = ttk.Label(progress_frame, text="0 / 0 files",
                                         foreground=ModernStyle.TEXT_DIM)
        self.progress_detail.pack(anchor=tk.W)
    
    def create_log_section(self, parent):
        """Create log output area."""
        log_frame = ttk.Frame(parent)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        ttk.Label(log_frame, text="📋 Download Log:").pack(anchor=tk.W)
        
        # Log text area
        self.log_text = scrolledtext.ScrolledText(log_frame, height=12,
                                                  bg=ModernStyle.BG_MEDIUM,
                                                  fg=ModernStyle.TEXT,
                                                  insertbackground=ModernStyle.TEXT,
                                                  relief=tk.FLAT,
                                                  font=('Consolas', ModernStyle.FONT_SIZE_SMALL),
                                                  state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Configure tags for colored output
        self.log_text.tag_configure('success', foreground=ModernStyle.SUCCESS)
        self.log_text.tag_configure('error', foreground=ModernStyle.ERROR)
        self.log_text.tag_configure('warning', foreground=ModernStyle.WARNING)
        self.log_text.tag_configure('info', foreground=ModernStyle.TEXT_DIM)
    
    def create_controls(self, parent):
        """Create control buttons."""
        control_frame = ttk.Frame(parent)
        control_frame.pack(fill=tk.X, pady=10)
        
        # Start button
        self.start_btn = tk.Button(control_frame, text="▶  Start Download",
                                   command=self.start_download,
                                   bg=ModernStyle.SUCCESS, fg=ModernStyle.TEXT,
                                   relief=tk.FLAT, padx=30, pady=12,
                                   font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE_LARGE, 'bold'))
        self.start_btn.pack(side=tk.LEFT)
        
        # Stop button
        self.stop_btn = tk.Button(control_frame, text="⏹  Stop",
                                  command=self.stop_download,
                                  bg=ModernStyle.ERROR, fg=ModernStyle.TEXT,
                                  relief=tk.FLAT, padx=30, pady=12,
                                  state=tk.DISABLED,
                                  font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE_LARGE, 'bold'))
        self.stop_btn.pack(side=tk.LEFT, padx=10)
        
        # Clear log button
        clear_btn = tk.Button(control_frame, text="🗑  Clear Log",
                             command=self.clear_log,
                             bg=ModernStyle.BG_LIGHT, fg=ModernStyle.TEXT,
                             relief=tk.FLAT, padx=20, pady=12,
                             font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE))
        clear_btn.pack(side=tk.RIGHT)
    
    def browse_directory(self):
        """Open directory browser."""
        directory = filedialog.askdirectory(initialdir=self.output_dir.get())
        if directory:
            self.output_dir.set(directory)
    
    def on_cookie_change(self, event=None):
        """Called when cookie/cURL text changes - auto-extract URL if present."""
        curl_text = self.cookie_entry.get('1.0', tk.END).strip()
        
        if not curl_text:
            return
        
        # Try to extract URL from cURL command
        url = extract_url_from_curl(curl_text)
        
        if url:
            # Auto-fill the URL field
            self.current_url.set(url)
            # Update hints to show success
            self.cookie_hint.config(text="✓ Cookie extracted from cURL", foreground=ModernStyle.SUCCESS)
            self.url_hint.config(text="✓ URL auto-filled from cURL", foreground=ModernStyle.SUCCESS)
        elif 'curl' in curl_text.lower():
            # It's a cURL but no takeout URL found
            self.cookie_hint.config(text="✓ Cookie found, but no takeout URL in cURL", foreground=ModernStyle.WARNING)
        else:
            # Just a cookie value
            self.cookie_hint.config(text="Cookie value entered", foreground=ModernStyle.TEXT_DIM)
    
    def load_env(self):
        """Load settings from .env file if exists."""
        env_path = Path(__file__).parent / '.env'
        if not env_path.exists():
            return
        
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        
                        if key == 'GOOGLE_COOKIE':
                            self.cookie_entry.insert('1.0', value) if hasattr(self, 'cookie_entry') else None
                        elif key == 'TAKEOUT_URL':
                            self.current_url.set(value)
                        elif key == 'OUTPUT_DIR':
                            self.output_dir.set(value)
                        elif key == 'FILE_COUNT':
                            self.file_count.set(int(value))
                        elif key == 'PARALLEL_DOWNLOADS':
                            self.parallel_downloads.set(int(value))
        except Exception as e:
            pass
    
    def log(self, message: str, tag: str = None):
        """Add message to log (thread-safe)."""
        self.msg_queue.put(('log', message, tag))
    
    def update_status(self, status: str):
        """Update status label (thread-safe)."""
        self.msg_queue.put(('status', status, None))
    
    def update_progress(self, completed: int, total: int, bytes_dl: int = 0):
        """Update progress bar (thread-safe)."""
        self.msg_queue.put(('progress', completed, total, bytes_dl))
    
    def process_queue(self):
        """Process messages from download threads."""
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                
                if msg[0] == 'log':
                    _, message, tag = msg
                    self.log_text.config(state=tk.NORMAL)
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", tag)
                    self.log_text.see(tk.END)
                    self.log_text.config(state=tk.DISABLED)
                
                elif msg[0] == 'status':
                    _, status, _ = msg
                    self.status_label.config(text=status)
                
                elif msg[0] == 'progress':
                    _, completed, total, bytes_dl = msg
                    if total > 0:
                        percent = (completed / total) * 100
                        self.overall_progress['value'] = percent
                        self.progress_detail.config(text=f"{completed} / {total} files")
                        
                        # Calculate speed and ETA
                        if self.stats['start_time'] and bytes_dl > 0:
                            elapsed = (datetime.now() - self.stats['start_time']).total_seconds()
                            if elapsed > 0:
                                speed_mbps = (bytes_dl / elapsed) / (1024 * 1024)
                                self.stats_label.config(text=f"Speed: {speed_mbps:.1f} MB/s")
                
                elif msg[0] == 'done':
                    self.download_complete()
                
                elif msg[0] == 'auth_failed':
                    self.handle_auth_failure()
                    
        except queue.Empty:
            pass
        
        # Schedule next check
        self.root.after(100, self.process_queue)
    
    def clear_log(self):
        """Clear the log text area."""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def validate_inputs(self) -> bool:
        """Validate user inputs before starting."""
        cookie_text = self.cookie_entry.get('1.0', tk.END).strip()
        if not cookie_text:
            messagebox.showerror("Error", "Please enter a cookie or cURL command")
            return False
        
        url = self.current_url.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter the first download URL")
            return False
        
        # Validate URL format
        parts = extract_url_parts(url)
        if parts[0] is None:
            messagebox.showerror("Error", 
                "Invalid URL format.\n\n"
                "Expected format: takeout-TIMESTAMP-N-NNN.zip\n"
                "Example: takeout-20251204T101148Z-3-001.zip")
            return False
        
        output = self.output_dir.get().strip()
        if not output:
            messagebox.showerror("Error", "Please select an output directory")
            return False
        
        return True
    
    def start_download(self):
        """Start the download process."""
        if not self.validate_inputs():
            return
        
        # Extract cookie from input
        cookie_text = self.cookie_entry.get('1.0', tk.END).strip()
        cookie = extract_cookie_from_curl(cookie_text)
        
        if not cookie:
            messagebox.showerror("Error", "Could not extract cookie from input")
            return
        
        # Update UI state
        self.is_downloading = True
        self.should_stop = False
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        
        # Reset stats
        self.stats = {
            'completed': 0,
            'failed': 0,
            'total': 0,
            'bytes_downloaded': 0,
            'start_time': datetime.now()
        }
        
        # Start download thread
        download_thread = threading.Thread(
            target=self.download_worker,
            args=(cookie, self.current_url.get(), self.output_dir.get(),
                  self.file_count.get(), self.parallel_downloads.get()),
            daemon=True
        )
        download_thread.start()
    
    def stop_download(self):
        """Stop the download process."""
        self.should_stop = True
        self.update_status("⏹ Stopping...")
        self.log("Stop requested - waiting for current downloads to finish...", 'warning')
    
    def download_worker(self, cookie: str, url: str, output_dir: str, 
                       file_count: int, parallel: int):
        """Worker thread for downloads."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        self.update_status("🔄 Preparing downloads...")
        self.log("Starting download process...", 'info')
        
        # Parse URL
        base_url, batch_num, start_file, extension, query_string = extract_url_parts(url)
        
        self.log(f"Batch: {batch_num}, Starting file: {start_file}", 'info')
        self.log(f"Output directory: {output_dir}", 'info')
        
        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Build download list
        downloads = []
        skipped = 0
        
        for i in range(start_file, start_file + file_count):
            if self.should_stop:
                break
                
            filename = f"takeout-{batch_num}-{i:03d}{extension}"
            file_path = output_path / filename
            
            if file_path.exists():
                self.log(f"Skipping {filename} - already exists", 'info')
                skipped += 1
                continue
            
            current_url = f"{base_url}{batch_num}-{i:03d}{extension}"
            if query_string:
                current_url += f"?{query_string}"
            
            downloads.append((i, current_url, file_path, filename))
        
        if not downloads:
            self.log(f"All {skipped} files already exist!", 'success')
            self.msg_queue.put(('done', None, None))
            return
        
        self.stats['total'] = len(downloads)
        self.log(f"{skipped} files skipped, {len(downloads)} files to download", 'info')
        self.update_status(f"📥 Downloading {len(downloads)} files...")
        self.update_progress(0, len(downloads))
        
        # Download with thread pool
        completed = 0
        failed = 0
        
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = {
                executor.submit(self.download_file, cookie, url, path, name): (num, name)
                for num, url, path, name in downloads
            }
            
            for future in as_completed(futures):
                if self.should_stop:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                
                num, name = futures[future]
                try:
                    success, message, is_auth_fail = future.result()
                    
                    if success:
                        completed += 1
                        self.log(f"✓ {name} - Done!", 'success')
                    else:
                        if is_auth_fail:
                            self.log(f"✗ {name} - Auth failed!", 'error')
                            self.msg_queue.put(('auth_failed', None, None))
                            executor.shutdown(wait=False, cancel_futures=True)
                            return
                        else:
                            failed += 1
                            self.log(f"✗ {name} - {message}", 'error')
                    
                    self.update_progress(completed + failed, len(downloads), 
                                        self.stats['bytes_downloaded'])
                    
                except Exception as e:
                    failed += 1
                    self.log(f"✗ {name} - Error: {e}", 'error')
        
        self.stats['completed'] = completed
        self.stats['failed'] = failed
        self.msg_queue.put(('done', None, None))
    
    def download_file(self, cookie: str, url: str, output_path: Path, 
                     filename: str) -> tuple[bool, str, bool]:
        """Download a single file."""
        session = create_session(cookie)
        
        try:
            with session.get(url, stream=True, allow_redirects=True, timeout=(10, 300)) as r:
                r.raise_for_status()
                
                content_type = r.headers.get('content-type', '')
                if 'text/html' in content_type:
                    preview = r.content[:500].decode('utf-8', errors='ignore')
                    if 'signin' in preview.lower() or 'login' in preview.lower():
                        return (False, "Auth failed", True)
                    return (False, "Got HTML instead of ZIP", False)
                
                total_size = int(r.headers.get('content-length', 0))
                
                if total_size < 1000000:
                    return (False, f"File too small ({total_size} bytes)", False)
                
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                size_mb = total_size / (1024*1024)
                self.log(f"↓ {filename} ({size_mb:.0f} MB)", 'info')
                
                # Track per-file download speed
                file_start_time = time.time()
                file_downloaded = 0
                last_speed_update = time.time()
                
                with open(output_path, 'wb', buffering=CHUNK_SIZE) as f:
                    for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                        if self.should_stop:
                            return (False, "Stopped by user", False)
                        if chunk:
                            f.write(chunk)
                            chunk_len = len(chunk)
                            file_downloaded += chunk_len
                            self.stats['bytes_downloaded'] += chunk_len
                            
                            # Update speed every 2 seconds
                            now = time.time()
                            if now - last_speed_update >= 2:
                                elapsed = now - file_start_time
                                if elapsed > 0:
                                    speed_mbps = (file_downloaded / elapsed) / (1024 * 1024)
                                    percent = int((file_downloaded / total_size) * 100) if total_size > 0 else 0
                                    self.log(f"  {filename}: {percent}% @ {speed_mbps:.1f} MB/s", 'info')
                                last_speed_update = now
                
                return (True, "Success", False)
                
        except requests.exceptions.RequestException as e:
            if output_path.exists():
                output_path.unlink()
            return (False, str(e), False)
    
    def download_complete(self):
        """Handle download completion."""
        self.is_downloading = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        
        completed = self.stats['completed']
        failed = self.stats['failed']
        total_mb = self.stats['bytes_downloaded'] / (1024 * 1024)
        
        if self.should_stop:
            self.update_status("⏹ Stopped")
            self.log(f"Download stopped. {completed} completed, {failed} failed", 'warning')
        else:
            self.update_status("✅ Complete!")
            self.log(f"Download complete! {completed} succeeded, {failed} failed", 'success')
            self.log(f"Total downloaded: {total_mb:.1f} MB", 'info')
            
            # Show notification
            self.send_notification("Downloads Complete", 
                                  f"{completed} files downloaded successfully")
    
    def handle_auth_failure(self):
        """Handle authentication failure."""
        self.is_downloading = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.update_status("🔐 Auth Expired")
        
        # Show dialog
        result = messagebox.askretrycancel(
            "Authentication Expired",
            "Your Google session has expired.\n\n"
            "Please get a new cookie from your browser:\n"
            "1. Open DevTools (F12) on Google Takeout\n"
            "2. Go to Network tab\n"
            "3. Click a download link\n"
            "4. Copy as cURL and paste above\n\n"
            "Click Retry after updating the cookie."
        )
        
        if result:
            self.log("Please paste new cookie and click Start", 'warning')
    
    def send_notification(self, title: str, message: str):
        """Send desktop notification."""
        try:
            subprocess.run(
                ['notify-send', '-a', 'Takeout Downloader', title, message],
                capture_output=True,
                timeout=5
            )
        except:
            pass

# ============================================================================
# MAIN
# ============================================================================

def main():
    root = tk.Tk()
    
    # Set icon if available
    try:
        # You could add an icon here
        pass
    except:
        pass
    
    app = TakeoutDownloaderGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()

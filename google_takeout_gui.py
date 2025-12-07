#!/usr/bin/env python3
"""
Google Takeout Bulk Downloader - GUI Version
A modern, user-friendly interface for downloading Google Takeout archives.

This module can be run standalone or launched via: python takeout.py --gui
"""

import os
import sys
import threading
import queue
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import requests

# Import shared core
from takeout import (
    TakeoutDownloader, SizeHistory, DownloadStats,
    extract_url_parts, extract_cookie_from_curl, extract_url_from_curl,
    VERSION, CHUNK_SIZE
)

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
    BLUE = "#3b82f6"
    
    # Fonts
    FONT_FAMILY = "Segoe UI"
    FONT_SIZE = 10
    FONT_SIZE_LARGE = 12
    FONT_SIZE_SMALL = 9

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def extract_from_curl(curl_text: str) -> tuple:
    """Extract both cookie and URL from a cURL command."""
    cookie = extract_cookie_from_curl(curl_text)
    url = extract_url_from_curl(curl_text)
    return cookie, url

# ============================================================================
# MAIN APPLICATION
# ============================================================================

class TakeoutDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Google Takeout Bulk Downloader")
        
        # Get screen dimensions and set appropriate window size
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        
        # Use 80% of screen or minimum 950x850
        width = max(950, int(screen_width * 0.6))
        height = max(850, int(screen_height * 0.8))
        
        # Center the window
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(950, 850)
        
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
        
        # Active downloads tracking {filename: {progress_bar, label, speed_label, ...}}
        self.active_downloads: Dict[str, dict] = {}
        self.active_downloads_lock = threading.Lock()
        
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
        """Create progress display with active downloads panel."""
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
        
        # Active Downloads Section
        active_frame = ttk.Frame(parent)
        active_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 5))
        
        ttk.Label(active_frame, text="⬇️ Active Downloads:", 
                 font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE_LARGE)).pack(anchor=tk.W)
        
        # Scrollable container for active downloads
        self.downloads_canvas = tk.Canvas(active_frame, bg=ModernStyle.BG_MEDIUM, 
                                          highlightthickness=0, height=180)
        downloads_scrollbar = ttk.Scrollbar(active_frame, orient="vertical", 
                                            command=self.downloads_canvas.yview)
        self.downloads_container = ttk.Frame(self.downloads_canvas)
        
        self.downloads_canvas.configure(yscrollcommand=downloads_scrollbar.set)
        
        downloads_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.downloads_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=5)
        
        self.canvas_window = self.downloads_canvas.create_window((0, 0), window=self.downloads_container, anchor="nw")
        
        # Configure canvas scrolling
        self.downloads_container.bind("<Configure>", self._on_downloads_configure)
        self.downloads_canvas.bind("<Configure>", self._on_canvas_configure)
    
    def _on_downloads_configure(self, event):
        """Update scroll region when downloads container changes."""
        self.downloads_canvas.configure(scrollregion=self.downloads_canvas.bbox("all"))
    
    def _on_canvas_configure(self, event):
        """Update container width when canvas resizes."""
        self.downloads_canvas.itemconfig(self.canvas_window, width=event.width)
    
    def create_download_widget(self, filename: str, total_size: int):
        """Create a download progress widget for a file."""
        frame = tk.Frame(self.downloads_container, bg=ModernStyle.BG_LIGHT, padx=10, pady=8)
        frame.pack(fill=tk.X, pady=2, padx=2)
        
        # Top row: filename and size
        top_row = tk.Frame(frame, bg=ModernStyle.BG_LIGHT)
        top_row.pack(fill=tk.X)
        
        name_label = tk.Label(top_row, text=f"📄 {filename}", 
                             bg=ModernStyle.BG_LIGHT, fg=ModernStyle.TEXT,
                             font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE, 'bold'))
        name_label.pack(side=tk.LEFT)
        
        size_mb = total_size / (1024 * 1024)
        size_label = tk.Label(top_row, text=f"{size_mb:.0f} MB",
                             bg=ModernStyle.BG_LIGHT, fg=ModernStyle.TEXT_DIM,
                             font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE_SMALL))
        size_label.pack(side=tk.RIGHT)
        
        # Progress bar
        progress_var = tk.DoubleVar(value=0)
        progress_bar = ttk.Progressbar(frame, variable=progress_var, maximum=100, length=300)
        progress_bar.pack(fill=tk.X, pady=(5, 3))
        
        # Bottom row: percent and speed
        bottom_row = tk.Frame(frame, bg=ModernStyle.BG_LIGHT)
        bottom_row.pack(fill=tk.X)
        
        percent_label = tk.Label(bottom_row, text="0%",
                                bg=ModernStyle.BG_LIGHT, fg=ModernStyle.ACCENT,
                                font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE))
        percent_label.pack(side=tk.LEFT)
        
        speed_label = tk.Label(bottom_row, text="Starting...",
                              bg=ModernStyle.BG_LIGHT, fg=ModernStyle.SUCCESS,
                              font=(ModernStyle.FONT_FAMILY, ModernStyle.FONT_SIZE, 'bold'))
        speed_label.pack(side=tk.RIGHT)
        
        return {
            'frame': frame,
            'progress_var': progress_var,
            'percent_label': percent_label,
            'speed_label': speed_label,
            'total_size': total_size,
            'start_time': time.time(),
            'bytes_downloaded': 0
        }
    
    def update_download_widget(self, filename: str, downloaded: int, speed_mbps: float):
        """Update a download progress widget."""
        with self.active_downloads_lock:
            if filename not in self.active_downloads:
                return
            widget = self.active_downloads[filename]
        
        total = widget['total_size']
        percent = (downloaded / total * 100) if total > 0 else 0
        
        # Queue UI update
        self.msg_queue.put(('download_progress', filename, percent, speed_mbps))
    
    def remove_download_widget(self, filename: str, success: bool):
        """Remove a download widget when complete."""
        self.msg_queue.put(('download_complete', filename, success))
    
    def create_log_section(self, parent):
        """Create log output area."""
        log_frame = ttk.Frame(parent)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        ttk.Label(log_frame, text="📋 Event Log:").pack(anchor=tk.W)
        
        # Log text area
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8,
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
                        
                        # Calculate overall speed
                        if self.stats['start_time'] and bytes_dl > 0:
                            elapsed = (datetime.now() - self.stats['start_time']).total_seconds()
                            if elapsed > 0:
                                speed_mbps = (bytes_dl / elapsed) / (1024 * 1024)
                                total_gb = bytes_dl / (1024 * 1024 * 1024)
                                self.stats_label.config(text=f"Total: {total_gb:.2f} GB @ {speed_mbps:.1f} MB/s avg")
                
                elif msg[0] == 'download_start':
                    _, filename, total_size = msg
                    widget = self.create_download_widget(filename, total_size)
                    with self.active_downloads_lock:
                        self.active_downloads[filename] = widget
                
                elif msg[0] == 'download_progress':
                    _, filename, percent, speed_mbps = msg
                    with self.active_downloads_lock:
                        if filename in self.active_downloads:
                            widget = self.active_downloads[filename]
                            widget['progress_var'].set(percent)
                            widget['percent_label'].config(text=f"{percent:.0f}%")
                            widget['speed_label'].config(text=f"{speed_mbps:.1f} MB/s")
                
                elif msg[0] == 'download_complete':
                    _, filename, success = msg
                    with self.active_downloads_lock:
                        if filename in self.active_downloads:
                            widget = self.active_downloads[filename]
                            widget['frame'].destroy()
                            del self.active_downloads[filename]
                
                elif msg[0] == 'done':
                    self.download_complete()
                
                elif msg[0] == 'auth_failed':
                    self.handle_auth_failure()
                    
        except queue.Empty:
            pass
        
        # Schedule next check
        self.root.after(50, self.process_queue)
    
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
        """Worker thread for downloads - sequential with auth retry."""
        self.update_status("🔄 Preparing downloads...")
        self.log("Starting download process...", 'info')
        
        # Parse URL
        base_url, file_num, extension, query_string = extract_url_parts(url)
        
        if base_url is None:
            self.log("Invalid URL format", 'error')
            self.msg_queue.put(('done', None, None))
            return
        
        self.log(f"URL pattern: {base_url}XXX{extension}", 'info')
        self.log(f"Output directory: {output_dir}", 'info')
        
        # Create output directory and size history
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        size_history = SizeHistory(output_dir)
        
        self.stats['total'] = file_count
        current_file = 1
        consecutive_404 = 0
        
        while current_file <= file_count and not self.should_stop:
            # Build filename and URL
            filename = f"{base_url.split('/')[-1]}{current_file:03d}{extension}"
            filepath = output_path / filename
            file_url = f"{base_url}{current_file:03d}{extension}"
            if query_string:
                file_url += f"?{query_string}"
            
            # Skip existing files
            if filepath.exists() and filepath.stat().st_size > 0:
                expected = size_history.get_expected_size(filename)
                if not expected or filepath.stat().st_size >= expected:
                    self.log(f"✓ {filename} (exists)", 'info')
                    self.stats['completed'] += 1
                    current_file += 1
                    consecutive_404 = 0
                    self.update_progress(self.stats['completed'], file_count, self.stats['bytes_downloaded'])
                    continue
            
            # Download
            self.update_status(f"📥 Downloading {filename}...")
            success, message, is_auth_fail = self.download_file(cookie, file_url, filepath, filename, size_history)
            
            if success:
                self.log(f"✓ {filename}", 'success')
                self.stats['completed'] += 1
                current_file += 1
                consecutive_404 = 0
                
            elif is_auth_fail:
                self.log(f"✗ {filename}: {message}", 'error')
                self.msg_queue.put(('auth_failed', None, None))
                return
                
            elif '404' in message or 'not found' in message.lower():
                consecutive_404 += 1
                self.log(f"✗ {filename}: not found", 'warning')
                if consecutive_404 >= 3:
                    self.log('3 consecutive 404s - assuming done', 'info')
                    break
                current_file += 1
                
            else:
                self.log(f"✗ {filename}: {message}", 'error')
                self.stats['failed'] += 1
                current_file += 1
                consecutive_404 = 0
            
            self.update_progress(self.stats['completed'] + self.stats['failed'], file_count, self.stats['bytes_downloaded'])
        
        self.msg_queue.put(('done', None, None))
    
    def download_file(self, cookie: str, url: str, output_path: Path, 
                     filename: str, size_history: SizeHistory) -> tuple:
        """Download a single file."""
        try:
            response = requests.get(
                url,
                headers={
                    'Cookie': cookie,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                },
                stream=True,
                timeout=(10, 300),
            )
            
            # Check for auth failure
            if response.status_code in (401, 403):
                return (False, "Auth failed", True)
            
            if 'accounts.google' in response.url:
                return (False, "Auth failed - redirected", True)
            
            response.raise_for_status()
            
            content_type = response.headers.get('content-type', '')
            if 'text/html' in content_type:
                return (False, "Auth failed - got HTML", True)
            
            total_size = int(response.headers.get('content-length', 0))
            if total_size < 1000:
                return (False, "Auth failed - file too small", True)
            
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Create download widget in UI
            self.msg_queue.put(('download_start', filename, total_size))
            
            temp_path = output_path.with_suffix('.downloading')
            downloaded = 0
            last_update_time = time.time()
            last_update_bytes = 0
            
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if self.should_stop:
                        self.msg_queue.put(('download_complete', filename, False))
                        temp_path.unlink()
                        return (False, "Stopped", False)
                    
                    if chunk:
                        # Check first chunk for ZIP magic
                        if downloaded == 0 and chunk[:2] != b'PK':
                            self.msg_queue.put(('download_complete', filename, False))
                            temp_path.unlink()
                            return (False, "Auth failed - not a ZIP", True)
                        
                        f.write(chunk)
                        downloaded += len(chunk)
                        self.stats['bytes_downloaded'] += len(chunk)
                        
                        # Update UI every 500ms
                        now = time.time()
                        elapsed = now - last_update_time
                        
                        if elapsed >= 0.5:
                            bytes_since_last = downloaded - last_update_bytes
                            speed_mbps = (bytes_since_last / elapsed) / (1024 * 1024) if elapsed > 0 else 0
                            percent = (downloaded / total_size * 100) if total_size > 0 else 0
                            self.msg_queue.put(('download_progress', filename, percent, speed_mbps))
                            last_update_time = now
                            last_update_bytes = downloaded
            
            # Rename to final
            temp_path.rename(output_path)
            size_history.record_size(filename, downloaded)
            
            self.msg_queue.put(('download_complete', filename, True))
            return (True, "Success", False)
            
        except requests.exceptions.HTTPError as e:
            self.msg_queue.put(('download_complete', filename, False))
            if e.response and e.response.status_code == 404:
                return (False, "404 not found", False)
            return (False, f"HTTP error: {e}", False)
        except requests.exceptions.RequestException as e:
            self.msg_queue.put(('download_complete', filename, False))
            return (False, f"Network error: {e}", False)
    
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
        import subprocess
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

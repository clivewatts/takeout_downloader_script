# Google Takeout Bulk Downloader

A simple, robust tool to bulk download Google Takeout archives. Available as **TUI** (Terminal UI) and **Web interface**.

![Version](https://img.shields.io/badge/Version-4.0.0-blue) ![TUI](https://img.shields.io/badge/TUI-Default-green) ![Web](https://img.shields.io/badge/Web-Available-blue) ![Docker](https://img.shields.io/badge/Docker-Ready-2496ED) ![Python](https://img.shields.io/badge/Python-3.8+-blue) ![Platform](https://img.shields.io/badge/Platform-Linux%20|%20Windows%20|%20macOS-orange)

## Features

- **Parallel Downloads** - Configurable 1-20 concurrent downloads
- **Auto-Retry** - On auth failure, prompts for new cURL and resumes
- **Resume Support** - Tracks file sizes to detect incomplete downloads
- **Simple** - Just paste your cURL command and go

## Quick Start

### TUI Mode (Default)

```bash
# Install dependencies
pip install textual rich requests

# Run TUI
python takeout.py
```

### Web Mode

```bash
# Install dependencies  
pip install flask flask-socketio requests

# Run web interface
python takeout.py --web
```

### Docker (Web Interface)

```bash
docker-compose up -d
# Open http://localhost:5000
```

## Installation

```bash
git clone https://github.com/clivewatts/takeout_downloader_script.git
cd takeout_downloader_script

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or: .venv\Scripts\activate  # Windows

# Install all dependencies
pip install -r requirements.txt
```

## Usage

### Getting Your cURL Command

1. Go to [Google Takeout](https://takeout.google.com) → **Manage exports**
2. Open DevTools (`F12`) → **Network** tab
3. Click **Download** on any file
4. Right-click the request → **Copy** → **Copy as cURL**
5. Paste into the app

### TUI Mode

```bash
python takeout.py
```

- Paste your cURL command in the text area
- Set output directory, max files, and parallel count
- Click **Start**
- Watch progress in the table and log

**Keyboard shortcuts:** `Q` quit, `S` start, `X` stop, `C` clear log

### Web Mode

```bash
python takeout.py --web
python takeout.py --web --port 8080  # Custom port
```

Open `http://localhost:5000` in your browser.

### Command-Line Options

```
python takeout.py [OPTIONS]

Options:
  --web           Start web interface instead of TUI
  --port PORT     Web server port (default: 5000)
  --host HOST     Web server host (default: 0.0.0.0)
  -v, --version   Show version
```

## Docker

### Using Docker Compose (Recommended)

```bash
docker-compose up -d
```

Open `http://localhost:5000`

### Manual Docker

```bash
docker build -t takeout-downloader .
docker run -d -p 5000:5000 -v $(pwd)/downloads:/downloads takeout-downloader
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OUTPUT_DIR` | Download directory | `/downloads` |
| `PARALLEL_DOWNLOADS` | Concurrent downloads | `6` |
| `FILE_COUNT` | Max files to download | `100` |

## Building Standalone Binary

Build a single executable that includes both TUI and Web modes:

```bash
pip install pyinstaller
python build.py
```

Output: `dist/takeout` (Linux/macOS) or `dist/takeout.exe` (Windows)

```bash
./takeout              # TUI mode
./takeout --web        # Web mode
```

## How It Works

1. **Paste cURL** - Cookie and URL are extracted automatically
2. **Download** - Files are downloaded with progress tracking
3. **Auth Failure** - If auth expires, prompts for new cURL and resumes
4. **Track Sizes** - Records file sizes to detect incomplete downloads
5. **Resume** - On restart, skips completed files and resumes incomplete ones

## Re-authentication

Google sessions expire after ~1 hour. When this happens:

1. Downloads pause automatically
2. You're prompted for a new cURL command
3. Get a fresh cURL from your browser (same steps as initial setup)
4. Paste it and downloads resume from where they left off

## Tips

- **Parallel Downloads**: Start with 3-6. Too many may trigger rate limiting.
- **Network Shares**: Mount with your user permissions for write access
- **Large Exports**: Google splits exports into 2GB files. 100+ files is common.

## Files

```
takeout.py           # Main entry point
google_takeout_tui.py   # TUI interface (textual)
google_takeout_web.py   # Web interface (Flask)
requirements.txt     # Python dependencies
Dockerfile          # Docker image
docker-compose.yml  # Docker Compose config
build.py            # Build script for standalone binary
```

## License

MIT License

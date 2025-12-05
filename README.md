# Google Takeout Bulk Downloader

A Python tool to bulk download Google Takeout archives using browser cookies for authentication. Available as both a **GUI application** and **command-line script**.

![GUI Screenshot](https://img.shields.io/badge/GUI-Available-brightgreen) ![Python](https://img.shields.io/badge/Python-3.8+-blue) ![Platform](https://img.shields.io/badge/Platform-Linux%20|%20Windows%20|%20macOS-orange)

## Quick Start - Download Pre-built Binaries

Download the latest release for your platform (no Python required):

| Platform | Download |
|----------|----------|
| **Linux** | [Google_Takeout_Downloader-linux-x64](https://github.com/clivewatts/takeout_downloader_script/releases/latest) |
| **Windows** | [Google_Takeout_Downloader-windows-x64.exe](https://github.com/clivewatts/takeout_downloader_script/releases/latest) |
| **macOS** | [Google_Takeout_Downloader-macos-x64.app](https://github.com/clivewatts/takeout_downloader_script/releases/latest) |

Just download, run, and paste your cookie!

## Features

- **🖥️ Modern GUI** - User-friendly graphical interface with dark theme
- **📦 Bulk Downloads** - Automatically downloads all numbered Takeout files
- **⚡ Parallel Downloads** - Configurable concurrent downloads (default: 4-6)
- **🔄 Resume Support** - Skips already downloaded files
- **🔐 Interactive Re-authentication** - Prompts for new cookies when session expires
- **📋 cURL Paste Support** - Just paste the entire cURL command, cookie is extracted automatically
- **📊 Progress Tracking** - Real-time progress with ETA and download speed
- **🔔 Desktop Notifications** - Get notified when auth expires or downloads complete
- **🔊 Sound Alerts** - Audio alerts for auth expiry and completion (CLI)
- **⚠️ Auth Expiry Warning** - Warns before session expires (~45 min)

## Installation

```bash
# Clone the repository
git clone https://github.com/clivewatts/takeout_downloader_script.git
cd takeout_downloader_script

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install requests
```

## Configuration

Copy the example environment file and configure:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# Full cookie header from browser
GOOGLE_COOKIE="your_cookie_here"

# First download URL from Google Takeout
TAKEOUT_URL="https://takeout-download.usercontent.google.com/download/takeout-YYYYMMDDTHHMMSSZ-N-001.zip?..."

# Output directory
OUTPUT_DIR="/path/to/downloads"

# Number of files to download
FILE_COUNT=100

# Parallel downloads (optional, default: 6)
PARALLEL_DOWNLOADS=6
```

## Getting the Initial Download URL

### What is this and why do we need it?

When you create a Google Takeout export, Google splits your data into multiple 2GB ZIP files. A large account might have **hundreds of files** like:

```
takeout-20251204T101148Z-3-001.zip
takeout-20251204T101148Z-3-002.zip
takeout-20251204T101148Z-3-003.zip
...
takeout-20251204T101148Z-3-730.zip
```

Google doesn't provide a "download all" button - you'd have to click each file individually. This script solves that by **extrapolating all the download URLs from just the first one**.

### How URL Extrapolation Works

You provide the URL for file `001`, and the script automatically generates URLs for `002`, `003`, etc. by incrementing the file number:

```
# You provide this (file 001):
https://takeout-download.usercontent.google.com/download/takeout-20251204T101148Z-3-001.zip?j=abc123&i=0&user=12345

# Script automatically generates:
https://takeout-download.usercontent.google.com/download/takeout-20251204T101148Z-3-002.zip?j=abc123&i=0&user=12345
https://takeout-download.usercontent.google.com/download/takeout-20251204T101148Z-3-003.zip?j=abc123&i=0&user=12345
... and so on
```

The query parameters (`j=`, `i=`, `user=`) stay the same - only the file number changes.

### How to Get the First URL

#### Method 1: Right-Click the Download Button (Easiest)

**Chrome / Edge:**
1. Go to [Google Takeout](https://takeout.google.com) → click **Manage exports**
2. Find your export - you'll see a list of files (1 of 730, 2 of 730, etc.)
3. **Right-click** the "Download" button for **file 1**
4. Click **Copy link address**
5. Paste into your `.env` as `TAKEOUT_URL`

**Firefox:**
1. Go to [Google Takeout](https://takeout.google.com) → click **Manage exports**
2. Find your export - you'll see a list of files
3. **Right-click** the "Download" button for **file 1**
4. Click **Copy Link**
5. Paste into your `.env` as `TAKEOUT_URL`

#### Method 2: From Network Tab (If Method 1 doesn't work)

**Chrome / Edge:**
1. Open DevTools (`F12`) → **Network** tab
2. Click the Download button for file 1
3. Look for a request containing `takeout-` in the Name column
4. Right-click it → **Copy** → **Copy URL**

**Firefox:**
1. Open DevTools (`F12`) → **Network** tab
2. Click the Download button for file 1
3. Look for a request containing `takeout-`
4. Right-click it → **Copy Value** → **Copy URL**

### Example URL

Your URL will look something like this:

```
https://takeout-download.usercontent.google.com/download/takeout-20251204T101148Z-3-001.zip?j=ceabdffe-95b3-40e5-8790-2119226fe093&i=0&user=987312302921&authuser=0
```

Breaking it down:
- `takeout-20251204T101148Z` - Timestamp of your export
- `3` - Batch number (if you've done multiple exports)
- `001` - **File number** (this is what gets incremented)
- `?j=...&i=...&user=...` - Authentication parameters (kept for all files)

## Getting Your Cookie

The cookie authenticates your requests. Google sessions typically expire after ~1 hour.

### Chrome / Chromium / Edge

1. Go to the Google Takeout download page
2. Open DevTools (`F12`) → **Network** tab
3. Click any download link
4. Find the request in the Network tab
5. Right-click → **Copy** → **Copy as cURL (bash)**
6. Paste the entire cURL command when prompted, or extract the `Cookie:` header for `.env`

### Firefox

1. Go to the Google Takeout download page
2. Open DevTools (`F12`) → **Network** tab
3. Click any download link
4. Find the request in the Network tab
5. Right-click → **Copy Value** → **Copy as cURL**
6. Paste the entire cURL command when prompted, or extract the `Cookie:` header for `.env`

### Extracting Cookie for `.env`

If you prefer to put the cookie in `.env` instead of pasting cURL each time:

1. Copy as cURL (as above)
2. Find the part that says `-H 'Cookie: ...'`
3. Copy everything between the quotes after `Cookie:`
4. Paste as `GOOGLE_COOKIE` in your `.env`

## Usage

### GUI Application (Recommended)

Launch the graphical interface:

```bash
./venv/bin/python google_takeout_gui.py
```

The GUI provides:
- Easy paste area for cookies/cURL commands
- Directory browser for output location
- Real-time progress and speed display
- Download log with color-coded status
- Start/Stop controls

### Command-Line Interface

```bash
# Run with settings from .env
./venv/bin/python google_takeout_downloader.py

# Or with command-line arguments
./venv/bin/python google_takeout_downloader.py \
  --cookie "your_cookie" \
  --url "https://takeout-download..." \
  --output "/path/to/downloads" \
  --count 100 \
  --parallel 6
```

### Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--cookie` | Full cookie header string | From `.env` |
| `--url` | First download URL | From `.env` |
| `--output` | Output directory | `./downloads` |
| `--count` | Max files to download | `100` |
| `--parallel` | Concurrent downloads | `6` |

## Re-authentication

When your session expires mid-download, the script will:

1. Pause downloads
2. Prompt you to paste a new cURL command
3. Automatically extract the cookie
4. Resume downloading from where it left off

```
============================================================
AUTHENTICATION EXPIRED
============================================================

To get a new cookie:
1. Open Chrome DevTools (F12) on Google Takeout
2. Go to Network tab
3. Click a download link
4. Right-click the request -> Copy -> Copy as cURL

Paste the ENTIRE cURL command below (or 'q' to quit):
------------------------------------------------------------
```

## Notifications & Alerts

The script includes desktop notifications and sound alerts (Linux):

- **🔐 Auth Expired** - Critical notification + sound when authentication fails
- **⚠️ Auth Warning** - Warning at ~45 minutes (sessions typically expire after ~1 hour)
- **✅ Complete** - Notification + sound when all downloads finish

### Requirements for Notifications

```bash
# Desktop notifications (usually pre-installed)
sudo zypper install libnotify-tools  # openSUSE
sudo apt install libnotify-bin       # Ubuntu/Debian

# Sound alerts (PulseAudio)
# Usually pre-installed with desktop environments
```

### Example Output

```
[takeout-3-001.zip] Starting (2.00 GB)
[takeout-3-001.zip] 25% (ETA: 2h 15m)
[takeout-3-001.zip] 50% (ETA: 1h 45m)
[takeout-3-001.zip] 75% (ETA: 58m)
[takeout-3-001.zip] Done!

⚠️  Auth session active for 45+ minutes - may expire soon

============================================================
Download complete! 50 succeeded, 0 failed
Files saved to: /smb/takeout
Total downloaded: 100.00 GB in 1:23:45
============================================================
```

## Tips

- **NFS/SMB Mounts**: If downloading to a network share, mount with your user permissions:
  ```bash
  sudo mount -t cifs //server/share /mnt/share -o guest,uid=1000,gid=1000
  ```

- **Parallel Downloads**: Start with 2-4 parallel downloads. Too many may trigger rate limiting.

- **Large Exports**: Google Takeout splits exports into 2GB files. A full Google account backup can be 100+ files.

- **Run in Background**: Use `screen` or `tmux` to keep downloads running after closing terminal:
  ```bash
  screen -S takeout
  ./venv/bin/python google_takeout_downloader.py
  # Press Ctrl+A, D to detach
  # screen -r takeout to reattach
  ```

## Building from Source

To create standalone executables:

```bash
# Install build dependencies
pip install pyinstaller

# Build for your current platform
python build.py

# Output will be in dist/ folder
```

### Automated Builds (GitHub Actions)

The repository includes a GitHub Actions workflow that automatically builds executables for all platforms when you create a release tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```

This will create a GitHub Release with binaries for:
- Linux (x64)
- Windows (x64)
- macOS (x64)

## License

MIT License

# Google Takeout Bulk Downloader

A Python script to bulk download Google Takeout archives using browser cookies for authentication.

## Features

- **Bulk Downloads** - Automatically downloads all numbered Takeout files (e.g., `takeout-001.zip`, `takeout-002.zip`, etc.)
- **Parallel Downloads** - Configurable concurrent downloads (default: 6)
- **Resume Support** - Skips already downloaded files
- **Interactive Re-authentication** - Prompts for new cookies when session expires (no restart needed)
- **cURL Paste Support** - Just paste the entire cURL command, cookie is extracted automatically
- **Progress Tracking** - Shows download progress for each file
- **Optimized Performance** - Large chunk sizes, connection pooling, and keep-alive

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/google-takeout-downloader.git
cd google-takeout-downloader

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

## Getting Your Cookie

1. Go to [Google Takeout](https://takeout.google.com) and create an export
2. Once ready, go to the download page
3. Open browser DevTools (F12) → **Network** tab
4. Click any download link
5. Right-click the request → **Copy** → **Copy as cURL**
6. Paste the entire cURL command when prompted, or extract the cookie for `.env`

## Usage

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

## Tips

- **NFS/SMB Mounts**: If downloading to a network share, mount with your user permissions:
  ```bash
  sudo mount -t cifs //server/share /mnt/share -o guest,uid=1000,gid=1000
  ```

- **Parallel Downloads**: Start with 2-4 parallel downloads. Too many may trigger rate limiting.

- **Large Exports**: Google Takeout splits exports into 2GB files. A full Google account backup can be 100+ files.

## License

MIT License

# Google Takeout Bulk Downloader

A Python script to bulk download Google Takeout archives using browser cookies for authentication.

## Features

- **Bulk Downloads** - Automatically downloads all numbered Takeout files (e.g., `takeout-001.zip`, `takeout-002.zip`, etc.)
- **Parallel Downloads** - Configurable concurrent downloads (default: 6)
- **Resume Support** - Skips already downloaded files
- **Interactive Re-authentication** - Prompts for new cookies when session expires (no restart needed)
- **cURL Paste Support** - Just paste the entire cURL command, cookie is extracted automatically
- **Progress Tracking** - Shows download progress for each file with ETA
- **Optimized Performance** - Large chunk sizes, connection pooling, and keep-alive
- **Desktop Notifications** - Get notified when auth expires or downloads complete (Linux)
- **Sound Alerts** - Audio alerts for auth expiry and completion
- **Auth Expiry Warning** - Warns before session expires (~45 min) so you can refresh proactively

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

## Getting the Initial URL

The `TAKEOUT_URL` in your `.env` file is the download link for the **first file** in your Google Takeout export. This URL contains:

- **File pattern**: `takeout-20251204T101148Z-3-001.zip` - The script increments the `001` part to download `002`, `003`, etc.
- **Authentication tokens**: Query parameters like `j=`, `i=`, `user=` that identify your export
- **Session info**: The `authuser=` parameter for multi-account users

### Why It's Needed

Google Takeout splits large exports into multiple 2GB ZIP files (e.g., 730 files for a large account). Instead of manually clicking each download link, you provide the first URL and the script automatically constructs URLs for all subsequent files.

### How to Get the URL

#### Chrome / Chromium / Edge

1. Go to [Google Takeout](https://takeout.google.com) → **Manage exports**
2. Find your export and click **Download** on the first file
3. **Before the download starts** or while it's downloading:
   - Open DevTools: Press `F12` or `Ctrl+Shift+I`
   - Go to the **Network** tab
   - Find the request that starts with `takeout-` or look for a redirect
   - Right-click the request → **Copy** → **Copy link address**
4. Paste this URL as `TAKEOUT_URL` in your `.env`

#### Firefox

1. Go to [Google Takeout](https://takeout.google.com) → **Manage exports**
2. Find your export and click **Download** on the first file
3. **Before the download starts** or while it's downloading:
   - Open DevTools: Press `F12` or `Ctrl+Shift+I`
   - Go to the **Network** tab
   - Look for the request (filter by "takeout" if needed)
   - Right-click the request → **Copy Value** → **Copy URL**
4. Paste this URL as `TAKEOUT_URL` in your `.env`

#### Alternative: Copy Link from Download Page

1. On the Google Takeout download page, **right-click** the "Download" button for file 1
2. Select **Copy link address** (Chrome) or **Copy Link** (Firefox)
3. This gives you the initial redirect URL which also works

### Example URL

```
https://takeout-download.usercontent.google.com/download/takeout-20251204T101148Z-3-001.zip?j=ceabdffe-95b3-40e5-8790-2119226fe093&i=0&user=987312302921&authuser=0
```

The script parses this and generates:
- `takeout-20251204T101148Z-3-001.zip`
- `takeout-20251204T101148Z-3-002.zip`
- `takeout-20251204T101148Z-3-003.zip`
- ... and so on

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

## License

MIT License

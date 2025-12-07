#!/usr/bin/env python3
"""
Build script to create a single standalone executable.
The binary supports both TUI (default) and Web (--web) modes.

Usage:
    python build.py              # Build for current platform
    python build.py --help       # Show instructions
"""

import subprocess
import sys
import platform
from pathlib import Path

APP_NAME = "takeout"
APP_VERSION = "4.0.0"


def get_platform():
    """Get current platform."""
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    return system


def install_pyinstaller():
    """Install PyInstaller if not present."""
    try:
        import PyInstaller
        print("✓ PyInstaller is installed")
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
        print("✓ PyInstaller installed")


def build():
    """Build single executable for current platform."""
    current_platform = get_platform()
    
    print(f"\n{'='*60}")
    print(f"Building {APP_NAME} v{APP_VERSION} for {current_platform.upper()}")
    print(f"{'='*60}\n")
    
    # PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onefile",
        "--clean",
        "--noconfirm",
        # Hidden imports for TUI
        "--hidden-import", "textual",
        "--hidden-import", "textual.widgets",
        "--hidden-import", "rich",
        # Hidden imports for Web
        "--hidden-import", "flask",
        "--hidden-import", "flask_socketio",
        "--hidden-import", "engineio.async_drivers.threading",
        # Collect submodules
        "--collect-submodules", "textual",
        "--collect-submodules", "rich",
        "--collect-submodules", "flask",
        "--collect-submodules", "flask_socketio",
        # Add data files
        "--add-data", f"google_takeout_tui.py{':' if current_platform != 'windows' else ';'}.",
        "--add-data", f"google_takeout_web.py{':' if current_platform != 'windows' else ';'}.",
        # Main script
        "takeout.py",
    ]
    
    # Platform-specific icon
    if current_platform == "windows":
        icon_path = Path("icon.ico")
        if icon_path.exists():
            cmd.extend(["--icon", str(icon_path)])
    elif current_platform == "macos":
        icon_path = Path("icon.icns")
        if icon_path.exists():
            cmd.extend(["--icon", str(icon_path)])
        cmd.extend(["--osx-bundle-identifier", "com.takeout.downloader"])
    elif current_platform == "linux":
        icon_path = Path("icon.png")
        if icon_path.exists():
            cmd.extend(["--icon", str(icon_path)])
    
    print(f"Running PyInstaller...\n")
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        # Determine output filename
        dist_path = Path("dist")
        if current_platform == "windows":
            exe_name = f"{APP_NAME}.exe"
        else:
            exe_name = APP_NAME
        
        output_file = dist_path / exe_name
        
        print(f"\n{'='*60}")
        print(f"✓ BUILD SUCCESSFUL!")
        print(f"{'='*60}")
        print(f"\nExecutable: {output_file}")
        
        if output_file.exists():
            size_mb = output_file.stat().st_size / (1024 * 1024)
            print(f"Size: {size_mb:.1f} MB")
        
        print(f"""
Usage:
  ./{exe_name}              # TUI mode (default)
  ./{exe_name} --web        # Web interface on http://localhost:5000
  ./{exe_name} --web --port 8080  # Web on custom port
  ./{exe_name} --version    # Show version
""")
        return True
    else:
        print(f"\n✗ Build failed!")
        return False


def main():
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║       Google Takeout Downloader - Build Tool                  ║
║                    Version {APP_VERSION}                            ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    if "--help" in sys.argv or "-h" in sys.argv:
        print("""
This script builds a single executable that supports both modes:
  - TUI (Terminal UI) - default mode
  - Web interface - with --web flag

The executable works on the platform it was built on.
To build for other platforms, run this script on that platform.

Requirements:
  pip install pyinstaller textual rich flask flask-socketio requests

Build:
  python build.py

Output:
  dist/takeout       (Linux/macOS)
  dist/takeout.exe   (Windows)
""")
        return
    
    install_pyinstaller()
    
    if not build():
        sys.exit(1)


if __name__ == "__main__":
    main()

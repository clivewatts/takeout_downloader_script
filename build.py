#!/usr/bin/env python3
"""
Build script to create standalone executables for Linux, macOS, and Windows.
Uses PyInstaller to package the GUI application.

Usage:
    python build.py          # Build for current platform
    python build.py --all    # Instructions for all platforms
"""

import subprocess
import sys
import platform
import shutil
from pathlib import Path

# Application info
APP_NAME = "Google Takeout Downloader"
APP_VERSION = "1.0.0"
SCRIPT_NAME = "google_takeout_gui.py"
ICON_NAME = "icon"  # Will look for icon.ico (Windows), icon.icns (macOS), icon.png (Linux)

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

def build_executable():
    """Build executable for current platform."""
    current_platform = get_platform()
    print(f"\n{'='*60}")
    print(f"Building for {current_platform.upper()}")
    print(f"{'='*60}\n")
    
    # Base PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME.replace(" ", "_"),
        "--onefile",           # Single executable
        "--windowed",          # No console window (GUI app)
        "--clean",             # Clean build
        "--noconfirm",         # Overwrite without asking
    ]
    
    # Platform-specific options
    if current_platform == "windows":
        icon_path = Path("icon.ico")
        if icon_path.exists():
            cmd.extend(["--icon", str(icon_path)])
        # Add version info for Windows
        cmd.extend(["--version-file", "version_info.txt"]) if Path("version_info.txt").exists() else None
        
    elif current_platform == "macos":
        icon_path = Path("icon.icns")
        if icon_path.exists():
            cmd.extend(["--icon", str(icon_path)])
        # macOS bundle identifier
        cmd.extend(["--osx-bundle-identifier", "com.takeout.downloader"])
        
    elif current_platform == "linux":
        icon_path = Path("icon.png")
        if icon_path.exists():
            cmd.extend(["--icon", str(icon_path)])
    
    # Add hidden imports that PyInstaller might miss
    cmd.extend([
        "--hidden-import", "requests",
        "--hidden-import", "urllib3",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.ttk",
        "--hidden-import", "tkinter.filedialog",
        "--hidden-import", "tkinter.messagebox",
        "--hidden-import", "tkinter.scrolledtext",
    ])
    
    # Add the main script
    cmd.append(SCRIPT_NAME)
    
    print(f"Running: {' '.join(cmd)}\n")
    
    # Run PyInstaller
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print(f"\n{'='*60}")
        print("✓ BUILD SUCCESSFUL!")
        print(f"{'='*60}")
        
        # Show output location
        dist_path = Path("dist")
        if current_platform == "windows":
            exe_name = f"{APP_NAME.replace(' ', '_')}.exe"
        elif current_platform == "macos":
            exe_name = f"{APP_NAME.replace(' ', '_')}.app"
        else:
            exe_name = APP_NAME.replace(" ", "_")
        
        output_file = dist_path / exe_name
        print(f"\nExecutable created at: {output_file}")
        
        if output_file.exists():
            if output_file.is_file():
                size_mb = output_file.stat().st_size / (1024 * 1024)
                print(f"Size: {size_mb:.1f} MB")
            print(f"\nTo run: {output_file}")
    else:
        print("\n✗ Build failed!")
        sys.exit(1)

def show_cross_platform_instructions():
    """Show instructions for building on all platforms."""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║           CROSS-PLATFORM BUILD INSTRUCTIONS                       ║
╚══════════════════════════════════════════════════════════════════╝

PyInstaller creates executables for the CURRENT platform only.
To build for all platforms, you need to run the build on each OS.

┌─────────────────────────────────────────────────────────────────┐
│ LINUX                                                           │
├─────────────────────────────────────────────────────────────────┤
│ python build.py                                                 │
│ Output: dist/Google_Takeout_Downloader                          │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ WINDOWS                                                         │
├─────────────────────────────────────────────────────────────────┤
│ python build.py                                                 │
│ Output: dist/Google_Takeout_Downloader.exe                      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ macOS                                                           │
├─────────────────────────────────────────────────────────────────┤
│ python build.py                                                 │
│ Output: dist/Google_Takeout_Downloader.app                      │
└─────────────────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════
GITHUB ACTIONS (Automated Cross-Platform Builds)
═══════════════════════════════════════════════════════════════════

For automated builds on all platforms, use GitHub Actions.
A workflow file has been created at: .github/workflows/build.yml

This will automatically:
1. Build executables for Linux, Windows, and macOS
2. Create a GitHub Release with all binaries
3. Trigger on version tags (e.g., v1.0.0)

To create a release:
    git tag v1.0.0
    git push origin v1.0.0

""")

def main():
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║         Google Takeout Downloader - Build Tool                    ║
║                      Version {APP_VERSION}                              ║
╚══════════════════════════════════════════════════════════════════╝
""")
    
    if "--all" in sys.argv or "--help" in sys.argv or "-h" in sys.argv:
        show_cross_platform_instructions()
        return
    
    # Install PyInstaller if needed
    install_pyinstaller()
    
    # Build for current platform
    build_executable()

if __name__ == "__main__":
    main()

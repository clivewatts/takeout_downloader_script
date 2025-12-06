#!/usr/bin/env python3
"""
Build script to create standalone executables for Linux, macOS, and Windows.
Uses PyInstaller to package the GUI and Web applications.

Usage:
    python build.py              # Build GUI for current platform
    python build.py --web        # Build Web server for current platform
    python build.py --both       # Build both GUI and Web
    python build.py --all        # Instructions for all platforms
"""

import subprocess
import sys
import platform
import shutil
from pathlib import Path

# Application info
APP_VERSION = "1.0.0"
ICON_NAME = "icon"  # Will look for icon.ico (Windows), icon.icns (macOS), icon.png (Linux)

# Build configurations
BUILD_CONFIGS = {
    'gui': {
        'name': 'Google_Takeout_Downloader',
        'script': 'google_takeout_gui.py',
        'windowed': True,
        'hidden_imports': [
            'requests', 'urllib3',
            'tkinter', 'tkinter.ttk', 'tkinter.filedialog',
            'tkinter.messagebox', 'tkinter.scrolledtext',
        ],
        'collect_submodules': [],
    },
    'web': {
        'name': 'Google_Takeout_Web',
        'script': 'google_takeout_web.py',
        'windowed': False,  # Console app for web server
        'hidden_imports': [
            'requests', 'urllib3',
            'flask', 'flask_socketio',
            'engineio.async_drivers.threading',
            'jinja2', 'markupsafe',
        ],
        'collect_submodules': [
            'flask', 'flask_socketio', 'engineio', 'socketio',
        ],
    },
}

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

def build_executable(build_type='gui'):
    """Build executable for current platform."""
    config = BUILD_CONFIGS[build_type]
    current_platform = get_platform()
    
    print(f"\n{'='*60}")
    print(f"Building {config['name']} for {current_platform.upper()}")
    print(f"{'='*60}\n")
    
    # Base PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", config['name'],
        "--onefile",           # Single executable
        "--clean",             # Clean build
        "--noconfirm",         # Overwrite without asking
    ]
    
    # Windowed mode (no console) for GUI apps
    if config['windowed']:
        cmd.append("--windowed")
    
    # Platform-specific options
    if current_platform == "windows":
        icon_path = Path("icon.ico")
        if icon_path.exists():
            cmd.extend(["--icon", str(icon_path)])
        # Add version info for Windows
        if Path("version_info.txt").exists():
            cmd.extend(["--version-file", "version_info.txt"])
        
    elif current_platform == "macos":
        icon_path = Path("icon.icns")
        if icon_path.exists():
            cmd.extend(["--icon", str(icon_path)])
        # macOS bundle identifier
        bundle_id = "com.takeout.downloader" if build_type == 'gui' else "com.takeout.web"
        cmd.extend(["--osx-bundle-identifier", bundle_id])
        
    elif current_platform == "linux":
        icon_path = Path("icon.png")
        if icon_path.exists():
            cmd.extend(["--icon", str(icon_path)])
    
    # Add hidden imports
    for imp in config['hidden_imports']:
        cmd.extend(["--hidden-import", imp])
    
    # Add collect-submodules for Flask/SocketIO
    for mod in config['collect_submodules']:
        cmd.extend(["--collect-submodules", mod])
    
    # Add the main script
    cmd.append(config['script'])
    
    print(f"Running: {' '.join(cmd)}\n")
    
    # Run PyInstaller
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print(f"\n{'='*60}")
        print(f"✓ BUILD SUCCESSFUL: {config['name']}")
        print(f"{'='*60}")
        
        # Show output location
        dist_path = Path("dist")
        if current_platform == "windows":
            exe_name = f"{config['name']}.exe"
        elif current_platform == "macos" and config['windowed']:
            exe_name = f"{config['name']}.app"
        else:
            exe_name = config['name']
        
        output_file = dist_path / exe_name
        print(f"\nExecutable created at: {output_file}")
        
        if output_file.exists():
            if output_file.is_file():
                size_mb = output_file.stat().st_size / (1024 * 1024)
                print(f"Size: {size_mb:.1f} MB")
            print(f"\nTo run: {output_file}")
            
            if build_type == 'web':
                print(f"Then open: http://localhost:5000")
        
        return True
    else:
        print(f"\n✗ Build failed for {config['name']}!")
        return False

def show_cross_platform_instructions():
    """Show instructions for building on all platforms."""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║           CROSS-PLATFORM BUILD INSTRUCTIONS                       ║
╚══════════════════════════════════════════════════════════════════╝

PyInstaller creates executables for the CURRENT platform only.
To build for all platforms, you need to run the build on each OS.

BUILD OPTIONS:
  python build.py              # Build GUI (desktop app)
  python build.py --web        # Build Web server
  python build.py --both       # Build both GUI and Web

┌─────────────────────────────────────────────────────────────────┐
│ LINUX                                                           │
├─────────────────────────────────────────────────────────────────┤
│ python build.py --both                                          │
│ Output: dist/Google_Takeout_Downloader                          │
│         dist/Google_Takeout_Web                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ WINDOWS                                                         │
├─────────────────────────────────────────────────────────────────┤
│ python build.py --both                                          │
│ Output: dist/Google_Takeout_Downloader.exe                      │
│         dist/Google_Takeout_Web.exe                             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ macOS                                                           │
├─────────────────────────────────────────────────────────────────┤
│ python build.py --both                                          │
│ Output: dist/Google_Takeout_Downloader.app                      │
│         dist/Google_Takeout_Web                                 │
└─────────────────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════
GITHUB ACTIONS (Automated Cross-Platform Builds)
═══════════════════════════════════════════════════════════════════

For automated builds on all platforms, use GitHub Actions.
A workflow file has been created at: .github/workflows/build.yml

This will automatically:
1. Build GUI and Web executables for Linux, Windows, and macOS
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
    
    # Determine what to build
    build_web = "--web" in sys.argv
    build_both = "--both" in sys.argv
    build_gui = not build_web or build_both
    
    success = True
    
    if build_gui or build_both:
        if not build_executable('gui'):
            success = False
    
    if build_web or build_both:
        if not build_executable('web'):
            success = False
    
    if success:
        print(f"\n{'='*60}")
        print("✓ ALL BUILDS COMPLETED SUCCESSFULLY!")
        print(f"{'='*60}")
    else:
        print(f"\n{'='*60}")
        print("✗ SOME BUILDS FAILED")
        print(f"{'='*60}")
        sys.exit(1)

if __name__ == "__main__":
    main()

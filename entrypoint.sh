#!/bin/bash
# Ensure downloads directory is writable
chmod 777 /downloads 2>/dev/null || true

# Run the application
exec python takeout.py --web

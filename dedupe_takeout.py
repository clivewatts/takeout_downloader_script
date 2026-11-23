#!/usr/bin/env python3
"""
Takeout Deduplication Script
=============================
Finds and removes duplicate ZIP files by comparing size + first/last bytes.
Much faster than full hashing for large files.

Usage:
    python dedupe_takeout.py /path/to/takeout/folder
    python dedupe_takeout.py /path/to/takeout/folder --dry-run  # Preview only
"""

import sys
from pathlib import Path
from collections import defaultdict

# How many bytes to read from start and end for comparison
SAMPLE_SIZE = 64 * 1024  # 64KB from each end


def get_file_signature(filepath):
    """Get a fast signature: size + first 64KB + last 64KB."""
    size = filepath.stat().st_size
    
    with open(filepath, 'rb') as f:
        # Read first chunk
        first_chunk = f.read(SAMPLE_SIZE)
        
        # Read last chunk (if the file has more than one sample worth of data).
        # The old `> SAMPLE_SIZE * 2` test skipped the tail for files between
        # 64KB and 128KB, so two different files could compare equal.
        if size > SAMPLE_SIZE:
            f.seek(-SAMPLE_SIZE, 2)  # Seek from end
            last_chunk = f.read(SAMPLE_SIZE)
        else:
            last_chunk = b''
    
    # Signature = size + hash of first+last chunks
    return (size, first_chunk, last_chunk)


def signatures_match(sig1, sig2):
    """Check if two signatures indicate duplicate files."""
    size1, first1, last1 = sig1
    size2, first2, last2 = sig2
    
    # Must have same size
    if size1 != size2:
        return False
    
    # Must have same first bytes
    if first1 != first2:
        return False
    
    # Must have same last bytes
    if last1 != last2:
        return False
    
    return True


def find_duplicates(folder):
    """Find all archive files and group potential duplicates by size first."""
    # Get all archive files sorted by name (so lower numbers come first)
    archive_files = set()
    for pattern in ("*.zip", "*.tgz", "*.tar.gz"):
        archive_files.update(folder.glob(pattern))
    zip_files = sorted(archive_files)
    
    if not zip_files:
        print(f"No archive files found in {folder}")
        return []
    
    total_files = len(zip_files)
    print(f"Found {total_files} archive files.")
    print()
    
    # Step 1: Group by size (instant)
    print("Step 1/3: Reading file sizes...")
    size_groups = defaultdict(list)
    for i, filepath in enumerate(zip_files, 1):
        try:
            size = filepath.stat().st_size
            size_groups[size].append(filepath)
            # Show progress every 50 files or at the end
            if i % 50 == 0 or i == total_files:
                print(f"  [{i}/{total_files}] Scanned {filepath.name}")
        except Exception as e:
            print(f"  Error reading {filepath.name}: {e}")
    
    # Count how many size groups have potential duplicates
    potential_dupes = {s: f for s, f in size_groups.items() if len(f) >= 2}
    unique_sizes = len(size_groups) - len(potential_dupes)
    
    print(f"  ✓ {unique_sizes} files have unique sizes (no duplicates possible)")
    print(f"  ? {sum(len(f) for f in potential_dupes.values())} files in {len(potential_dupes)} size groups need checking")
    print()
    
    if not potential_dupes:
        print("No potential duplicates found!")
        return []
    
    # Step 2: For groups with same size, compare signatures
    print("Step 2/3: Comparing file signatures (first/last 64KB)...")
    duplicates = []  # List of (keep, [duplicates])
    groups_checked = 0
    total_groups = len(potential_dupes)
    
    for size, files in potential_dupes.items():
        groups_checked += 1
        size_mb = size / (1024 * 1024)
        size_gb = size / (1024 * 1024 * 1024)
        
        if size_gb >= 1:
            size_str = f"{size_gb:.2f} GB"
        else:
            size_str = f"{size_mb:.1f} MB"
        
        print(f"  [{groups_checked}/{total_groups}] Checking {len(files)} files @ {size_str}...")
        
        # Get signatures for all files in this size group
        signatures = []
        for f in files:
            try:
                print(f"    Reading {f.name}...", end=" ", flush=True)
                sig = get_file_signature(f)
                signatures.append((f, sig))
                print("OK")
            except Exception as e:
                print(f"ERROR: {e}")
        
        # Find duplicates within this group
        matched = set()
        for i, (file1, sig1) in enumerate(signatures):
            if file1 in matched:
                continue
            
            dupes_for_file = []
            for j, (file2, sig2) in enumerate(signatures[i+1:], i+1):
                if file2 in matched:
                    continue
                if signatures_match(sig1, sig2):
                    dupes_for_file.append(file2)
                    matched.add(file2)
            
            if dupes_for_file:
                matched.add(file1)
                duplicates.append((file1, dupes_for_file))
                print(f"    ⚠ Found {len(dupes_for_file)} duplicate(s) of {file1.name}")
    
    print()
    print("Step 3/3: Analysis complete!")
    
    return duplicates


def dedupe(folder, dry_run=False):
    """Find and remove duplicate files. Returns (duplicates_found, bytes_freed)."""
    duplicate_groups = find_duplicates(folder)
    
    if not duplicate_groups:
        return 0, 0
    
    duplicates_found = 0
    bytes_freed = 0
    
    print("\n" + "=" * 60)
    print("DUPLICATE ANALYSIS")
    print("=" * 60)
    
    for keep, dupes in duplicate_groups:
        print(f"\n  ✓ KEEP: {keep.name}")
        
        for dupe in dupes:
            size = dupe.stat().st_size
            duplicates_found += 1
            bytes_freed += size
            size_mb = size / (1024 * 1024)
            
            if dry_run:
                print(f"  ✗ WOULD DELETE: {dupe.name} ({size_mb:.1f} MB)")
            else:
                print(f"  ✗ DELETING: {dupe.name} ({size_mb:.1f} MB)")
                dupe.unlink()
    
    return duplicates_found, bytes_freed


def main():
    if len(sys.argv) < 2:
        print("Usage: python dedupe_takeout.py /path/to/takeout/folder [--dry-run]")
        print("\nOptions:")
        print("  --dry-run    Preview duplicates without deleting")
        sys.exit(1)
    
    folder = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv
    
    if not folder.exists():
        print(f"Error: Folder not found: {folder}")
        sys.exit(1)
    
    if not folder.is_dir():
        print(f"Error: Not a directory: {folder}")
        sys.exit(1)
    
    print("=" * 60)
    print("TAKEOUT DEDUPLICATION SCRIPT")
    print("=" * 60)
    print(f"Folder: {folder}")
    print(f"Mode: {'DRY RUN (no files will be deleted)' if dry_run else 'LIVE (duplicates will be deleted)'}")
    print()
    
    duplicates, bytes_freed = dedupe(folder, dry_run)
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    if duplicates == 0:
        print("No duplicates found!")
    else:
        freed_gb = bytes_freed / (1024 * 1024 * 1024)
        if dry_run:
            print(f"Found {duplicates} duplicate(s) ({freed_gb:.2f} GB)")
            print("Run without --dry-run to delete them.")
        else:
            print(f"Deleted {duplicates} duplicate(s), freed {freed_gb:.2f} GB")
            print("\nYou can now re-run the downloader to fetch the correct files.")


if __name__ == "__main__":
    main()

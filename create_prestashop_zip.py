#!/usr/bin/env python3
"""
Create PrestaShop module ZIP file with proper structure.
"""
import os
import zipfile
from pathlib import Path

# Source directory (PrestaShop module)
SOURCE_DIR = Path("D:/GitHub/prestashop-odoo-webhook")

# Output ZIP file
OUTPUT_ZIP = Path("D:/GitHub/prestashopodoo.zip")

# Files to exclude
EXCLUDE_FILES = {
    ".git",
    ".gitignore",
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    "Thumbs.db",
    "SETUP_BIDIRECTIONAL_TEST.md",
    "README.md",
}


def should_exclude(filepath: Path) -> bool:
    """Check if file should be excluded."""
    for exclude in EXCLUDE_FILES:
        if exclude in str(filepath):
            return True
        if filepath.name == exclude:
            return True
    return False


def create_zip():
    """Create ZIP file with proper structure."""
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        # Walk through source directory
        for root, dirs, files in os.walk(SOURCE_DIR):
            # Remove excluded directories from walk
            dirs[:] = [d for d in dirs if not should_exclude(Path(root) / d)]

            for filename in files:
                filepath = Path(root) / filename

                # Skip excluded files
                if should_exclude(filepath):
                    continue

                # Calculate relative path
                relpath = filepath.relative_to(SOURCE_DIR.parent)

                # Convert to forward slashes for ZIP
                arcname = str(relpath).replace("\\", "/")

                # Add file to ZIP
                print(f"Adding: {arcname}")
                zf.write(filepath, arcname)

    print(f"\nZIP created: {OUTPUT_ZIP}")
    print(f"Size: {OUTPUT_ZIP.stat().st_size:,} bytes")

    # Calculate MD5
    import hashlib

    md5 = hashlib.md5()
    with open(OUTPUT_ZIP, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            md5.update(chunk)

    print(f"MD5: {md5.hexdigest()}")


if __name__ == "__main__":
    create_zip()

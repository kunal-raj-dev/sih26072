"""Vercel Serverless Function entrypoint for Project Vajra FastAPI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root and src/ to sys.path so 'vajra' and relative imports resolve
repo_root = Path(__file__).resolve().parent.parent
src_dir = repo_root / "src"

if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Set serverless environment flags
os.environ["VERCEL"] = "1"
os.environ.setdefault("VAJRA_PATHS__STORE_DIR", "/tmp/vajra/store")

# Pre-create writable /tmp directories on cold-start
tmp_store = Path(os.environ["VAJRA_PATHS__STORE_DIR"])
try:
    tmp_store.mkdir(parents=True, exist_ok=True)
    (tmp_store / "artifacts").mkdir(parents=True, exist_ok=True)
except OSError:
    pass

# Import the pre-configured FastAPI app
from vajra.api.app import app

# Export app for Vercel ASGI handler
__all__ = ["app"]

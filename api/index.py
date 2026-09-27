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
os.environ.setdefault("VAJRA_PATHS__DATA_ROOT", "/tmp/vajra/data")

# Pre-create writable /tmp directories on cold-start
for d in [
    Path(os.environ["VAJRA_PATHS__STORE_DIR"]) / "artifacts",
    Path(os.environ["VAJRA_PATHS__DATA_ROOT"]) / "external",
    Path(os.environ["VAJRA_PATHS__DATA_ROOT"]) / "processed",
]:
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

# Import the pre-configured FastAPI app
try:
    from vajra.api.app import app
except Exception as e:
    import traceback
    err_tb = traceback.format_exc()
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    app = FastAPI(title="Project Vajra [Startup Error]")

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"])
    def serverless_error_handler(full_path: str):
        return PlainTextResponse(f"FastAPI Serverless Startup Error:\n\n{err_tb}", status_code=500)

# Export app for Vercel ASGI handler
__all__ = ["app"]

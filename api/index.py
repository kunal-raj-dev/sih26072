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
    from vajra.api.app import app as _raw_app
except Exception as e:
    import traceback
    err_tb = traceback.format_exc()
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    _raw_app = FastAPI(title="Project Vajra [Startup Error]")

    @_raw_app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"])
    def serverless_error_handler(full_path: str):
        return PlainTextResponse(f"FastAPI Serverless Startup Error:\n\n{err_tb}", status_code=500)


# ASGI Path normalizer for Vercel Serverless Function rewrites
class VercelPathNormalizer:
    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            orig_path = scope.get("path", "")
            raw_qs = scope.get("query_string", b"").decode("utf-8", "ignore")

            import urllib.parse
            params = urllib.parse.parse_qs(raw_qs, keep_blank_values=True)

            target_path = orig_path
            if "vajra_path" in params:
                target_path = params.pop("vajra_path")[0]
                # Rebuild query string without vajra_path so FastAPI endpoints stay clean
                new_qs = urllib.parse.urlencode([(k, v) for k, vs in params.items() for v in vs])
                scope["query_string"] = new_qs.encode("utf-8")
            elif target_path in ("/api/index.py", "/index.py", "/api", "/api/"):
                headers = dict(scope.get("headers", []))
                forwarded_uri = headers.get(b"x-forwarded-uri", b"").decode("utf-8", "ignore")
                matched_path = headers.get(b"x-matched-path", b"").decode("utf-8", "ignore")
                if forwarded_uri:
                    target_path = forwarded_uri.split("?")[0]
                elif matched_path and not matched_path.endswith(".py"):
                    target_path = matched_path.split("?")[0]

            # If the route starts with /v1/ instead of /api/v1/
            if target_path.startswith("/v1/"):
                target_path = "/api" + target_path

            # Update ASGI scope path so FastAPI router matches cleanly
            scope["path"] = target_path
            if "raw_path" in scope:
                scope["raw_path"] = target_path.encode("utf-8")

            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    headers_list = list(message.get("headers", []))
                    headers_list.append((b"x-vajra-resolved-path", target_path.encode("utf-8")))
                    headers_list.append((b"x-vajra-orig-path", orig_path.encode("utf-8")))
                    message["headers"] = headers_list
                await send(message)

            return await self.asgi_app(scope, receive, send_wrapper)

        return await self.asgi_app(scope, receive, send)


app = VercelPathNormalizer(_raw_app)

# Export app for Vercel ASGI handler
__all__ = ["app"]

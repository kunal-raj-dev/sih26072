"""Synchronize local .env variables into Vercel Project Environment Variables.

Usage:
    python scripts/sync_vercel_env.py --token <VERCEL_PERSONAL_TOKEN>
Or set VERCEL_TOKEN in your environment.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

PROJECT_ID = "prj_f70aNECGEZ1Byg1fMcDho5hiJV8R"
PROJECT_NAME = "project-vajra"
TEAM_ID = "team_8Z1IwIGv9Ezj3dNtNWxzH7Hc"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

SENSITIVE_KEYS = {
    "CDSAPI_KEY",
    "EARTHDATA_PASSWORD",
    "NCMRWF_PASSWORD",
    "MOSDAC_PASSWORD",
}


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        print(f"Error: {path} not found.", file=sys.stderr)
        sys.exit(1)
    env_vars: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("'\"")
        if key:
            env_vars[key] = val
    return env_vars


def push_to_vercel(token: str, env_vars: dict[str, str], project_id: str = PROJECT_ID, team_id: str = TEAM_ID) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    base_url = f"https://api.vercel.com/v10/projects/{project_id}/env?teamId={team_id}&upsert=true"

    print(f"Syncing {len(env_vars)} environment variables to Vercel project {project_id}...")

    # Upload each variable with upsert=true
    success_count = 0
    with httpx.Client(timeout=15.0) as client:
        for k, v in env_vars.items():
            is_sensitive = k in SENSITIVE_KEYS or "PASSWORD" in k or "KEY" in k
            env_type = "sensitive" if is_sensitive else "plain"
            payload = {
                "key": k,
                "value": v,
                "type": env_type,
                "target": ["production", "preview", "development"],
            }
            res = client.post(base_url, headers=headers, json=payload)
            if res.status_code in (200, 201):
                success_count += 1
                masked = v[:3] + "..." + v[-2:] if len(v) > 6 else "***"
                print(f"  [OK] {k} ({env_type}) -> {masked}")
            else:
                print(f"  [ERR] {k}: HTTP {res.status_code} -> {res.text}", file=sys.stderr)

    print(f"\nCompleted: {success_count}/{len(env_vars)} variables successfully provisioned in Vercel.")


def main():
    parser = argparse.ArgumentParser(description="Sync local .env to Vercel")
    parser.add_argument("--token", help="Vercel personal access token")
    parser.add_argument("--print", action="store_true", help="Print variables for manual dashboard paste")
    args = parser.parse_args()

    envs = parse_env_file(ENV_PATH)

    token = args.token or os.environ.get("VERCEL_TOKEN")
    if not token and not args.print:
        print("\n=== Local Project Environment Variables Detected ===")
        for k, v in envs.items():
            masked = v[:3] + "..." + v[-2:] if len(v) > 6 else "***"
            print(f"  {k}={masked}")
        print("\nTo automatically push these to Vercel:")
        print("  1. Create a personal token at: https://vercel.com/account/tokens")
        print("  2. Run: python scripts/sync_vercel_env.py --token <YOUR_TOKEN>\n")
        print("Or to copy-paste directly into Vercel Dashboard:")
        print("  Go to: https://vercel.com/kunal-rajs-projects-7518d379/project-vajra/settings/environment-variables")
        print("  And paste the .env contents into the Key/Value bulk importer.\n")
        return

    if args.print:
        print(ENV_PATH.read_text(encoding="utf-8"))
        return

    push_to_vercel(token, envs)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
OSS Tracker — Data Generator
Fetches real data from GitHub, NPM Registry, and Hacker News APIs.
Publishes to MiniSky Pub/Sub topics via raw REST (no SDK).

Usage:
    python data-generator/fetch_oss.py

Pub/Sub topics expected (provision via ude or make provision):
    raw.git_repos
    raw.npm_packages
    raw.hn_stories

APIs used (all free, no auth required except GitHub token for higher rate limits):
    GitHub REST API    — https://api.github.com
    NPM Registry       — https://registry.npmjs.org
    HN Algolia API     — https://hn.algolia.com/api/v1
"""

import json
import time
import uuid
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

MINISKY_HOST = os.getenv("MINISKY_HOST", "http://localhost:8080")
PROJECT_ID   = os.getenv("MINISKY_PROJECT_ID", "local-dev-project")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))  # seconds

# Optional: set GITHUB_TOKEN env var to raise rate limit from 60 → 5000 req/hr
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# GitHub repos to track — add or remove as you like
GITHUB_REPOS = [
    "dbt-labs/dbt-core",
    "pola-rs/polars",
    "tiangolo/fastapi",
    "apache/kafka",
    "streamlit/streamlit",
    "prometheus/prometheus",
    "tycoach/unified-data-engine",
]

# NPM packages to track
NPM_PACKAGES = [
    "axios",
    "lodash",
    "express",
    "react",
    "typescript",
    "eslint",
    "prettier",
]

# HN search query — top OSS / tech stories
HN_QUERY     = "open source data engineering"
HN_PAGE_SIZE = 20

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_get(url: str, headers: dict = {}) -> dict | None:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  [HTTP {e.code}] GET {url}")
        return None
    except Exception as e:
        print(f"  [ERROR] GET {url} → {e}")
        return None


def publish(topic: str, records: list[dict]) -> bool:
    """Publish a list of records to a MiniSky Pub/Sub topic."""
    if not records:
        return True

    url = f"{MINISKY_HOST}/v1/projects/{PROJECT_ID}/topics/{topic}:publish"

    messages = []
    for record in records:
        payload = json.dumps(record).encode()
        import base64
        messages.append({"data": base64.b64encode(payload).decode()})

    body = json.dumps({"messages": messages}).encode()
    req  = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
            return True
    except Exception as e:
        print(f"  [PUBLISH ERROR] {topic} → {e}")
        return False


# ─────────────────────────────────────────────
# FETCHERS
# ─────────────────────────────────────────────

def fetch_github_repos(batch_id: str) -> list[dict]:
    """Fetch metadata for each tracked GitHub repo."""
    records = []
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    for full_name in GITHUB_REPOS:
        url  = f"https://api.github.com/repos/{full_name}"
        data = http_get(url, headers)
        if not data:
            continue

        topics_url  = f"https://api.github.com/repos/{full_name}/topics"
        topics_data = http_get(topics_url, {**headers, "Accept": "application/vnd.github.mercy-preview+json"})
        topics      = ",".join(topics_data.get("names", [])) if topics_data else ""

        record = {
            "repo_full_name": data.get("full_name"),
            "repo_name":      data.get("name"),
            "owner":          data.get("owner", {}).get("login"),
            "description":    data.get("description"),
            "stars":          data.get("stargazers_count", 0),
            "forks":          data.get("forks_count", 0),
            "open_issues":    data.get("open_issues_count", 0),
            "watchers":       data.get("watchers_count", 0),
            "language":       data.get("language"),
            "topics":         topics,
            "is_archived":    data.get("archived", False),
            "updated_at":     data.get("pushed_at") or now_iso(),
            "batch_id":       batch_id,
            "_ingested_at":   now_iso(),
        }
        records.append(record)
        print(f"  ✓ github  {full_name} — ⭐ {record['stars']:,}")

    return records


def fetch_npm_packages(batch_id: str) -> list[dict]:
    """Fetch metadata for each tracked NPM package."""
    records = []

    for pkg in NPM_PACKAGES:
        url  = f"https://registry.npmjs.org/{pkg}"
        data = http_get(url)
        if not data:
            continue

        latest_version = data.get("dist-tags", {}).get("latest", "unknown")
        version_data   = data.get("versions", {}).get(latest_version, {})
        author_raw     = data.get("author") or version_data.get("author") or {}
        author         = author_raw.get("name") if isinstance(author_raw, dict) else str(author_raw)

        # weekly downloads via separate endpoint
        dl_url  = f"https://api.npmjs.org/downloads/point/last-week/{pkg}"
        dl_data = http_get(dl_url)
        weekly_downloads = dl_data.get("downloads") if dl_data else None

        record = {
            "package_name":     data.get("name"),
            "latest_version":   latest_version,
            "description":      data.get("description"),
            "author":           author,
            "license":          version_data.get("license"),
            "weekly_downloads": weekly_downloads,
            "total_versions":   len(data.get("versions", {})),
            "homepage":         data.get("homepage"),
            "repository_url":   (data.get("repository") or {}).get("url"),
            "keywords":         ",".join(data.get("keywords") or []),
            "updated_at":       data.get("time", {}).get(latest_version) or now_iso(),
            "batch_id":         batch_id,
            "_ingested_at":     now_iso(),
        }
        records.append(record)
        print(f"  ✓ npm     {pkg}@{latest_version} — {weekly_downloads:,} dl/wk" if weekly_downloads else f"  ✓ npm     {pkg}@{latest_version}")

    return records


def fetch_hn_stories(batch_id: str) -> list[dict]:
    """Fetch top HN stories matching OSS/data engineering topics."""
    records = []

    url  = f"https://hn.algolia.com/api/v1/search?query={HN_QUERY.replace(' ', '+')}&tags=story&hitsPerPage={HN_PAGE_SIZE}"
    data = http_get(url)
    if not data:
        return records

    for hit in data.get("hits", []):
        story_id = str(hit.get("objectID", ""))
        if not story_id:
            continue

        # updated_at: use created_at since HN doesn't expose a true updated_at
        # Score changes are the proxy for "changed" — engine will detect via snapshot
        created = hit.get("created_at") or now_iso()

        record = {
            "story_id":     story_id,
            "title":        hit.get("title") or hit.get("story_title", ""),
            "author":       hit.get("author", ""),
            "url":          hit.get("url"),
            "score":        hit.get("points") or 0,
            "num_comments": hit.get("num_comments") or 0,
            "story_type":   hit.get("_tags", ["story"])[0] if hit.get("_tags") else "story",
            "tags":         ",".join(hit.get("_tags") or []),
            "updated_at":   created,
            "batch_id":     batch_id,
            "_ingested_at": now_iso(),
        }
        records.append(record)

    print(f"  ✓ hn      {len(records)} stories fetched (query: '{HN_QUERY}')")
    return records


# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────

def run():
    print("=" * 60)
    print("OSS Tracker — Data Generator")
    print(f"  MiniSky : {MINISKY_HOST}")
    print(f"  Project : {PROJECT_ID}")
    print(f"  Interval: {POLL_INTERVAL}s")
    print(f"  Repos   : {len(GITHUB_REPOS)} tracked")
    print(f"  Packages: {len(NPM_PACKAGES)} tracked")
    print("=" * 60)

    cycle = 0
    while True:
        cycle += 1
        batch_id = str(uuid.uuid4())
        ts       = now_iso()

        print(f"\n[Cycle {cycle}] {ts}")
        print(f"  batch_id: {batch_id}")
        print()

        # ── GitHub ──────────────────────────────
        print("→ Fetching GitHub repos...")
        gh_records = fetch_github_repos(batch_id)
        if gh_records:
            ok = publish("raw.git_repos", gh_records)
            print(f"  Published {len(gh_records)} records → raw.git_repos {'✓' if ok else '✗'}")

        # ── NPM ─────────────────────────────────
        print("→ Fetching NPM packages...")
        npm_records = fetch_npm_packages(batch_id)
        if npm_records:
            ok = publish("raw.npm_packages", npm_records)
            print(f"  Published {len(npm_records)} records → raw.npm_packages {'✓' if ok else '✗'}")

        # ── Hacker News ─────────────────────────
        print("→ Fetching HN stories...")
        hn_records = fetch_hn_stories(batch_id)
        if hn_records:
            ok = publish("raw.hn_stories", hn_records)
            print(f"  Published {len(hn_records)} records → raw.hn_stories {'✓' if ok else '✗'}")

        print(f"\n  ✓ Cycle {cycle} complete. Sleeping {POLL_INTERVAL}s...\n")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
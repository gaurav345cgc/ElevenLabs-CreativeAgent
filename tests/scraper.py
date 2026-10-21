#!/usr/bin/env python3
"""
scraper.py — Measured recon on target subreddits via Reddit API.

Reddit now blocks bare www.reddit.com/*.json calls with HTTP 403.
Use a free read-only app (client credentials) instead:

  1. Open https://www.reddit.com/prefs/apps
  2. Create app → type "script" (or "web app")
  3. Set redirect uri to http://localhost:8080 (required, unused)
  4. Put client id + secret in .env or the environment:

       REDDIT_CLIENT_ID=...
       REDDIT_CLIENT_SECRET=...
       REDDIT_USER_AGENT=genmyo-community-research/1.0 by u/YOUR_USERNAME

Usage:
    python scraper.py                     # all target subs, summary
    python scraper.py --sub Journaling    # one sub, with top-post titles
    python scraper.py --csv out.csv       # write a CSV
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

# Load repo .env if present (optional).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV = _REPO_ROOT / ".env"
if _ENV.is_file():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)

UA = os.environ.get(
    "REDDIT_USER_AGENT",
    "genmyo-community-research/1.0 by u/YOUR_USERNAME",
)

TARGETS = [
    "DecidingToBeBetter",
    "Healthygamergg",
    "nosurf",
    "Stoicism",
    "findapath",
    "selfimprovement",
    "getdisciplined",
    "Journaling",
    "Mindfulness",
    "Meditation",
    "simpleliving",
    "digitalminimalism",
    "GenZ",
    "CasualConversation",
    "socialskills",
]

HOOK_WORDS = [
    "i",
    "why",
    "how",
    "what",
    "anyone",
    "does",
    "stopped",
    "quit",
    "months",
    "days",
    "years",
    "actually",
    "honest",
    "unpopular",
    "advice",
    "help",
    "update",
    "realised",
    "realized",
    "noticed",
    "think",
]

_TOKEN: str | None = None


def _require_reddit_app() -> tuple[str, str]:
    client_id = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise SystemExit(
            "Reddit public JSON is blocked (403).\n"
            "Create a free app at https://www.reddit.com/prefs/apps then set:\n"
            "  REDDIT_CLIENT_ID=...\n"
            "  REDDIT_CLIENT_SECRET=...\n"
            "  REDDIT_USER_AGENT=genmyo-community-research/1.0 by u/YOUR_USERNAME\n"
        )
    if "YOUR_USERNAME" in UA:
        print(
            "warning: set REDDIT_USER_AGENT with your real Reddit username "
            "(Reddit asks for this).",
            file=sys.stderr,
        )
    return client_id, client_secret


def _access_token() -> str:
    global _TOKEN
    if _TOKEN:
        return _TOKEN

    client_id, client_secret = _require_reddit_app()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise SystemExit(f"Reddit token request failed ({exc.code}): {detail}") from exc

    token = payload.get("access_token")
    if not token:
        raise SystemExit(f"Reddit token response missing access_token: {payload}")
    _TOKEN = token
    return token


def get(path: str) -> dict:
    """GET JSON from oauth.reddit.com (authenticated read-only)."""
    url = path if path.startswith("http") else f"https://oauth.reddit.com{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {_access_token()}",
            "User-Agent": UA,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def about(sub: str) -> dict:
    d = get(f"/r/{sub}/about")["data"]
    return {
        "subreddit": sub,
        "subscribers": d.get("subscribers"),
        "active_now": d.get("accounts_active"),
        "over18": d.get("over18"),
        "created_utc": d.get("created_utc"),
        "public_description": (d.get("public_description") or "").replace("\n", " ")[:200],
    }


def top(sub: str, period: str = "month", limit: int = 100) -> list[dict]:
    path = f"/r/{sub}/top?t={period}&limit={limit}"
    children = get(path)["data"]["children"]
    return [c["data"] for c in children]


def analyse(posts: list[dict]) -> dict:
    if not posts:
        return {}
    scores = [p["score"] for p in posts]
    comments = [p["num_comments"] for p in posts]
    self_posts = sum(1 for p in posts if p.get("is_self"))
    title_lens = [len(p["title"]) for p in posts]
    words: Counter[str] = Counter()
    for p in posts:
        for w in p["title"].lower().replace("?", " ").replace(",", " ").split():
            if w in HOOK_WORDS:
                words[w] += 1
    return {
        "n_posts": len(posts),
        "median_score": statistics.median(scores),
        "median_comments": statistics.median(comments),
        "discussion_density": round(
            statistics.median(comments) / max(statistics.median(scores), 1), 3
        ),
        "pct_text_posts": round(100 * self_posts / len(posts)),
        "median_title_len": statistics.median(title_lens),
        "top_hook_words": ", ".join(f"{w}({c})" for w, c in words.most_common(6)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sub", help="single subreddit (omit r/)")
    ap.add_argument("--period", default="month", choices=["week", "month", "year"])
    ap.add_argument("--csv", help="write results to CSV")
    args = ap.parse_args()

    # Fail fast with a clear setup message if creds are missing.
    _require_reddit_app()

    subs = [args.sub] if args.sub else TARGETS
    rows: list[dict] = []

    for sub in subs:
        try:
            meta = about(sub)
            time.sleep(1.2)
            posts = top(sub, args.period)
            time.sleep(1.2)
        except Exception as e:
            print(f"  !! {sub}: {e}", file=sys.stderr)
            continue

        row = {**meta, **analyse(posts)}
        rows.append(row)

        print(f"\n=== r/{sub} ===")
        if row.get("subscribers"):
            print(f"  subscribers      {row['subscribers']:,}")
        else:
            print("  subscribers      ?")
        print(f"  active now       {row.get('active_now')}")
        print(
            f"  median score     {row.get('median_score')}   "
            f"(top/{args.period}, n={row.get('n_posts')})"
        )
        print(f"  median comments  {row.get('median_comments')}")
        print(
            f"  discussion dens. {row.get('discussion_density')}   "
            f"<- higher = more conversational, better for you"
        )
        print(f"  text posts       {row.get('pct_text_posts')}%")
        print(f"  title length     {row.get('median_title_len')} chars")
        print(f"  hook words       {row.get('top_hook_words')}")

        if args.sub:
            print("\n  --- top 25 titles (study these) ---")
            for p in sorted(posts, key=lambda x: -x["num_comments"])[:25]:
                print(
                    f"  [{p['num_comments']:>4} comments | {p['score']:>5} pts] "
                    f"{p['title'][:110]}"
                )

    if args.csv and rows:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nwrote {args.csv}")

    print(
        "\nLabel everything above Measured, with today's date. "
        "Re-run monthly; subreddit rules and norms drift ~10-15% per quarter."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Spot-check regenerated C+D scripts for wound keyword hits."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://vwhmjhoym3.execute-api.us-east-1.amazonaws.com"
TENANT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

CHECKS = {
    "PH-01": "5bf4fdf9-dcb1-40e7-862e-2e3c4c371b23",
    "WK-04": "660416ab-c93a-4e31-b37d-61a8ffd973b6",
    "WK-05": "f0fe5559-b37d-4fc9-8904-b31b7ad7a1bb",
    "PH-03": "c5aadc98-3a9f-4833-adf8-da48e2b117dd",
    "FR": "8f6fa668-642d-4ae0-9e20-01973533f564",
}
NEED = {
    "PH-01": ["pain", "body"],
    "WK-04": ["trust", "work", "job", "betray", "promise"],
    "WK-05": ["purpose", "why", "job", "work", "meaning"],
    "PH-03": ["tired", "fatigue", "rest", "exhaust", "heavy"],
    "FR": ["friend", "alone", "lonely", "chat"],
}


def _key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("CREATIVE_AGENT_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("missing key")


def main() -> None:
    headers = {"X-API-Key": _key(), "X-Tenant-Id": TENANT}
    with httpx.Client(timeout=60.0) as http:
        for code, tid in CHECKS.items():
            r = http.get(f"{BASE}/transcripts/{tid}", headers=headers)
            r.raise_for_status()
            data = r.json()
            text = (
                data.get("enhanced_text")
                or data.get("transcript_text")
                or data.get("raw_text")
                or ""
            )
            if not text and "versions" in data:
                text = json.dumps(data.get("versions"))
            low = text.lower()
            hits = [w for w in NEED[code] if w in low]
            print(
                f"{code}: words={len(low.split())} hits={hits} "
                f"title={data.get('title') or data.get('title_hint')}"
            )
            print("  open:", " ".join(low.split()[:40]), "...")


if __name__ == "__main__":
    main()

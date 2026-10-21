"""Verify Batch C/D ENHANCED scripts mention their title themes."""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://vwhmjhoym3.execute-api.us-east-1.amazonaws.com"
TENANT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def api_key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("CREATIVE_AGENT_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("missing API key")


def main() -> None:
    rows = json.loads((ROOT / "output" / "batch_cd_pending_review.json").read_text(encoding="utf-8"))
    headers = {"X-API-Key": api_key(), "X-Tenant-Id": TENANT}
    with httpx.Client(timeout=60.0) as client:
        for row in rows:
            tid = row["transcript_id"]
            data = client.get(
                f"{BASE}/transcripts/{tid}/versions",
                headers=headers,
                params={"include_content": "true"},
            ).json()
            enh = next(v for v in data["versions"] if v["version_kind"] == "ELEVENLABS_ENHANCED")
            text = enh.get("pause_review_text") or enh.get("content_text") or ""
            work = len(
                re.findall(
                    r"(?i)\b(work|job|office|career|workplace|colleague|colleagues|boss|"
                    r"employer|team|desk|meeting|role)\b",
                    text,
                )
            )
            pain = len(
                re.findall(
                    r"(?i)\b(pain|body|fatigue|burnout|ache|exhaust|sore|tension)\b",
                    text,
                )
            )
            friend = len(
                re.findall(
                    r"(?i)\b(friend|friends|friendship|lonely|loneliness|alone|"
                    r"connection|belonging)\b",
                    text,
                )
            )
            print(
                f"{row['code']}-{row['sample']}: work={work} pain={pain} friend={friend}"
            )
            if row["code"].startswith("WK") or row["code"] == "FR":
                plain = re.sub(r"\[pause[^\]]*\]", "", text)
                plain = re.sub(r"\s+", " ", plain).strip()
                print(f"  open: {plain[:200]}")


if __name__ == "__main__":
    main()

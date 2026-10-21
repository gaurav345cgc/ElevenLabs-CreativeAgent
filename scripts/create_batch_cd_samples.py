"""Create Batch C+D Script Hub samples (2 per code) — compose + enhance only.

Loads taxonomy from first10_relatability_pack.json (pillar/stage/duration/proxy wound).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import boto3
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from transcript_composer.relatability import (  # noqa: E402
    compose_wound_id_for_entry,
    load_relatability_pack,
)

BASE = "https://vwhmjhoym3.execute-api.us-east-1.amazonaws.com"
TENANT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
COMPOSER = "creative-agent-dev-composer"
BATCHES = {"C", "D"}


def _api_key() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("CREATIVE_AGENT_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    key_file = ROOT / "infra" / "terraform" / "build" / "deployed_api_key.txt"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    raise SystemExit("Missing CREATIVE_AGENT_API_KEY")


def _invoke_composer(payload: dict) -> dict:
    client = boto3.client("lambda", region_name="us-east-1")
    resp = client.invoke(
        FunctionName=COMPOSER,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    raw = json.loads(resp["Payload"].read().decode("utf-8"))
    if isinstance(raw.get("body"), str):
        body = json.loads(raw["body"])
    else:
        body = raw.get("body") or raw
    status = raw.get("statusCode", 201)
    if status not in (200, 201):
        raise RuntimeError(f"composer failed status={status} body={body}")
    return body


def _wait_enhanced(http: httpx.Client, headers: dict, transcript_id: str, timeout_s: int = 900) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = http.get(f"{BASE}/transcripts/{transcript_id}", headers=headers)
        r.raise_for_status()
        status = r.json()["status"]
        if status == "ENHANCED":
            return status
        if status in {"FAILED_ENHANCEMENT", "REVIEW_REQUIRED"}:
            err = r.json().get("last_error")
            raise RuntimeError(f"{transcript_id} ended {status}: {err}")
        print(f"  {transcript_id[:8]}… still {status}", flush=True)
        time.sleep(12)
    raise TimeoutError(f"timed out waiting for ENHANCED on {transcript_id}")


def _jobs_from_pack() -> list[tuple[str, str, dict]]:
    pack = load_relatability_pack()
    jobs: list[tuple[str, str, dict]] = []
    for entry in pack["codes"]:
        if entry.get("batch") not in BATCHES:
            continue
        code = entry["product_code"]
        wound = compose_wound_id_for_entry(entry)
        for sample in ("A", "B"):
            title = f"{code} {entry['display_name']} — sample {sample}"
            payload = {
                "tenant_id": TENANT,
                "content_type": entry.get("content_type") or "guided_meditation",
                "generation_code": entry["generation_code"],
                "wound_id": wound,
                "stage_no": int(entry["stage_no"]),
                "target_duration_minutes": int(entry["target_duration_minutes"]),
                "pillar_code": entry["pillar_code"],
                "principles": list(entry.get("principles") or []),
                "title_hint": title,
                "correlation_id": f"batch-cd-{code.lower()}-{sample.lower()}",
            }
            jobs.append((code, sample, payload))
    return jobs


def main() -> int:
    key = _api_key()
    headers = {"X-API-Key": key, "X-Tenant-Id": TENANT}
    results: list[dict] = []
    jobs = _jobs_from_pack()

    print(f"Creating {len(jobs)} samples (compose -> enhance, no TTS)...", flush=True)
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0)) as http:
        for code, sample, payload in jobs:
            title = payload["title_hint"]
            print(f"\n==> {title}", flush=True)
            try:
                created = _invoke_composer(payload)
            except Exception as exc:
                print(f"  COMPOSE FAILED: {exc}", flush=True)
                results.append(
                    {
                        "code": code,
                        "sample": sample,
                        "transcript_id": None,
                        "title": title,
                        "status": "COMPOSE_FAILED",
                        "error": str(exc),
                        "wound_id": payload["wound_id"],
                        "generation_code": payload["generation_code"],
                        "minutes": payload["target_duration_minutes"],
                    }
                )
                continue
            tid = created["transcript_id"]
            print(f"  composed transcript_id={tid}", flush=True)
            try:
                status = _wait_enhanced(http, headers, tid)
            except Exception as exc:
                print(f"  ENHANCE FAILED: {exc}", flush=True)
                results.append(
                    {
                        "code": code,
                        "sample": sample,
                        "transcript_id": tid,
                        "title": title,
                        "status": "ENHANCE_FAILED",
                        "error": str(exc),
                        "wound_id": payload["wound_id"],
                        "generation_code": payload["generation_code"],
                        "minutes": payload["target_duration_minutes"],
                    }
                )
                continue
            print(f"  ready for approval: {status}", flush=True)
            results.append(
                {
                    "code": code,
                    "sample": sample,
                    "transcript_id": tid,
                    "title": title,
                    "status": status,
                    "wound_id": payload["wound_id"],
                    "generation_code": payload["generation_code"],
                    "minutes": payload["target_duration_minutes"],
                }
            )

    out = ROOT / "output" / "batch_cd_pending_review.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    ok = [r for r in results if r.get("status") == "ENHANCED"]
    print(f"\nDone. {len(ok)}/{len(results)} ENHANCED. Wrote {out}", flush=True)
    for row in results:
        print(
            f"  {row['code']}-{row['sample']}: {row.get('transcript_id')} [{row.get('status')}] {row['title']}",
            flush=True,
        )
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

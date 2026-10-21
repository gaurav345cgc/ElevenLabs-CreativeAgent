"""Upload curated library beds to the TTS S3 background/ prefix.

Usage (from repo root, with AWS creds + .env):
  python scripts/upload_background_library.py
  python scripts/upload_background_library.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from tts_pipeline.background_policy.library_catalog import LIBRARY_BED_UPLOADS  # noqa: E402


def _bucket() -> str:
    value = os.environ.get("CREATIVE_AGENT_TTS_AUDIO_BUCKET", "").strip()
    if not value:
        raise SystemExit("Set CREATIVE_AGENT_TTS_AUDIO_BUCKET in .env")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--library-dir",
        type=Path,
        default=ROOT / "library",
        help="Local folder of bed audio files",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-upload even if key exists")
    args = parser.parse_args()

    try:
        import boto3
    except ImportError as exc:
        raise SystemExit("boto3 required") from exc

    bucket = _bucket()
    s3 = boto3.client("s3")
    library_dir: Path = args.library_dir

    uploaded = skipped = missing = 0
    for filename, code in sorted(LIBRARY_BED_UPLOADS.items(), key=lambda x: x[1]):
        local = library_dir / filename
        key = f"background/{code}.mp3"
        if not local.is_file():
            print(f"MISSING  {filename} → s3://{bucket}/{key}")
            missing += 1
            continue

        if not args.force and not args.dry_run:
            try:
                head = s3.head_object(Bucket=bucket, Key=key)
                if int(head["ContentLength"]) == local.stat().st_size:
                    print(f"SKIP     {code} (already on S3, same size)")
                    skipped += 1
                    continue
            except s3.exceptions.ClientError:
                pass

        size_mb = local.stat().st_size / (1024 * 1024)
        if args.dry_run:
            print(f"DRY-RUN  {local.name} → s3://{bucket}/{key} ({size_mb:.1f} MiB)")
            uploaded += 1
            continue

        print(f"UPLOAD   {code} ({size_mb:.1f} MiB)…")
        s3.upload_file(
            str(local),
            bucket,
            key,
            ExtraArgs={
                "ContentType": "audio/mpeg",
                "Metadata": {"profile-code": code},
            },
        )
        uploaded += 1
        print(f"  ok -> s3://{bucket}/{key}")

    print()
    print(f"done: uploaded={uploaded} skipped={skipped} missing={missing} bucket={bucket}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

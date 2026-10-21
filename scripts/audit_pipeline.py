#!/usr/bin/env python3
"""Plain-language audit for operators — run when anything stops or before a new batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from observability.pipeline_audit import CheckStatus, run_pipeline_audit
from pipeline_orchestrator.config import OrchestratorSettings
from transcript_composer.llm_config import ensure_dotenv_loaded


def main() -> int:
    ensure_dotenv_loaded()
    parser = argparse.ArgumentParser(
        description="Audit Creative Agent pipeline health (for operators and non-technical reviewers)",
    )
    parser.add_argument("--output-dir", default=None, help="Override output/ checkpoint directory")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--save",
        default=None,
        metavar="PATH",
        help="Also save the text report to a file (e.g. output/audit-report.txt)",
    )
    args = parser.parse_args()

    settings = OrchestratorSettings.from_env()
    output_dir = Path(args.output_dir) if args.output_dir else settings.output_dir
    report = run_pipeline_audit(settings=settings, output_dir=output_dir)
    text = report.format_text()

    if args.json:
        payload = {
            "overall": report.overall.value,
            "headline": report.headline,
            "transcript_id": report.transcript_id,
            "audio_job_id": report.audio_job_id,
            "local_mp3_path": report.local_mp3_path,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "summary": c.summary,
                    "detail": c.detail,
                    "action": c.action,
                }
                for c in report.checks
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(text)

    if args.save:
        save_path = Path(args.save)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(text, encoding="utf-8")
        if not args.json:
            print(f"Report saved to: {save_path.resolve()}")

    if report.overall == CheckStatus.FAIL:
        return 1
    if report.overall == CheckStatus.WARN:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

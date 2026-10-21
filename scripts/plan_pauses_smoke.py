#!/usr/bin/env python3
"""Smoke test: plan meditation pause holds from local text (Phase 17).

Calls OpenAI when a key is available. Use --dry-fixture for offline inspection.

Examples:
  python scripts/plan_pauses_smoke.py --beats-file beats.txt --target-minutes 10 --out output/pause-plan.json
  python scripts/plan_pauses_smoke.py --text-file script.txt --target-minutes 8 --dry-fixture
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from transcript_composer.llm_config import ensure_dotenv_loaded
from tts_pipeline.chunk_planner.planner import estimate_chunk_duration_ms
from tts_pipeline.chunk_planner.sentences import split_paragraphs
from tts_pipeline.pause_planner import (
    OpenAIPausePlannerClient,
    normalize_pause_plan,
    parse_pause_plan_response,
    validate_pause_plan_anchors,
)
from tts_pipeline.pause_planner.policy import PAUSE_POLICY_VERSION, PROMPT_VERSION
from tts_pipeline.pause_planner.schema import (
    PauseHold,
    PauseHoldKind,
    PausePlan,
    PausePlannerProvider,
)


def _load_beats(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError(f"beats file is empty: {path}")
    if path.suffix.lower() == ".json":
        payload = json.loads(raw)
        if isinstance(payload, dict) and isinstance(payload.get("beats"), list):
            items = payload["beats"]
        elif isinstance(payload, list):
            items = payload
        else:
            raise ValueError("beats JSON must be a list or {\"beats\": [...]}")
        beats = [str(item).strip() for item in items if str(item).strip()]
    else:
        beats = [line.strip() for line in raw.splitlines() if line.strip()]
    if not beats:
        raise ValueError(f"no usable beats in {path}")
    return beats


def _load_paragraphs(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        raise ValueError(f"no usable paragraphs in {path}")
    return paragraphs


def _estimate_speech_seconds(texts: list[str]) -> int:
    joined = "\n\n".join(texts)
    return max(0, estimate_chunk_duration_ms(joined) // 1000)


def _dry_fixture_plan(
    *,
    beats: list[str],
    paragraphs: list[str],
    target_duration_seconds: int,
    estimated_speech_seconds: int,
) -> PausePlan:
    """Deterministic offline plan for operator dry runs."""
    units = beats if beats else paragraphs
    holds: list[PauseHold] = []
    if len(units) >= 1:
        holds.append(
            PauseHold(
                hold_id="h1",
                after_beat_index=0 if beats else None,
                after_paragraph_index=None if beats else 0,
                hold_seconds=12,
                kind=PauseHoldKind.PRACTICE,
                reason="dry-fixture: absorb first cue",
            )
        )
    if len(units) >= 2:
        last = len(units) - 1
        holds.append(
            PauseHold(
                hold_id="h2",
                after_beat_index=last if beats else None,
                after_paragraph_index=None if beats else last,
                hold_seconds=30,
                kind=PauseHoldKind.INTEGRATION,
                reason="dry-fixture: closing rest",
            )
        )
    return PausePlan(
        planner=PausePlannerProvider.OPENAI,
        model="dry-fixture",
        prompt_version=PROMPT_VERSION,
        policy_version=PAUSE_POLICY_VERSION,
        target_duration_seconds=target_duration_seconds,
        estimated_speech_seconds=estimated_speech_seconds,
        total_hold_seconds=0,
        holds=holds,
    )


def _print_holds_table(plan: PausePlan) -> None:
    print()
    print(f"{'idx':<4} {'seconds':>7}  {'kind':<12}  {'anchor':<18}  reason")
    print("-" * 80)
    for index, hold in enumerate(plan.holds):
        if hold.after_beat_index is not None:
            anchor = f"beat {hold.after_beat_index}"
        else:
            anchor = f"para {hold.after_paragraph_index}"
        reason = (hold.reason or "")[:48]
        print(
            f"{index:<4} {hold.hold_seconds:>7}  {hold.kind.value:<12}  {anchor:<18}  {reason}"
        )
    print("-" * 80)
    print(f"hold_count={len(plan.holds)}  total_hold_seconds={plan.total_hold_seconds}")


def main() -> int:
    ensure_dotenv_loaded()
    parser = argparse.ArgumentParser(
        description="Plan meditation pause holds from local text or beats",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/plan_pauses_smoke.py --beats-file beats.txt "
            "--target-minutes 10 --out output/pause-plan.json\n"
            "  python scripts/plan_pauses_smoke.py --text-file script.txt "
            "--target-minutes 8 --dry-fixture\n"
        ),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--text-file",
        type=Path,
        help="Narration text file (paragraphs used as planner anchors)",
    )
    source.add_argument(
        "--beats-file",
        type=Path,
        help="Beats file: one beat per line, or JSON list / {\"beats\": [...]}",
    )
    parser.add_argument(
        "--target-minutes",
        type=float,
        default=10.0,
        help="Target meditation duration in minutes (default: 10)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional path to write normalized PausePlan JSON",
    )
    parser.add_argument(
        "--dry-fixture",
        action="store_true",
        help="Skip OpenAI and emit a deterministic offline fixture plan",
    )
    args = parser.parse_args()

    if args.target_minutes <= 0:
        print("error               ", "--target-minutes must be > 0")
        return 1

    try:
        if args.beats_file is not None:
            if not args.beats_file.is_file():
                print("error               ", f"beats file not found: {args.beats_file}")
                return 1
            beats = _load_beats(args.beats_file)
            paragraphs: list[str] = []
            use_beats = True
            speech_texts = beats
        else:
            assert args.text_file is not None
            if not args.text_file.is_file():
                print("error               ", f"text file not found: {args.text_file}")
                return 1
            beats = []
            paragraphs = _load_paragraphs(args.text_file)
            use_beats = False
            speech_texts = paragraphs
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        print("error               ", str(exc))
        return 1

    target_duration_seconds = max(1, int(round(args.target_minutes * 60)))
    estimated_speech_seconds = _estimate_speech_seconds(speech_texts)

    if args.dry_fixture:
        raw_plan = _dry_fixture_plan(
            beats=beats,
            paragraphs=paragraphs,
            target_duration_seconds=target_duration_seconds,
            estimated_speech_seconds=estimated_speech_seconds,
        )
        source_label = "dry-fixture"
    else:
        try:
            client = OpenAIPausePlannerClient()
            raw = client.plan_pauses(
                beats=beats,
                paragraphs=paragraphs,
                target_duration_seconds=target_duration_seconds,
                estimated_speech_seconds=estimated_speech_seconds,
            )
            raw_plan = parse_pause_plan_response(
                raw,
                model=client.model,
                target_duration_seconds=target_duration_seconds,
                estimated_speech_seconds=estimated_speech_seconds,
                raw_response_bytes=json.dumps(raw).encode("utf-8"),
                use_beats=use_beats,
            )
            source_label = f"openai:{client.model}"
            if client.last_latency_ms is not None:
                print("latency_ms          ", round(client.last_latency_ms, 1))
        except Exception as exc:  # noqa: BLE001 — operator smoke surface
            print("error               ", f"{type(exc).__name__}: {exc}")
            return 1

    try:
        validate_pause_plan_anchors(
            raw_plan,
            beat_count=len(beats),
            paragraph_count=len(paragraphs),
        )
        plan = normalize_pause_plan(
            raw_plan,
            target_duration_seconds=target_duration_seconds,
            estimated_speech_seconds=estimated_speech_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        print("error               ", f"{type(exc).__name__}: {exc}")
        return 1

    print("source              ", source_label)
    print("preferred_anchors   ", "beats" if use_beats else "paragraphs")
    print("anchor_count        ", len(speech_texts))
    print("target_seconds      ", target_duration_seconds)
    print("estimated_speech_s  ", estimated_speech_seconds)
    print("policy_version      ", plan.policy_version)
    print("prompt_version      ", plan.prompt_version)
    _print_holds_table(plan)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print("wrote               ", args.out.resolve())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

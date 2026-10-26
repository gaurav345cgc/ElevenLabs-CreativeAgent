"""Format orchestrator repair context into Agent 1 prompt blocks."""

from __future__ import annotations

from models.requests import CreateTranscriptRequest


def format_repair_block(request: CreateTranscriptRequest) -> str:
    """Prompt block injected when the orchestrator retries after QA failure."""
    ctx = request.repair_context
    if ctx is None:
        return ""

    lines = [
        "## QA repair brief (prior draft failed validation — fix these)",
        f"Repair attempt: {ctx.repair_attempt}",
        "Do NOT ignore this block. Keep the same wound, pillar, and generation.",
        "Rewrite so every listed failure is addressed. Stay invitational and ear-first.",
    ]
    if ctx.previous_issues:
        lines.append("\n### Prior QA failures")
        for issue in ctx.previous_issues[:12]:
            slot = f" [{issue.slot}]" if issue.slot else ""
            msg = (issue.message or "").strip()
            if msg:
                lines.append(f"- `{issue.code}`{slot}: {msg}")
            else:
                lines.append(f"- `{issue.code}`{slot}")
    instructions = (ctx.composer_instructions or "").strip()
    if instructions:
        lines.append("\n### Required repairs (follow all)")
        lines.append(instructions)
    lines.append(
        "\nAfter repairs, the script must still pass relatability and pain/pillar checks "
        "for THIS brief — do not drift into a different wound."
    )
    return "\n".join(lines)

"""Check pack stage_no values against pattern-index wound rules."""

from __future__ import annotations

from models.validation import get_wound_stage_rules
from transcript_composer.relatability import compose_wound_id_for_entry, load_relatability_pack


def main() -> None:
    rules = get_wound_stage_rules()
    pack = load_relatability_pack()
    for entry in pack["codes"]:
        wound = compose_wound_id_for_entry(entry)
        stage = int(entry["stage_no"])
        allowed = rules.get(wound)
        ok = allowed is not None and stage in allowed
        print(
            f"{entry['product_code']}: wound={wound} stage={stage} "
            f"allowed={sorted(allowed) if allowed else None} ok={ok} "
            f"pillar={entry['pillar_code']}"
        )


if __name__ == "__main__":
    main()

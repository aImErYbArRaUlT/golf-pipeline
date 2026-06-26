"""AI-assisted schema mapping (Phase 7) - with a human-validation gate.

When a new launch monitor arrives with unfamiliar columns, this proposes how to
map them into the common schema using Claude. It is deliberately *advisory*: the
output is a DRAFT that a human reviews and confirms before anything is trusted -
the model never writes a staging model or touches the pipeline. That's the
governance point: AI with guardrails, a human in the loop.

Needs the `ai` dependency group (`uv sync --group ai`) and ANTHROPIC_API_KEY.
Run via `just ai-map <source>` or `python -m golf_ingest.ai_mapping --help`.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass

from . import transform
from .sources import SOURCES, get_source

# The common schema fields the model maps a source's columns into. shot_id and
# source are synthesized (md5 lineage), so they're excluded from the mapping.
COMMON_FIELDS = [
    "player",
    "club",
    "session_date",
    "ball_speed_mph",
    "club_speed_mph",
    "smash_factor",
    "launch_angle_deg",
    "spin_rate_rpm",
    "carry_yards",
    "total_yards",
    "side_dispersion",
]

# Default to the most capable model; override with ANTHROPIC_MODEL if desired.
DEFAULT_MODEL = "claude-opus-4-8"


@dataclass(frozen=True)
class ColumnMapping:
    common_field: str
    source_column: str  # the raw column, or "" if no good match
    unit_conversion: str  # "none", or e.g. "m/s -> mph (x2.23694)"
    confidence: float  # 0.0 - 1.0
    notes: str


@dataclass(frozen=True)
class MappingProposal:
    source_name: str
    mappings: list[ColumnMapping]
    unmapped_source_columns: list[str]
    missing_common_fields: list[str]
    overall_notes: str

    @classmethod
    def from_dict(cls, d: dict) -> MappingProposal:
        return cls(
            source_name=d["source_name"],
            mappings=[ColumnMapping(**m) for m in d["mappings"]],
            unmapped_source_columns=list(d.get("unmapped_source_columns", [])),
            missing_common_fields=list(d.get("missing_common_fields", [])),
            overall_notes=d.get("overall_notes", ""),
        )


# JSON Schema the model is constrained to (output_config.format), so the
# response is always valid and parseable into the dataclasses above.
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "source_name": {"type": "string"},
        "mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "common_field": {"type": "string", "enum": COMMON_FIELDS},
                    "source_column": {"type": "string"},
                    "unit_conversion": {"type": "string"},
                    "confidence": {"type": "number"},
                    "notes": {"type": "string"},
                },
                "required": [
                    "common_field",
                    "source_column",
                    "unit_conversion",
                    "confidence",
                    "notes",
                ],
                "additionalProperties": False,
            },
        },
        "unmapped_source_columns": {"type": "array", "items": {"type": "string"}},
        "missing_common_fields": {"type": "array", "items": {"type": "string"}},
        "overall_notes": {"type": "string"},
    },
    "required": [
        "source_name",
        "mappings",
        "unmapped_source_columns",
        "missing_common_fields",
        "overall_notes",
    ],
    "additionalProperties": False,
}

_SYSTEM = """\
You map a golf launch-monitor CSV export into a fixed common schema for a data
pipeline. Each source names metrics differently and may use different units
(m/s vs mph, metres vs yards). Your job: for each common-schema field, pick the
best-matching source column and state any unit conversion needed to reach the
target unit. Be conservative - if no column is a confident match, leave
source_column empty and add it to missing_common_fields. List source columns you
did not use in unmapped_source_columns. Confidence is 0.0-1.0.

Target units: speeds in mph, distances in yards, angles in degrees, spin in rpm,
smash_factor unitless. session_date is a calendar date; player and club are
labels."""


def propose_mapping(
    source_name: str,
    header: list[str],
    units_row: list[str] | None,
    sample_rows: list[list[str]],
    model: str | None = None,
) -> MappingProposal:
    """Ask Claude to propose a mapping. Imports anthropic lazily so the rest of
    this module (dataclasses, rendering) works without the `ai` group."""
    import anthropic  # lazy: only needed for the live call

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    payload = {
        "source_name": source_name,
        "target_common_fields": COMMON_FIELDS,
        "header": header,
        "units_row": units_row,
        "sample_rows": sample_rows,
    }
    response = client.messages.create(
        model=model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        max_tokens=8192,
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": (
                    "Map this source into the common schema. Source details "
                    "(JSON):\n\n" + json.dumps(payload, indent=2)
                ),
            }
        ],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return MappingProposal.from_dict(json.loads(text))


def render_proposal(p: MappingProposal) -> str:
    """Render a proposal as a readable, reviewable report (no dependencies)."""
    lines = [
        "=" * 70,
        f"DRAFT mapping for source: {p.source_name}  (AI-suggested - NOT trusted)",
        "Review every row before using. AI proposes; you confirm.",
        "=" * 70,
        f"{'common_field':<18}{'source_column':<26}{'conf':<6}unit_conversion",
        "-" * 70,
    ]
    for m in sorted(p.mappings, key=lambda x: x.common_field):
        col = m.source_column or "(none - synthesize)"
        lines.append(f"{m.common_field:<18}{col:<26}{m.confidence:<6.2f}{m.unit_conversion}")
    if p.missing_common_fields:
        lines.append("")
        lines.append(f"Missing (no confident match): {', '.join(p.missing_common_fields)}")
    if p.unmapped_source_columns:
        lines.append(f"Unused source columns: {', '.join(p.unmapped_source_columns)}")
    if p.overall_notes:
        lines.append("")
        lines.append(f"Notes: {p.overall_notes}")
    lines.append("=" * 70)
    return "\n".join(lines)


def _read_sample(
    url: str, encoding: str, has_units_row: bool
) -> tuple[list[str], list[str] | None, list[list[str]]]:
    """Fetch a source CSV and pull its header, units row, and a couple of rows."""
    raw = transform.fetch_csv(url)
    text = raw.decode(encoding, errors="replace")
    rows = [line.split(",") for line in text.splitlines() if line.strip()]
    header = rows[0]
    units = rows[1] if has_units_row and len(rows) > 1 else None
    data_start = 2 if has_units_row else 1
    samples = rows[data_start : data_start + 2]
    return header, units, samples


def main() -> None:
    parser = argparse.ArgumentParser(description="AI-assisted schema mapping (advisory).")
    parser.add_argument("--source", required=True, help="A registered source, or any label.")
    parser.add_argument("--url", help="CSV URL (defaults to the registered source's URL).")
    parser.add_argument("--encoding", default="utf-8", help="CSV encoding (default utf-8).")
    parser.add_argument("--no-units-row", action="store_true", help="Source has no units row.")
    parser.add_argument(
        "--out",
        help="Write the draft proposal JSON here for review (e.g. mapping.draft.json).",
    )
    args = parser.parse_args()

    if args.url:
        url, encoding, has_units = args.url, args.encoding, not args.no_units_row
    else:
        src = get_source(args.source) if args.source in SOURCES else None
        if src is None:
            parser.error("Unknown source and no --url given.")
        url, encoding, has_units = src.url, src.encoding, src.has_units_row

    header, units, samples = _read_sample(url, encoding, has_units)
    proposal = propose_mapping(args.source, header, units, samples)
    print(render_proposal(proposal))

    if args.out:
        with open(args.out, "w") as f:
            json.dump(asdict(proposal), f, indent=2)
        print(f"\nDraft written to {args.out} - review and confirm before trusting it.")


if __name__ == "__main__":
    main()

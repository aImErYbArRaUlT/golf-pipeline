"""Unit tests for AI schema mapping - parsing + rendering only (no network).

These exercise the dataclass parsing and the human-readable report without
calling the Anthropic API, so they run in CI without an API key.
"""

from __future__ import annotations

from golf_ingest.ai_mapping import MappingProposal, render_proposal

_FAKE_RESPONSE = {
    "source_name": "newmonitor",
    "mappings": [
        {
            "common_field": "ball_speed_mph",
            "source_column": "BallSpeed",
            "unit_conversion": "m/s -> mph (x2.23694)",
            "confidence": 0.95,
            "notes": "metric source",
        },
        {
            "common_field": "carry_yards",
            "source_column": "Carry",
            "unit_conversion": "m -> yards (x1.09361)",
            "confidence": 0.9,
            "notes": "",
        },
        {
            "common_field": "player",
            "source_column": "",
            "unit_conversion": "none",
            "confidence": 0.0,
            "notes": "no player column present",
        },
    ],
    "unmapped_source_columns": ["Temperature", "Humidity"],
    "missing_common_fields": ["player", "session_date"],
    "overall_notes": "Metric launch monitor; convert speed and distance.",
}


def test_proposal_parses_from_model_json():
    p = MappingProposal.from_dict(_FAKE_RESPONSE)
    assert p.source_name == "newmonitor"
    assert len(p.mappings) == 3
    # the metric mapping carries its unit conversion
    ball = next(m for m in p.mappings if m.common_field == "ball_speed_mph")
    assert ball.source_column == "BallSpeed"
    assert "mph" in ball.unit_conversion
    assert p.missing_common_fields == ["player", "session_date"]


def test_render_proposal_flags_draft_and_gaps():
    report = render_proposal(MappingProposal.from_dict(_FAKE_RESPONSE))
    # the human-validation gate must be loud about being untrusted
    assert "NOT trusted" in report
    # unmapped fields surface for review
    assert "session_date" in report
    assert "Temperature" in report
    # an empty source column renders as a synthesize hint, not a blank
    assert "synthesize" in report

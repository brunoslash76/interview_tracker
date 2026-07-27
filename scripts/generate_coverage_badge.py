#!/usr/bin/env python3
"""Generate a small self-contained SVG badge from coverage.py JSON output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def badge_color(percent: float) -> str:
    if percent >= 90:
        return "#4c1"
    if percent >= 80:
        return "#97ca00"
    if percent >= 70:
        return "#a4a61d"
    if percent >= 60:
        return "#dfb317"
    return "#e05d44"


def render_badge(percent: float, label: str = "coverage") -> str:
    display = f"{percent:.0f}%"
    color = badge_color(percent)
    label_width = max(70, 8 + len(label) * 6)
    total_width = label_width + 48
    value_x = label_width + 24
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img" aria-label="{label}: {display}">
  <title>{label}: {display}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="{total_width}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="48" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">
    <text x="{label_width / 2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_width / 2}" y="14">{label}</text>
    <text x="{value_x}" y="15" fill="#010101" fill-opacity=".3">{display}</text>
    <text x="{value_x}" y="14">{display}</text>
  </g>
</svg>
"""


def load_percent(coverage_json: Path) -> float:
    payload = json.loads(coverage_json.read_text(encoding="utf-8"))
    totals = payload.get("totals")
    if isinstance(totals, dict) and "percent_covered" in totals:
        return float(totals["percent_covered"])
    total = payload.get("total")
    if isinstance(total, dict):
        for key in ("statements", "lines"):
            section = total.get(key)
            if isinstance(section, dict) and "pct" in section:
                return float(section["pct"])
    raise ValueError(f"unsupported coverage report: {coverage_json}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("output_svg", type=Path)
    parser.add_argument(
        "--label",
        default="coverage",
        help="Left-hand badge label (e.g. coverage, frontend)",
    )
    args = parser.parse_args()

    percent = load_percent(args.coverage_json)
    args.output_svg.write_text(render_badge(percent, args.label), encoding="utf-8")
    print(f"Wrote {args.output_svg} ({percent:.0f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

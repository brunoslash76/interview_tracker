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


def render_badge(percent: float) -> str:
    display = f"{percent:.0f}%"
    color = badge_color(percent)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="118" height="20" role="img" aria-label="coverage: {display}">
  <title>coverage: {display}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="118" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="70" height="20" fill="#555"/>
    <rect x="70" width="48" height="20" fill="{color}"/>
    <rect width="118" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">
    <text x="35" y="15" fill="#010101" fill-opacity=".3">coverage</text>
    <text x="35" y="14">coverage</text>
    <text x="94" y="15" fill="#010101" fill-opacity=".3">{display}</text>
    <text x="94" y="14">{display}</text>
  </g>
</svg>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("output_svg", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.coverage_json.read_text(encoding="utf-8"))
    percent = float(payload["totals"]["percent_covered"])
    args.output_svg.write_text(render_badge(percent), encoding="utf-8")
    print(f"Wrote {args.output_svg} ({percent:.0f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

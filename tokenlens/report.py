"""Shareable markdown report. Deliberately excludes file paths, commands, and
any other machine-identifying detail that the terminal `waste`/`summary`
views show — those stay local, this is the thing people screenshot.
"""

from __future__ import annotations

from tokenlens.transcripts import humanize
from tokenlens.waste import WasteCategory, biggest_lever


def render_report(
    total_cost: float,
    total_tokens: int,
    session_count: int,
    categories: dict[str, WasteCategory],
    total_input_tokens: int,
    window_label: str,
) -> str:
    lines = [
        "# TokenLens report",
        "",
        f"**${total_cost:,.2f}** spent across **{humanize(total_tokens)} tokens** "
        f"in {session_count} session(s), {window_label}.",
        "",
        "## Where it went",
        "",
    ]

    ranked = sorted(categories.values(), key=lambda c: c.tokens, reverse=True)
    for cat in ranked:
        share = (cat.tokens / total_input_tokens * 100) if total_input_tokens else 0
        lines.append(f"- **{cat.label}** — {humanize(cat.tokens)} tok ({share:.1f}% of input)")

    lines += [
        "",
        "## Biggest fix",
        "",
        biggest_lever(categories, total_input_tokens),
        "",
        "_Generated locally by TokenLens from Claude Code session transcripts. No data left this machine._",
    ]
    return "\n".join(lines)

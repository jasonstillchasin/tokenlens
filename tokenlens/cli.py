from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from tokenlens.pricing import load_pricing, turn_cost
from tokenlens.report import render_report
from tokenlens.transcripts import Session, humanize, load_sessions
from tokenlens.ui import open_dashboard, render_html
from tokenlens.waste import (
    DEFAULT_VERBOSE_THRESHOLD_CHARS,
    analyze_session_waste,
    biggest_lever,
    merge_waste,
)

console = Console()

_SINCE_RE = re.compile(r"^(\d+)([dh])$")


def parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    m = _SINCE_RE.match(value.strip())
    if not m:
        raise click.BadParameter("expected e.g. '7d' or '24h'")
    amount, unit = int(m.group(1)), m.group(2)
    delta = timedelta(days=amount) if unit == "d" else timedelta(hours=amount)
    return datetime.now(timezone.utc) - delta


@dataclass
class SessionSummary:
    id: str
    project: str
    start: datetime
    end: datetime
    turns: int
    fresh_input: int
    cache_read: int
    cache_write: int
    output: int
    cost: float
    subagent_cost: float

    @property
    def total_tokens(self) -> int:
        return self.fresh_input + self.cache_read + self.cache_write + self.output


def summarize(sessions: list[Session], pricing: dict) -> list[SessionSummary]:
    by_id: dict[str, list[Session]] = defaultdict(list)
    for s in sessions:
        by_id[s.id].append(s)

    summaries = []
    for sid, parts in by_id.items():
        all_turns = [t for p in parts for t in p.turns]
        if not all_turns:
            continue
        main_part = next((p for p in parts if not p.is_subagent), parts[0])
        cost = sum(turn_cost(t, pricing) for t in all_turns)
        subagent_cost = sum(
            turn_cost(t, pricing) for p in parts if p.is_subagent for t in p.turns
        )
        summaries.append(
            SessionSummary(
                id=sid,
                project=main_part.project,
                start=min(t.ts for t in all_turns),
                end=max(t.ts for t in all_turns),
                turns=len(main_part.turns),
                fresh_input=sum(t.input_tokens for t in all_turns),
                cache_read=sum(t.cache_read for t in all_turns),
                cache_write=sum(t.cache_write for t in all_turns),
                output=sum(t.output_tokens for t in all_turns),
                cost=cost,
                subagent_cost=subagent_cost,
            )
        )
    return sorted(summaries, key=lambda s: s.cost, reverse=True)


def render_summary_table(summaries: list[SessionSummary]) -> None:
    total_cost = sum(s.cost for s in summaries)
    total_tokens = sum(s.total_tokens for s in summaries)

    console.print(
        f"\n[bold]${total_cost:,.2f}[/bold] across [bold]{total_tokens:,}[/bold] tokens "
        f"in {len(summaries)} session(s)\n"
    )

    table = Table(show_footer=True)
    table.add_column("Session")
    table.add_column("Project")
    table.add_column("Turns", justify="right")
    table.add_column("Fresh in", justify="right")
    table.add_column("Cache read", justify="right")
    table.add_column("Cache write", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Cost", justify="right", footer=f"${total_cost:,.2f}")

    for s in summaries:
        table.add_row(
            s.id[:8],
            s.project,
            str(s.turns),
            humanize(s.fresh_input),
            humanize(s.cache_read),
            humanize(s.cache_write),
            humanize(s.output),
            f"${s.cost:,.2f}",
        )
    console.print(table)


@click.group()
def main():
    """TokenLens — see where your coding agent's tokens and dollars went."""


@main.command()
@click.option("--since", default="7d", help="Look back window, e.g. 7d or 24h.")
@click.option("--session", "session_id", default=None, help="Restrict to one session id.")
def summary(since: str, session_id: str | None):
    """Per-session and total token/cost breakdown."""
    cutoff = parse_since(since) if not session_id else None
    sessions = load_sessions(since=cutoff, session_id=session_id)
    if not sessions:
        console.print("No sessions found for that window.")
        return
    pricing = load_pricing()
    summaries = summarize(sessions, pricing)
    render_summary_table(summaries)


@main.command()
@click.option("--since", default="7d", help="Look back window, e.g. 7d or 24h.")
@click.option("--session", "session_id", default=None, help="Restrict to one session id.")
@click.option(
    "--verbose-threshold",
    default=DEFAULT_VERBOSE_THRESHOLD_CHARS,
    help="Tool result size (chars) above which it counts as verbose output.",
)
def waste(since: str, session_id: str | None, verbose_threshold: int):
    """Ranked breakdown of where tokens were likely wasted."""
    cutoff = parse_since(since) if not session_id else None
    sessions = load_sessions(since=cutoff, session_id=session_id)
    if not sessions:
        console.print("No sessions found for that window.")
        return

    per_file = [analyze_session_waste(s, verbose_threshold) for s in sessions]
    merged = merge_waste(per_file)
    total_input_tokens = sum(
        t.input_tokens + t.cache_read + t.cache_write for s in sessions for t in s.turns
    )

    ranked = sorted(merged.values(), key=lambda c: c.tokens, reverse=True)
    console.print()
    for cat in ranked:
        share = (cat.tokens / total_input_tokens * 100) if total_input_tokens else 0
        console.print(f"[bold]{cat.label}[/bold] — {humanize(cat.tokens)} tok ({share:.1f}%)")
        for ex in cat.top_examples():
            console.print(f"  • {ex}")
        if not cat.examples:
            console.print("  (none found)")
        console.print()

    console.print(f"[bold]Biggest lever:[/bold] {biggest_lever(merged, total_input_tokens)}")


@main.command()
@click.option("--since", default="7d", help="Look back window, e.g. 7d or 24h.")
@click.option("--session", "session_id", default=None, help="Restrict to one session id.")
@click.option("--out", "out_path", default=None, type=click.Path(dir_okay=False), help="Save HTML to this file (also opens in browser).")
def ui(since: str, session_id: str | None, out_path: str | None):
    """Open an HTML dashboard in your browser."""
    cutoff = parse_since(since) if not session_id else None
    sessions = load_sessions(since=cutoff, session_id=session_id)
    if not sessions:
        console.print("No sessions found for that window.")
        return

    pricing = load_pricing()
    summaries = summarize(sessions, pricing)
    per_file = [analyze_session_waste(s) for s in sessions]
    merged = merge_waste(per_file)
    total_input_tokens = sum(
        t.input_tokens + t.cache_read + t.cache_write for s in sessions for t in s.turns
    )
    window_label = f"session {session_id}" if session_id else f"last {since}"

    content = render_html(
        summaries=summaries,
        categories=merged,
        total_input_tokens=total_input_tokens,
        total_cost=sum(s.cost for s in summaries),
        total_tokens=sum(s.total_tokens for s in summaries),
        window_label=window_label,
    )
    from pathlib import Path as _Path
    path = open_dashboard(content, _Path(out_path) if out_path else None)
    console.print(f"Opened {path}")


@main.command()
@click.option("--since", default="7d", help="Look back window, e.g. 7d or 24h.")
@click.option("--session", "session_id", default=None, help="Restrict to one session id.")
@click.option("--out", "out_path", required=True, type=click.Path(dir_okay=False), help="Output markdown file.")
def report(since: str, session_id: str | None, out_path: str):
    """Write a short, shareable markdown report (no machine-identifying detail)."""
    cutoff = parse_since(since) if not session_id else None
    sessions = load_sessions(since=cutoff, session_id=session_id)
    if not sessions:
        console.print("No sessions found for that window.")
        return

    pricing = load_pricing()
    summaries = summarize(sessions, pricing)
    per_file = [analyze_session_waste(s) for s in sessions]
    merged = merge_waste(per_file)
    total_input_tokens = sum(
        t.input_tokens + t.cache_read + t.cache_write for s in sessions for t in s.turns
    )
    window_label = f"session {session_id}" if session_id else f"last {since}"

    markdown = render_report(
        total_cost=sum(s.cost for s in summaries),
        total_tokens=sum(s.total_tokens for s in summaries),
        session_count=len(summaries),
        categories=merged,
        total_input_tokens=total_input_tokens,
        window_label=window_label,
    )
    Path(out_path).write_text(markdown)
    console.print(f"Wrote {out_path}")

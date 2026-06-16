"""Waste attribution. Every number here is an estimate from transcript data,
not a measured fact — see docs/transcript-format.md for what's recoverable
and what isn't. Categories can overlap (a repeated read of a huge file shows
up in both "repeated reads" and "verbose output"); this is a diagnostic
ranking, not an exact partition of spend.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from tokenlens.transcripts import Session

# ponytail: fixed default threshold, overridable via --verbose-threshold.
# Raise it if your tools legitimately return large payloads (e.g. test logs).
DEFAULT_VERBOSE_THRESHOLD_CHARS = 2000


@dataclass
class WasteCategory:
    key: str
    label: str
    tokens: int = 0
    examples: list[tuple[str, int]] = field(default_factory=list)  # (label, tokens)
    suggestion: str = ""

    def top_examples(self, n: int = 3) -> list[str]:
        ranked = sorted(self.examples, key=lambda e: e[1], reverse=True)[:n]
        return [f"{label} ({tok:,} tok)" for label, tok in ranked]


def _repeated_reads(sess: Session) -> WasteCategory:
    cat = WasteCategory(
        key="repeated_reads",
        label="Repeated file reads",
        suggestion="cache file contents client-side or check mtime before re-reading.",
    )
    by_path: dict[str, list] = defaultdict(list)
    for call in sess.tool_calls:
        if call.name == "Read" and isinstance(call.input, dict) and "file_path" in call.input:
            by_path[call.input["file_path"]].append(call)
    for path, calls in by_path.items():
        if len(calls) <= 1:
            continue
        redundant = calls[1:]
        tokens = sum(c.result_tokens_est for c in redundant)
        cat.tokens += tokens
        cat.examples.append((f"{path} read {len(calls)}x", tokens))
    return cat


def _clean_label(value) -> str:
    return " ".join(str(value).split())


def _verbose_output(sess: Session, threshold_chars: int) -> WasteCategory:
    cat = WasteCategory(
        key="verbose_output",
        label="Verbose tool output",
        suggestion="truncate/pipe large outputs (head, --quiet, structured results) before they hit context.",
    )
    for call in sess.tool_calls:
        if call.result_chars >= threshold_chars:
            tokens = call.result_tokens_est
            cat.tokens += tokens
            label = call.input.get("file_path") or call.input.get("command") or call.name
            cat.examples.append((f"{call.name}: {_clean_label(label)[:60]}", tokens))
    return cat


def _schema_overhead(sess: Session) -> WasteCategory:
    cat = WasteCategory(
        key="schema_overhead",
        label="Tool schema / system prompt overhead (estimate)",
        suggestion="disconnect MCP servers or tools you rarely call — their schemas ride along on every turn.",
    )
    if not sess.turns:
        return cat
    first = min(sess.turns, key=lambda t: t.ts)
    cat.tokens = first.cache_write
    if cat.tokens:
        cat.examples.append(("first-turn cache write (system prompt + tool schemas, bundled)", cat.tokens))
    return cat


def _retry_loops(sess: Session) -> WasteCategory:
    cat = WasteCategory(
        key="retry_loops",
        label="Retry / error loops",
        suggestion="fix the recurring failure instead of letting the agent retry blind.",
    )
    for call in sess.tool_calls:
        if call.is_error:
            tokens = call.result_tokens_est
            cat.tokens += tokens
            label = call.input.get("command") or call.input.get("file_path") or call.name
            cat.examples.append((f"{call.name} failed: {_clean_label(label)[:60]}", tokens))
    return cat


def _history_carryover(sess: Session) -> WasteCategory:
    cat = WasteCategory(
        key="history_carryover",
        label="History carryover growth",
        suggestion="context grew well beyond turn 1 — /compact or split unrelated work into new sessions.",
    )
    if len(sess.turns) < 2:
        return cat
    ordered = sorted(sess.turns, key=lambda t: t.ts)
    baseline = ordered[0].context_size
    growth_tax = sum(max(0, t.context_size - baseline) for t in ordered[1:])
    cat.tokens = growth_tax
    if growth_tax:
        cat.examples.append(
            (f"context grew {baseline:,} → {ordered[-1].context_size:,} tok over {len(ordered)} turns", growth_tax)
        )
    return cat


def analyze_session_waste(
    sess: Session, verbose_threshold_chars: int = DEFAULT_VERBOSE_THRESHOLD_CHARS
) -> dict[str, WasteCategory]:
    cats = [
        _repeated_reads(sess),
        _verbose_output(sess, verbose_threshold_chars),
        _schema_overhead(sess),
        _retry_loops(sess),
        _history_carryover(sess),
    ]
    return {c.key: c for c in cats}


def merge_waste(many: list[dict[str, WasteCategory]]) -> dict[str, WasteCategory]:
    merged: dict[str, WasteCategory] = {}
    for cats in many:
        for key, cat in cats.items():
            if key not in merged:
                merged[key] = WasteCategory(key=cat.key, label=cat.label, suggestion=cat.suggestion)
            merged[key].tokens += cat.tokens
            merged[key].examples += cat.examples
    return merged


def biggest_lever(categories: dict[str, WasteCategory], total_input_tokens: int) -> str:
    if not categories or total_input_tokens == 0:
        return "Not enough data to call a biggest lever."
    top = max(categories.values(), key=lambda c: c.tokens)
    if top.tokens == 0:
        return "No significant waste detected in this window."
    share = top.tokens / total_input_tokens * 100
    return f"{top.label} is {share:.0f}% of input tokens. {top.suggestion}"

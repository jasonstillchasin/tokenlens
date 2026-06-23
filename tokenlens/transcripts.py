"""Read-only parser for Claude Code's local JSONL session transcripts.

Format confirmed against real data — see docs/transcript-format.md before
changing anything here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def humanize(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


@dataclass
class Turn:
    """One assistant API call's token usage."""

    session_id: str
    uuid: str
    ts: datetime
    model: str
    input_tokens: int
    cache_read: int
    cache_write_5m: int
    cache_write_1h: int
    output_tokens: int

    @property
    def cache_write(self) -> int:
        return self.cache_write_5m + self.cache_write_1h

    @property
    def context_size(self) -> int:
        """Total prompt size for this one call (fresh + all cache)."""
        return self.input_tokens + self.cache_read + self.cache_write


@dataclass
class ToolCall:
    session_id: str
    uuid: str  # uuid of the assistant message this call belongs to
    ts: datetime
    name: str
    tool_use_id: str
    input: dict
    is_error: bool | None = None
    result_chars: int = 0

    @property
    def result_tokens_est(self) -> int:
        # ponytail: chars // 4 is a rough token estimate (no real tokenizer
        # dependency). Good enough to rank offenders; swap for a real
        # tokenizer if exact counts ever matter.
        return self.result_chars // 4


@dataclass
class Session:
    id: str
    project: str
    path: Path
    is_subagent: bool
    turns: list[Turn] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def start(self) -> datetime | None:
        return min((t.ts for t in self.turns), default=None)

    @property
    def end(self) -> datetime | None:
        return max((t.ts for t in self.turns), default=None)


def find_transcript_files() -> list[tuple[Path, bool]]:
    """Returns (path, is_subagent) for every session file on this machine."""
    if not CLAUDE_PROJECTS_DIR.exists():
        return []
    files: list[tuple[Path, bool]] = []
    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        files += [(f, False) for f in project_dir.glob("*.jsonl")]
        files += [(f, True) for f in project_dir.glob("*/subagents/*.jsonl")]
    return files


def _session_id_for(path: Path, is_subagent: bool) -> str:
    return path.parent.parent.name if is_subagent else path.stem


def _project_for(path: Path, is_subagent: bool) -> str:
    return path.parent.parent.parent.name if is_subagent else path.parent.name


def load_session(path: Path, is_subagent: bool) -> Session:
    session_id = _session_id_for(path, is_subagent)
    project = _project_for(path, is_subagent)
    sess = Session(id=session_id, project=project, path=path, is_subagent=is_subagent)
    pending_calls: dict[str, ToolCall] = {}

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = obj.get("type")
            ts_raw = obj.get("timestamp")
            ts = datetime.fromisoformat(ts_raw) if ts_raw else None
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            if kind == "assistant":
                msg = obj.get("message") or {}
                usage = msg.get("usage")
                if usage and ts:
                    cc = usage.get("cache_creation") or {}
                    sess.turns.append(
                        Turn(
                            session_id=session_id,
                            uuid=obj.get("uuid", ""),
                            ts=ts,
                            model=msg.get("model", "unknown"),
                            input_tokens=usage.get("input_tokens", 0),
                            cache_read=usage.get("cache_read_input_tokens", 0),
                            cache_write_5m=cc.get("ephemeral_5m_input_tokens", 0),
                            cache_write_1h=cc.get("ephemeral_1h_input_tokens", 0),
                            output_tokens=usage.get("output_tokens", 0),
                        )
                    )
                for block in msg.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and ts:
                        call = ToolCall(
                            session_id=session_id,
                            uuid=obj.get("uuid", ""),
                            ts=ts,
                            name=block.get("name", "unknown"),
                            tool_use_id=block.get("id", ""),
                            input=block.get("input") or {},
                        )
                        sess.tool_calls.append(call)
                        pending_calls[call.tool_use_id] = call

            elif kind == "user":
                msg = obj.get("message") or {}
                content = msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            call = pending_calls.get(block.get("tool_use_id"))
                            if call is None:
                                continue
                            call.is_error = bool(block.get("is_error"))
                            raw = block.get("content")
                            if isinstance(raw, str):
                                call.result_chars = len(raw)
                            elif isinstance(raw, list):
                                call.result_chars = sum(
                                    len(b.get("text", "")) for b in raw if isinstance(b, dict)
                                )
    return sess


def load_sessions(
    since: datetime | None = None, session_id: str | None = None
) -> list[Session]:
    """Loads every session (and subagent) file, optionally filtered.

    `since` filters out sessions whose last turn is older than the cutoff.
    `session_id` restricts to one real session (matches its subagent files too).
    """
    sessions = []
    for path, is_subagent in find_transcript_files():
        if session_id and _session_id_for(path, is_subagent) != session_id:
            continue
        sess = load_session(path, is_subagent)
        if not sess.turns:
            continue
        if since and (sess.end is None or sess.end < since):
            continue
        sessions.append(sess)
    return sessions

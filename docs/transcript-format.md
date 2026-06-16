# Claude Code transcript format (confirmed against real data)

Discovered by inspecting real session files on this machine, not the docs. If
a future Claude Code version changes this, re-run the inspection in this file
before touching the parser.

## Location

```
~/.claude/projects/<slugified-cwd>/<session-uuid>.jsonl       # main thread
~/.claude/projects/<slugified-cwd>/<session-uuid>/subagents/agent-*.jsonl  # Task-tool subagents
```

The slug is the project's working directory with `/` replaced by `-`. Each
`.jsonl` line is one JSON object. A project directory can hold many session
files (one per `claude` invocation / resume).

Subagent transcripts are **separate files**, not interleaved lines in the
parent session file. Every line in a subagent file has `"isSidechain": true`.
A naive "sum every line in every .jsonl under the project dir" will include
subagent spend automatically (correct — it's real billed spend) but you must
decide whether to attribute it to the parent session or report it separately.
No `isSidechain: true` lines were found in any *main* session file on this
machine — sidechain-ness is a file-location property, not a per-line mix-in.

## Line types (`type` field)

Observed on a 1625-line real session:

| type | count | carries `usage`? |
|---|---|---|
| `assistant` | 644 | **yes** |
| `user` | 438 | no |
| `attachment` | 121 | no |
| `queue-operation` | 136 | no |
| `last-prompt` | 111 | no |
| `system` | 66 | no |
| `pr-link` | 109 | no |

**Only `assistant` lines carry token usage.** Everything else is metadata
(hook events, queued prompts, attachments, PR links). No `summary` /
compaction line type was observed in any session on this machine — if one
turns up later it has no `usage` either, so it's safe to ignore for token
math either way.

## Token usage (on `assistant` lines, at `message.usage`)

Real example:

```json
{
  "input_tokens": 3,
  "cache_creation_input_tokens": 11291,
  "cache_read_input_tokens": 12908,
  "output_tokens": 168,
  "cache_creation": {
    "ephemeral_1h_input_tokens": 11291,
    "ephemeral_5m_input_tokens": 0
  },
  "service_tier": "standard"
}
```

Field meanings, confirmed:

- `input_tokens` — fresh, uncached input tokens for this one API call.
- `cache_read_input_tokens` — tokens served from prompt cache. Cheap.
- `cache_creation_input_tokens` — tokens newly written to cache this call.
  **Not uniformly priced** — it splits into `ephemeral_5m_input_tokens` and
  `ephemeral_1h_input_tokens`, which Anthropic prices differently (1h cache
  writes cost more than 5m writes). Sum the two sub-fields to get
  `cache_creation_input_tokens` back; price them separately for accuracy.
- `output_tokens` — generated tokens for this call.
- `message.model` — present per-message, e.g. `"claude-sonnet-4-6"`. A single
  session can mix models (main thread vs. a Haiku subagent), so price
  per-message by this field, never assume one model per session.

`usage` is **per API call**, not cumulative — summing `input_tokens` and
`output_tokens` across all `assistant` lines in a session gives the
session total. This is what Milestone 0's acceptance check does.

## Tool calls and results

`tool_use` lives inside an `assistant` message's `content` array:

```json
{"type": "tool_use", "id": "...", "name": "Bash", "input": {"command": "...", "description": "..."}, "caller": "..."}
```

The matching `tool_result` lives inside the **next `user` line's**
`message.content` array:

```json
{"type": "tool_result", "tool_use_id": "...", "is_error": false, "content": "<string, or a list of content blocks>"}
```

`content` is usually a plain string (tool output text) but can be a list of
content blocks (e.g. for image results) — handle both. `is_error: true`
marks a failed tool call; the next assistant turn that retries the same
tool/args is the "retry loop" signal for Milestone 2.

## What's NOT recoverable from the transcript

The system prompt and full tool-schema definitions sent on every call are
**not logged as their own field** — Claude Code doesn't write "here's the
system prompt" or "here's the tool list" to the JSONL. The only proxy is
`cache_creation_input_tokens` on a session's first `assistant` line, which
bundles system prompt + tool schemas + any cached file content together.
Milestone 2's "tool-schema / metadata overhead" number is therefore an
**estimate with a stated ceiling**, not a measured fact — call it out as such
in the waste report rather than presenting it as precise.

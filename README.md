# TokenLens

See where your coding agent's tokens and dollars went — and the one fix that matters most.

```
$ tokenlens waste --since 7d

History carryover growth — 12.4M tok (61.2%)
  • context grew 18,204 → 142,608 tok over 312 turns (12,210,035 tok)

Verbose tool output — 1.8M tok (8.9%)
  • Bash: pytest -v (412,300 tok)
  • Read: src/generated/schema.py (98,200 tok)

Tool schema / system prompt overhead (estimate) — 640.0K tok (3.2%)
  • first-turn cache write (system prompt + tool schemas, bundled) (640,000 tok)

Repeated file reads — 210.5K tok (1.0%)
  • src/config.py read 9x (180,400 tok)

Retry / error loops — 40.2K tok (0.2%)
  • Bash failed: npm test (40,200 tok)

Biggest lever: History carryover growth is 61% of input tokens. context grew
well beyond turn 1 — /compact or split unrelated work into new sessions.
```

## Install

```bash
git clone https://github.com/jasonstillchasin/tokenlens
pip install ./tokenlens
```

## How it works

TokenLens reads the JSONL session transcripts Claude Code already writes to
`~/.claude/projects/`, sums the token usage Anthropic's API reports on every
turn, and prices it against a `pricing.toml` you can edit. The `waste`
command then ranks five known sources of token bloat — repeated reads,
verbose tool output, tool-schema overhead, retry loops, and runaway context
growth — so you can see which one is actually worth fixing.

## Commands

- `tokenlens summary [--since 7d] [--session <id>]` — per-session cost and token breakdown.
- `tokenlens waste [--since 7d] [--session <id>]` — ranked waste breakdown with the biggest lever called out.
- `tokenlens report --out report.md [--since 7d]` — short, shareable markdown version of the above.

## Privacy

Fully local. TokenLens only reads files already on your machine and never
makes a network call. It never modifies or deletes a transcript. `report.md`
is written without file paths, commands, or other machine-identifying
detail — safe to post.

## Pricing

`tokenlens/pricing.toml` ships with reasonable defaults per model, split by
fresh input / cached input (5m and 1h write tiers price differently) / cache
read / output. Edit it to match your actual rate. See
[docs/transcript-format.md](docs/transcript-format.md) for how the numbers
are derived, and [ROADMAP.md](ROADMAP.md) for what's deliberately not built yet.

## License

MIT

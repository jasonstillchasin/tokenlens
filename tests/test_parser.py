"""Run with: python tests/test_parser.py
Asserts the parser and waste detectors against a fixture with known totals.
"""

from pathlib import Path

from tokenlens.transcripts import load_session
from tokenlens.waste import analyze_session_waste

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.jsonl"


def test_token_totals():
    sess = load_session(FIXTURE, is_subagent=False)
    assert len(sess.turns) == 3
    assert sum(t.input_tokens for t in sess.turns) == 180
    assert sum(t.cache_read for t in sess.turns) == 1250
    assert sum(t.cache_write for t in sess.turns) == 500
    assert sum(t.output_tokens for t in sess.turns) == 45


def test_tool_calls():
    sess = load_session(FIXTURE, is_subagent=False)
    assert len(sess.tool_calls) == 3
    reads = [c for c in sess.tool_calls if c.name == "Read"]
    assert len(reads) == 2
    bash = [c for c in sess.tool_calls if c.name == "Bash"][0]
    assert bash.is_error is True


def test_waste_categories():
    sess = load_session(FIXTURE, is_subagent=False)
    cats = analyze_session_waste(sess)

    # second Read of the same file: "README contents here." = 22 chars // 4
    assert cats["repeated_reads"].tokens == 22 // 4

    # first turn's cache write is the schema/system-prompt proxy
    assert cats["schema_overhead"].tokens == 500

    # one failed Bash call: "command not found: false-typo" = 30 chars // 4
    assert cats["retry_loops"].tokens == 30 // 4


if __name__ == "__main__":
    test_token_totals()
    test_tool_calls()
    test_waste_categories()
    print("ok")

"""Render a self-contained HTML dashboard and open it in the default browser."""
from __future__ import annotations

import atexit
import html
import webbrowser
from pathlib import Path
from tempfile import NamedTemporaryFile
from datetime import datetime

from tokenlens.transcripts import humanize
from tokenlens.waste import WasteCategory, biggest_lever

_CAT_COLORS = {
    "history_carryover": "#f85149",
    "verbose_output": "#d29922",
    "schema_overhead": "#8b949e",
    "repeated_reads": "#58a6ff",
    "retry_loops": "#3fb950",
}


def _h(s: object) -> str:
    return html.escape(str(s))


def _waste_rows(categories: dict[str, WasteCategory], total_input_tokens: int) -> str:
    ranked = sorted(categories.values(), key=lambda c: c.tokens, reverse=True)
    rows = []
    has_overlap = False
    for cat in ranked:
        share = (cat.tokens / total_input_tokens * 100) if total_input_tokens else 0
        if share > 100:
            has_overlap = True
        color = _CAT_COLORS.get(cat.key, "#58a6ff")
        bar_width = min(share, 100)
        if cat.examples:
            examples_html = "".join(
                f'<div class="example">• {_h(ex)}</div>' for ex in cat.top_examples(3)
            )
        else:
            examples_html = '<div class="example muted">(none found)</div>'
        rows.append(f"""
        <div class="waste-row">
          <div class="waste-header">
            <span class="waste-label">{_h(cat.label)}</span>
            <span class="waste-tokens">{humanize(cat.tokens)} tok</span>
            <span class="waste-pct" style="color:{color}">{share:.1f}%</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill" style="width:{bar_width:.2f}%;background:{color}"></div>
          </div>
          <div class="examples">{examples_html}</div>
          <div class="suggestion">→ {_h(cat.suggestion)}</div>
        </div>""")
    overlap_note = (
        '<p class="overlap-note">* Percentages can exceed 100 — some tokens appear in multiple categories.</p>'
        if has_overlap else ""
    )
    return "\n".join(rows) + overlap_note


def _session_rows(summaries: list) -> str:
    rows = []
    for s in summaries:
        date_str = s.start.strftime("%Y-%m-%d") if s.start else "—"
        data_date = s.start.isoformat() if s.start else ""
        rows.append(f"""
        <tr>
          <td class="mono muted" data-val="{_h(s.id[:12])}">{_h(s.id[:12])}</td>
          <td data-val="{_h(s.project)}">{_h(s.project)}</td>
          <td class="right" data-val="{s.turns}">{s.turns:,}</td>
          <td class="right" data-val="{s.total_tokens}">{humanize(s.total_tokens)}</td>
          <td class="right mono" data-val="{_h(data_date)}">{_h(date_str)}</td>
          <td class="right cost" data-val="{s.cost}">${s.cost:,.4f}</td>
        </tr>""")
    return "\n".join(rows)


def render_html(
    summaries: list,
    categories: dict[str, WasteCategory],
    total_input_tokens: int,
    total_cost: float,
    total_tokens: int,
    window_label: str,
) -> str:
    lever = biggest_lever(categories, total_input_tokens)
    waste_rows = _waste_rows(categories, total_input_tokens)
    session_rows = _session_rows(summaries)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TokenLens — {_h(window_label)}</title>
<style>
  :root {{
    --bg: #0d1117;
    --card: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --muted: #8b949e;
    --accent: #58a6ff;
    --red: #f85149;
    --green: #3fb950;
    --yellow: #d29922;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; font-size: 14px; line-height: 1.5; padding: 24px; }}
  a {{ color: var(--accent); }}
  .page {{ max-width: 960px; margin: 0 auto; }}

  /* Header */
  .header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }}
  .logo {{ font-size: 20px; font-weight: 700; letter-spacing: -0.5px; color: var(--text); }}
  .logo span {{ color: var(--accent); }}
  .window-label {{ color: var(--muted); font-size: 13px; }}

  /* Stat cards */
  .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }}
  .stat {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
  .stat-value {{ font-size: 28px; font-weight: 700; letter-spacing: -1px; color: var(--text); }}
  .stat-label {{ color: var(--muted); font-size: 12px; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.5px; }}

  /* Lever callout */
  .lever {{ background: #1a1f2e; border: 1px solid #2d3561; border-left: 3px solid var(--accent); border-radius: 8px; padding: 14px 16px; margin-bottom: 20px; font-size: 13px; color: var(--text); }}
  .lever strong {{ color: var(--accent); }}

  /* Section */
  .section {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 20px; }}
  .section-title {{ font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); margin-bottom: 16px; }}

  /* Waste rows */
  .waste-row {{ margin-bottom: 18px; }}
  .waste-row:last-child {{ margin-bottom: 0; }}
  .waste-header {{ display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }}
  .waste-label {{ font-weight: 500; flex: 1; }}
  .waste-tokens {{ color: var(--muted); font-size: 13px; }}
  .waste-pct {{ font-weight: 700; font-size: 15px; min-width: 48px; text-align: right; }}
  .bar-track {{ height: 6px; background: var(--border); border-radius: 3px; margin-bottom: 8px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.3s; }}
  .examples {{ display: flex; flex-direction: column; gap: 2px; }}
  .example {{ font-size: 12px; color: var(--muted); font-family: ui-monospace, "SF Mono", Consolas, monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .suggestion {{ font-size: 12px; color: var(--accent); margin-top: 6px; opacity: 0.75; }}

  /* Table */
  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); cursor: pointer; user-select: none; white-space: nowrap; }}
  th:hover {{ color: var(--text); }}
  th.sorted {{ color: var(--accent); }}
  th.right, td.right {{ text-align: right; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: rgba(255,255,255,0.02); }}
  .mono {{ font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 12px; }}
  .muted {{ color: var(--muted); }}
  .cost {{ font-weight: 600; color: var(--green); }}

  /* Overlap note */
  .overlap-note {{ font-size: 11px; color: var(--muted); margin-top: 12px; }}

  /* Footer */
  .footer {{ text-align: center; color: var(--muted); font-size: 12px; margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--border); }}
</style>
</head>
<body>
<div class="page">

  <div class="header">
    <div class="logo">Token<span>Lens</span></div>
    <div class="window-label">{_h(window_label)}</div>
  </div>

  <div class="stats">
    <div class="stat">
      <div class="stat-value">${total_cost:,.2f}</div>
      <div class="stat-label">Total cost</div>
    </div>
    <div class="stat">
      <div class="stat-value">{humanize(total_tokens)}</div>
      <div class="stat-label">Total tokens</div>
    </div>
    <div class="stat">
      <div class="stat-value">{len(summaries)}</div>
      <div class="stat-label">Sessions</div>
    </div>
  </div>

  <div class="lever"><strong>⚡ Biggest lever:</strong> {_h(lever)}</div>

  <div class="section">
    <div class="section-title">Token Waste Breakdown</div>
    {waste_rows}
  </div>

  <div class="section">
    <div class="section-title">Sessions</div>
    <div class="table-wrap">
      <table id="sessions-table">
        <thead>
          <tr>
            <th data-col="0">Session</th>
            <th data-col="1">Project</th>
            <th data-col="2" class="right">Turns</th>
            <th data-col="3" class="right">Tokens</th>
            <th data-col="4" class="right">Date</th>
            <th data-col="5" class="right sorted">Cost ▾</th>
          </tr>
        </thead>
        <tbody>
          {session_rows}
        </tbody>
      </table>
    </div>
  </div>

  <div class="footer">Generated locally by TokenLens · {_h(generated)} · no network calls made</div>
</div>

<script>
(function() {{
  var table = document.getElementById('sessions-table');
  var tbody = table.querySelector('tbody');
  var ths = table.querySelectorAll('th');
  var sortCol = 5, sortAsc = false;

  function cellVal(row, col) {{
    var v = row.cells[col].dataset.val;
    if (v === undefined || v === '') return '';
    var n = parseFloat(v);
    if (!isNaN(n)) return n;
    var text = v;
    if (text.includes('K')) {{ n = parseFloat(text) * 1e3; }}
    else if (text.includes('M')) {{ n = parseFloat(text) * 1e6; }}
    else if (text.includes('B')) {{ n = parseFloat(text) * 1e9; }}
    if (!isNaN(n)) return n;
    return text.toLowerCase();
  }}

  function sort(col, asc) {{
    var rows = Array.from(tbody.rows);
    rows.sort(function(a, b) {{
      var av = cellVal(a, col), bv = cellVal(b, col);
      if (av < bv) return asc ? -1 : 1;
      if (av > bv) return asc ? 1 : -1;
      return 0;
    }});
    rows.forEach(function(r) {{ tbody.appendChild(r); }});
    ths.forEach(function(th, i) {{
      th.classList.remove('sorted');
      th.textContent = th.textContent.replace(/ [▴▾]$/, '');
    }});
    ths[col].classList.add('sorted');
    ths[col].textContent += asc ? ' ▴' : ' ▾';
  }}

  ths.forEach(function(th, i) {{
    th.addEventListener('click', function() {{
      if (sortCol === i) {{ sortAsc = !sortAsc; }} else {{ sortCol = i; sortAsc = false; }}
      sort(sortCol, sortAsc);
    }});
  }});
}})();
</script>
</body>
</html>"""


def open_dashboard(html_content: str, out_path: Path | None = None) -> Path:
    if out_path:
        out_path.write_text(html_content, encoding="utf-8")
        path = out_path
    else:
        tmp = NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8")
        try:
            tmp.write(html_content)
            tmp.close()
        except Exception:
            tmp.close()
            Path(tmp.name).unlink(missing_ok=True)
            raise
        path = Path(tmp.name)
        atexit.register(lambda p=path: p.unlink(missing_ok=True))
    webbrowser.open(path.resolve().as_uri())
    return path

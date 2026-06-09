"""Interactive HTML report renderer for the Robot Framework failure matrix."""
from __future__ import annotations

import html as _html
import json
from collections import defaultdict
from datetime import datetime
from typing import Optional


def _e(text) -> str:
    return _html.escape(str(text or ""), quote=True)


def _score_cls(score: int) -> str:
    if score >= 75:
        return "crit"
    if score >= 55:
        return "high"
    if score >= 35:
        return "med"
    return "low"


def _badge(score: int, escalated: bool = False) -> str:
    cls = _score_cls(score)
    api = '<span class="api-tag">API</span>' if escalated else ""
    return f'<span class="badge badge-{cls}">{score}{api}</span>'


def _plbl(score: int) -> str:
    if score >= 70:
        lbl = "P1"
    elif score >= 55:
        lbl = "P2"
    elif score >= 40:
        lbl = "P3"
    else:
        lbl = "P4"
    return f'<span class="plbl plbl-{lbl}">{lbl}</span>'


def _chip(ft: str) -> str:
    if ft == "functional":
        return '<span class="chip chip-fn">🐛 Functional</span>'
    if ft == "infra-keyword":
        return '<span class="chip chip-infra">⚙ Missing keyword</span>'
    if ft == "infra-setup":
        return '<span class="chip chip-infra">⚙ Infra setup</span>'
    return '<span class="chip chip-infra">⚙ Setup issue</span>'


def _http_code_html(code: Optional[int]) -> str:
    if code is None:
        return ""
    cls = "code-5xx" if code >= 500 else "code-4xx"
    return f'<span class="{cls}">HTTP {code}</span>'


_CSS = """\
:root{
  --crit:#dc2626;--high:#ea580c;--med:#b45309;--low:#16a34a;
  --bg:#f8fafc;--surface:#fff;--border:#e2e8f0;
  --text:#1e293b;--muted:#64748b;--code-bg:#f1f5f9;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--text);font-size:14px;line-height:1.6}
.wrap{max-width:1380px;margin:0 auto;padding:24px 20px}

/* ── Header ── */
header{margin-bottom:20px}
header h1{font-size:22px;font-weight:700}
.meta{color:var(--muted);font-size:13px;margin-top:2px}
.jump{display:flex;gap:16px;flex-wrap:wrap;margin-top:10px;font-size:13px}
.jump a{color:#3b82f6;text-decoration:none}
.jump a:hover{text-decoration:underline}

/* ── Stats bar ── */
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:22px}
.stat{background:var(--surface);border:1px solid var(--border);
  border-radius:10px;padding:12px 18px;text-align:center;min-width:82px}
.stat .num{display:block;font-size:26px;font-weight:800}
.stat .lbl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.stat.crit .num{color:var(--crit)}
.stat.high .num{color:var(--high)}
.stat.med  .num{color:var(--med)}
.stat.low  .num{color:var(--low)}

/* ── Sections ── */
section{background:var(--surface);border:1px solid var(--border);
  border-radius:10px;padding:20px;margin-bottom:18px}
section>h2{font-size:15px;font-weight:600;margin-bottom:14px;
  padding-bottom:10px;border-bottom:1px solid var(--border)}

/* ── Chart ── */
.chart-row{display:flex;align-items:center;gap:40px;flex-wrap:wrap}
.chart-wrap{width:200px;height:200px;flex-shrink:0}
.legend{display:flex;flex-direction:column;gap:9px}
.legend-row{display:flex;align-items:center;gap:8px;font-size:13px}
.dot{width:11px;height:11px;border-radius:50%;flex-shrink:0}
.dot-crit{background:var(--crit)}.dot-high{background:var(--high)}
.dot-med{background:var(--med)}.dot-low{background:var(--low)}
.leg-label{flex:1;min-width:110px}
.leg-cnt{font-weight:700;min-width:28px;text-align:right}
.leg-pct{color:var(--muted);min-width:38px;text-align:right;font-size:12px}

/* ── Tables ── */
.tscroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:7px 10px;font-size:11px;font-weight:600;
  text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
  background:var(--bg);border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid var(--border);vertical-align:top}
tr:last-child td{border-bottom:none}
tbody tr:hover td{background:#f8fafc}

/* ── Badges ── */
.badge{display:inline-flex;align-items:center;gap:3px;
  padding:1px 8px;border-radius:9999px;font-size:12px;font-weight:700;
  color:#fff;white-space:nowrap}
.badge-crit{background:var(--crit)}.badge-high{background:var(--high)}
.badge-med{background:var(--med)}.badge-low{background:var(--low)}
.api-tag{background:rgba(255,255,255,.25);font-size:9px;font-weight:600;
  letter-spacing:.03em;padding:1px 4px;border-radius:3px}

/* ── P-labels ── */
.plbl{display:inline-block;padding:1px 7px;border-radius:4px;
  font-size:11px;font-weight:700;white-space:nowrap}
.plbl-P1{background:#fee2e2;color:#991b1b}
.plbl-P2{background:#ffedd5;color:#9a3412}
.plbl-P3{background:#fef3c7;color:#92400e}
.plbl-P4{background:#dcfce7;color:#166534}

/* ── Chips ── */
.chip{display:inline-block;padding:1px 7px;border-radius:4px;font-size:11px;font-weight:500}
.chip-fn{background:#dbeafe;color:#1e40af}
.chip-infra{background:#f1f5f9;color:#475569}

/* ── Count badge ── */
.cnt{background:var(--code-bg);color:var(--text);border-radius:9999px;
  padding:1px 8px;font-size:12px;font-weight:600;white-space:nowrap}

/* ── HTTP codes ── */
.code-5xx{color:var(--crit);font-weight:700}
.code-4xx{color:var(--high);font-weight:700}

/* ── Collapsible ── */
details{border:1px solid var(--border);border-radius:8px}
details+details{margin-top:8px}
details[open]{box-shadow:0 2px 8px rgba(0,0,0,.06)}
summary{padding:11px 14px;cursor:pointer;
  display:flex;align-items:flex-start;gap:10px;
  user-select:none;list-style:none}
summary::-webkit-details-marker{display:none}
.chev{flex-shrink:0;margin-top:3px;font-size:9px;color:var(--muted);
  transition:transform .12s;display:inline-block}
details[open]>.summary>.chev{transform:rotate(90deg)}
.sum-body{flex:1;display:flex;align-items:flex-start;gap:8px;flex-wrap:wrap}
.sum-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;width:100%}
.fp{font-family:"SFMono-Regular",Consolas,monospace;font-size:12px;
  color:#475569;background:var(--code-bg);padding:2px 6px;
  border-radius:4px;word-break:break-word;margin-top:4px;width:100%}
.details-body{padding:0 14px 14px}
.areas-txt{font-size:12px;color:var(--muted)}

/* ── Rank circle ── */
.rnk{flex-shrink:0;width:26px;height:26px;border-radius:50%;
  background:var(--bg);border:1px solid var(--border);
  display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:700;color:var(--muted);margin-top:1px}

/* ── Callout ── */
.callout{background:#eff6ff;border-left:3px solid #3b82f6;
  padding:10px 14px;border-radius:0 6px 6px 0;
  font-size:13px;color:#1e40af;margin-bottom:14px}

/* ── Summary note line ── */
.sum-note{font-size:12px;color:var(--muted);margin-top:3px;width:100%}
"""

_CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"


def render_html(failures: list, groups: dict, area_label: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = len(failures)
    n_groups = len(groups)

    # Score distribution counts
    dist = {"crit": 0, "high": 0, "med": 0, "low": 0}
    for f in failures:
        dist[_score_cls(f.score)] += 1

    # API-escalated failures grouped by endpoint
    api_failures = [f for f in failures if f.escalated]
    ep_groups: dict[str, list] = defaultdict(list)
    for f in api_failures:
        ep_groups[f.api_endpoint or "Unknown endpoint"].append(f)

    def _ep_sort_key(kv):
        members = kv[1]
        return (-(max(m.score for m in members)), 0 if (members[0].received_code or 0) >= 500 else 1)

    sorted_ep_groups = sorted(ep_groups.items(), key=_ep_sort_key)

    # Failure groups sorted by avg score desc
    sorted_groups = sorted(
        groups.items(),
        key=lambda kv: -(sum(m.score for m in kv[1]) / len(kv[1])),
    )

    # Area summary stats
    area_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "fn": 0, "infra": 0, "known": 0})
    for f in failures:
        s = area_stats[f.area]
        s["total"] += 1
        if f.failure_type == "functional":
            s["fn"] += 1
        elif f.failure_type.startswith("infra"):
            s["infra"] += 1
        if f.defect_ids or f.is_quarantined:
            s["known"] += 1

    def _pct(n):
        return f"{round(n / total * 100)}%" if total else "0%"

    # ── Build HTML ──────────────────────────────────────────────────────────
    p = []

    p.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Failure Matrix — {_e(area_label)}</title>
<script src="{_CHART_JS_CDN}"></script>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
""")

    # ── Header ──────────────────────────────────────────────────────────────
    api_link = f'<a href="#api">API Failures ({len(api_failures)})</a>' if api_failures else ""
    p.append(f"""<header>
  <h1>Robot Framework Failure Matrix</h1>
  <p class="meta">{_e(area_label)} &bull; Generated {_e(now)}</p>
  <nav class="jump">
    <a href="#distribution">Distribution</a>
    <a href="#areas">Areas</a>
    {api_link}
    <a href="#groups">Groups ({n_groups})</a>
  </nav>
</header>
""")

    # ── Stats bar ────────────────────────────────────────────────────────────
    p.append(f"""<div class="stats">
  <div class="stat"><span class="num">{total}</span><span class="lbl">Failures</span></div>
  <div class="stat"><span class="num">{n_groups}</span><span class="lbl">Groups</span></div>
  <div class="stat crit"><span class="num">{dist['crit']}</span><span class="lbl">Critical</span></div>
  <div class="stat high"><span class="num">{dist['high']}</span><span class="lbl">High</span></div>
  <div class="stat med"><span class="num">{dist['med']}</span><span class="lbl">Medium</span></div>
  <div class="stat low"><span class="num">{dist['low']}</span><span class="lbl">Low</span></div>
</div>
""")

    # ── Score distribution ───────────────────────────────────────────────────
    chart_data = json.dumps([dist["crit"], dist["high"], dist["med"], dist["low"]])
    p.append(f"""<section id="distribution">
  <h2>Score Distribution</h2>
  <div class="chart-row">
    <div class="chart-wrap"><canvas id="scoreChart"></canvas></div>
    <div class="legend">
      <div class="legend-row">
        <span class="dot dot-crit"></span>
        <span class="leg-label">Critical &nbsp;<small>(score &ge;75)</small></span>
        <span class="leg-cnt">{dist['crit']}</span>
        <span class="leg-pct">{_pct(dist['crit'])}</span>
      </div>
      <div class="legend-row">
        <span class="dot dot-high"></span>
        <span class="leg-label">High &nbsp;<small>(55–74)</small></span>
        <span class="leg-cnt">{dist['high']}</span>
        <span class="leg-pct">{_pct(dist['high'])}</span>
      </div>
      <div class="legend-row">
        <span class="dot dot-med"></span>
        <span class="leg-label">Medium &nbsp;<small>(35–54)</small></span>
        <span class="leg-cnt">{dist['med']}</span>
        <span class="leg-pct">{_pct(dist['med'])}</span>
      </div>
      <div class="legend-row">
        <span class="dot dot-low"></span>
        <span class="leg-label">Low &nbsp;<small>(&lt;35)</small></span>
        <span class="leg-cnt">{dist['low']}</span>
        <span class="leg-pct">{_pct(dist['low'])}</span>
      </div>
    </div>
  </div>
</section>
""")

    # ── Area summary ─────────────────────────────────────────────────────────
    p.append('<section id="areas"><h2>Area Summary</h2><div class="tscroll"><table>')
    p.append("<thead><tr><th>Area</th><th>Failures</th><th>Functional</th>"
             "<th>Infra / Setup</th><th>Known Defect</th></tr></thead><tbody>")
    for area, c in sorted(area_stats.items(), key=lambda x: -x[1]["total"]):
        p.append(f"<tr><td>{_e(area)}</td><td><strong>{c['total']}</strong></td>"
                 f"<td>{c['fn']}</td><td>{c['infra']}</td><td>{c['known']}</td></tr>")
    p.append("</tbody></table></div></section>\n")

    # ── API failures ─────────────────────────────────────────────────────────
    if api_failures:
        p.append('<section id="api"><h2>API Response Failures</h2>')
        p.append('<p class="callout">These tests received a <strong>Wrong response code</strong> '
                 'from the backend. Investigate these before anything else — a broken endpoint '
                 'affects every test that touches it.</p>')
        for endpoint, ep_tests in sorted_ep_groups:
            rep = max(ep_tests, key=lambda f: f.score)
            err = rep.response_error or next((f.response_error for f in ep_tests if f.response_error), None)
            code_html = _http_code_html(rep.received_code)
            max_score = max(f.score for f in ep_tests)
            p.append(f"""<details>
  <summary class="summary">
    <span class="chev">&#9658;</span>
    <div class="sum-body">
      <div class="sum-row">
        {_badge(max_score, escalated=True)}
        {code_html}
        <code style="font-size:13px;font-weight:600;background:var(--code-bg);padding:2px 6px;border-radius:4px">{_e(endpoint)}</code>
        <span class="cnt">{len(ep_tests)} test{"s" if len(ep_tests) != 1 else ""}</span>
      </div>
      {"<p class='sum-note'>" + _e(err) + "</p>" if err else ""}
    </div>
  </summary>
  <div class="details-body">
    <div class="tscroll"><table>
      <thead><tr><th>Score</th><th>Test</th><th>Area</th></tr></thead>
      <tbody>
""")
            for f in sorted(ep_tests, key=lambda x: -x.score):
                p.append(f"<tr><td>{_badge(f.score, f.escalated)}</td>"
                         f"<td>{_e(f.name)}</td><td>{_e(f.area)}</td></tr>")
            p.append("</tbody></table></div></div></details>\n")
        p.append("</section>\n")

    # ── Failure groups ───────────────────────────────────────────────────────
    p.append('<section id="groups"><h2>Failure Groups <small style="font-size:12px;'
             'color:var(--muted);font-weight:400">ranked by average score</small></h2>')

    for rank, (fp, members) in enumerate(sorted_groups, 1):
        avg = int(sum(m.score for m in members) / len(members))
        ft = members[0].failure_type
        areas = sorted({m.area for m in members})
        areas_str = ", ".join(areas[:4]) + (f" +{len(areas)-4} more" if len(areas) > 4 else "")
        group_escalated = any(m.escalated for m in members)

        # Truncate fingerprint for display
        fp_display = (fp[:120] + "…") if len(fp) > 120 else fp

        # Representative error message (first line, stripped)
        rep = members[0]
        msg_lines = [ln.strip() for ln in (rep.message or "").splitlines() if ln.strip()]
        first_msg = msg_lines[0][:160] if msg_lines else ""

        # API endpoints for this group
        api_eps = sorted({m.api_endpoint for m in members if m.api_endpoint})

        p.append(f"""<details>
  <summary class="summary">
    <span class="rnk">{rank}</span>
    <span class="chev">&#9658;</span>
    <div class="sum-body">
      <div class="sum-row">
        {_badge(avg, group_escalated)}
        {_plbl(avg)}
        <span class="cnt">{len(members)} test{"s" if len(members) != 1 else ""}</span>
        {_chip(ft)}
        <span class="areas-txt">{_e(areas_str)}</span>
      </div>
      <div class="fp">{_e(fp_display)}</div>
      {"<p class='sum-note'>" + _e(first_msg) + "</p>" if first_msg and first_msg.lower() not in fp_display.lower() else ""}
      {"<p class='sum-note'><strong>Endpoints:</strong> " + " &bull; ".join(f"<code>{_e(ep)}</code>" for ep in api_eps) + "</p>" if api_eps else ""}
    </div>
  </summary>
  <div class="details-body">
    <div class="tscroll"><table>
      <thead><tr><th>Score</th><th>Test</th><th>Area</th><th>Suite</th><th>Priority</th><th>Severity</th><th>Defects</th></tr></thead>
      <tbody>
""")
        for m in sorted(members, key=lambda x: -x.score):
            defects = ", ".join(m.defect_ids) if m.defect_ids else ("quarantined" if m.is_quarantined else "—")
            p.append(f"<tr>"
                     f"<td>{_badge(m.score, m.escalated)}</td>"
                     f"<td>{_e(m.name)}</td>"
                     f"<td>{_e(m.area)}</td>"
                     f"<td>{_e(m.suite)}</td>"
                     f"<td>{_e(m.priority)}</td>"
                     f"<td>{_e(m.severity)}</td>"
                     f"<td>{_e(defects)}</td>"
                     f"</tr>")
        p.append("</tbody></table></div></div></details>\n")

    p.append("</section>\n")

    # ── Close + Chart.js init ────────────────────────────────────────────────
    p.append(f"""</div>
<script>
(function(){{
  var ctx = document.getElementById('scoreChart').getContext('2d');
  new Chart(ctx, {{
    type: 'doughnut',
    data: {{
      labels: ['Critical','High','Medium','Low'],
      datasets: [{{
        data: {chart_data},
        backgroundColor: ['#dc2626','#ea580c','#b45309','#16a34a'],
        borderWidth: 3,
        borderColor: '#fff',
        hoverOffset: 6
      }}]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: true,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            label: function(ctx) {{
              var total = ctx.dataset.data.reduce(function(a,b){{return a+b}}, 0);
              var pct = total ? Math.round(ctx.parsed / total * 100) : 0;
              return ' ' + ctx.label + ': ' + ctx.parsed + ' (' + pct + '%)';
            }}
          }}
        }}
      }},
      cutout: '62%'
    }}
  }});
}})();
</script>
</body>
</html>
""")

    return "".join(p)

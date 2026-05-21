"""Render a dark-theme HTML report from summary.json + transcript.json."""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _fmt_ts(seconds: float | int | str) -> str:
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return str(seconds)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def _esc(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=False)


CSS = """
:root {
  --bg: #09090b;
  --surface: #111113;
  --surface-2: #18181b;
  --border: rgba(255, 255, 255, 0.08);
  --text: #fafafa;
  --muted: #a1a1aa;
  --dim: #71717a;
  --accent: #38bdf8;
  --accent-dim: rgba(56, 189, 248, 0.12);
  --mono: ui-monospace, "SF Mono", "Cascadia Code", Menlo, monospace;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text); }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  line-height: 1.7; padding: 40px 0 56px;
  background-image: radial-gradient(ellipse 80% 50% at 50% -20%, rgba(56,189,248,0.06), transparent);
}
.container { max-width: 780px; margin: 0 auto; padding: 0 28px; }
.badge {
  display: inline-block; font-family: var(--mono); font-size: 11px; font-weight: 500;
  letter-spacing: 0.06em; text-transform: uppercase; color: var(--accent);
  padding: 5px 10px; border-radius: 6px;
  background: var(--accent-dim); border: 1px solid rgba(56,189,248,0.2);
}
h1 { font-size: 24px; font-weight: 600; margin: 14px 0 6px; line-height: 1.35; letter-spacing: -0.02em; }
h2 {
  font-size: 11px; font-weight: 600; margin: 36px 0 14px;
  color: var(--dim); text-transform: uppercase; letter-spacing: 0.14em;
  border: none; padding: 0;
}
.meta-row {
  display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 8px;
  font-size: 12px; color: var(--muted);
}
.meta-row span {
  padding: 4px 10px; border-radius: 6px;
  background: var(--surface); border: 1px solid var(--border);
}
.meta-row a { color: var(--accent); text-decoration: none; }
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 20px 22px; margin: 0;
}
.card + .card { margin-top: 12px; }
.purpose { border-color: rgba(56,189,248,0.18); font-size: 15px; color: #e4e4e7; }
ul, ol { padding-left: 22px; margin: 0; }
li { margin: 6px 0; color: #d4d4d8; }
.outline-track { position: relative; padding-left: 20px; }
.outline-track::before {
  content: ""; position: absolute; left: 5px; top: 8px; bottom: 8px;
  width: 1px; background: linear-gradient(var(--border), transparent);
}
.outline-node { position: relative; padding: 14px 0 14px 18px; }
.outline-node:not(:last-child) { border-bottom: 1px solid var(--border); }
.outline-marker {
  position: absolute; left: -20px; top: 20px;
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--bg); border: 1.5px solid var(--accent);
}
.ts {
  font-family: var(--mono); font-size: 12px; color: var(--accent);
  display: block; margin-bottom: 4px;
}
.outline-title { font-weight: 600; font-size: 14px; color: var(--text); }
.outline-abs { color: var(--muted); font-size: 13px; margin-top: 3px; line-height: 1.55; }
.concepts { display: flex; flex-wrap: wrap; gap: 8px; }
.tag {
  font-size: 12px; padding: 6px 12px; border-radius: 8px;
  background: var(--surface-2); border: 1px solid var(--border); color: #d4d4d8;
}
.tag b { color: var(--accent); font-weight: 600; margin-right: 6px; }
.transcript-toggle, .section-notes-toggle {
  cursor: pointer; user-select: none; color: var(--accent);
  font-size: 13px; font-family: var(--mono);
}
.transcript-toggle::before, .section-notes-toggle::before { content: "▸ "; }
.transcript-toggle.open::before, .section-notes-toggle.open::before { content: "▾ "; }
.transcript {
  display: none; margin-top: 14px; max-height: 480px; overflow-y: auto;
  background: var(--surface-2); border-radius: 8px; padding: 14px 16px;
  font-size: 13px; line-height: 1.65; border: 1px solid var(--border);
}
.transcript.open { display: block; }
.transcript .seg { padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
.transcript .seg:last-child { border-bottom: none; }
.transcript .seg .ts { display: inline; min-width: 64px; margin-right: 8px; color: var(--dim); }
footer {
  color: var(--dim); font-size: 11px; text-align: center; margin-top: 48px;
  font-family: var(--mono); letter-spacing: 0.02em;
}
.section-notes { display: none; margin-top: 14px; }
.section-notes.open { display: block; }
.section-note {
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px 16px; margin: 8px 0;
}
.section-note .ts { font-size: 11px; color: var(--dim); }
.section-note h4 { margin: 0 0 8px; font-size: 14px; font-weight: 600; }
.section-note ul { font-size: 13px; }
"""

JS = """
document.querySelectorAll('.transcript-toggle, .section-notes-toggle').forEach(function(btn){
  btn.addEventListener('click', function(){
    var target = document.getElementById(btn.dataset.target);
    if (!target) return;
    target.classList.toggle('open');
    btn.classList.toggle('open');
  });
});
"""


def render_html(summary_json_path: Path, transcript_json_path: Path, output_path: Path, meta: dict | None = None) -> Path:
    summary_json_path = Path(summary_json_path)
    transcript_json_path = Path(transcript_json_path)
    output_path = Path(output_path)
    with summary_json_path.open("r", encoding="utf-8") as f:
        summary = json.load(f)
    with transcript_json_path.open("r", encoding="utf-8") as f:
        transcript = json.load(f)

    meta = meta or summary.get("meta", {}) or {}
    final = summary.get("final", {}) or {}
    section_notes = summary.get("section_notes", []) or []
    segments = transcript.get("segments", []) or []

    course_title = meta.get("course_title") or "未知课程"
    sub_title = meta.get("sub_title") or "课程录像"
    lecturer = meta.get("lecturer_name") or meta.get("lecturer") or ""
    course_code = meta.get("course_code") or ""
    room_name = meta.get("room_name") or ""
    start_at = meta.get("start_at")
    if start_at:
        try:
            class_time = datetime.fromtimestamp(int(start_at)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            class_time = ""
    else:
        class_time = ""
    duration = transcript.get("duration") or meta.get("duration")
    duration_str = _fmt_ts(duration) if duration else "—"
    source_url = meta.get("source_url")

    parts: list[str] = []
    parts.append('<div class="container">')
    parts.append('<span class="badge">Pipeline Digest</span>')
    parts.append(f'<h1>{_esc(course_title)} · {_esc(sub_title)}</h1>')

    meta_bits = []
    if course_code:
        meta_bits.append(f"<span>{_esc(course_code)}</span>")
    if lecturer:
        meta_bits.append(f"<span>{_esc(lecturer)}</span>")
    if class_time:
        meta_bits.append(f"<span>{_esc(class_time)}</span>")
    if room_name:
        meta_bits.append(f"<span>{_esc(room_name)}</span>")
    meta_bits.append(f"<span>{_esc(duration_str)}</span>")
    if source_url:
        meta_bits.append(f'<span><a href="{_esc(source_url)}" target="_blank" rel="noopener">source ↗</a></span>')
    if meta_bits:
        parts.append(f'<div class="meta-row">{"".join(meta_bits)}</div>')

    if final.get("core_purpose"):
        parts.append('<h2>课程目的</h2>')
        parts.append(f'<div class="card purpose">{_esc(final["core_purpose"])}</div>')

    if final.get("overall_summary"):
        parts.append('<h2>整体概述</h2>')
        parts.append(f'<div class="card">{_esc(final["overall_summary"])}</div>')

    outline = final.get("chapter_outline") or []
    if outline:
        parts.append('<h2>章节大纲</h2><div class="card"><div class="outline-track">')
        for item in outline:
            ts = _esc(item.get("ts", ""))
            title = _esc(item.get("title", ""))
            abstract = _esc(item.get("abstract", ""))
            parts.append(
                '<div class="outline-node"><div class="outline-marker"></div>'
                f'<span class="ts">{ts}</span>'
                f'<div class="outline-title">{title}</div>'
                f'<div class="outline-abs">{abstract}</div></div>'
            )
        parts.append('</div></div>')

    concepts = final.get("key_concepts") or []
    if concepts:
        parts.append('<h2>关键概念</h2><div class="card"><div class="concepts">')
        for c in concepts:
            term = _esc(c.get("term", "")) if isinstance(c, dict) else _esc(c)
            expl = _esc(c.get("explanation", "")) if isinstance(c, dict) else ""
            parts.append(f'<div class="tag"><b>{term}</b>{expl}</div>')
        parts.append('</div></div>')

    examples = final.get("key_examples") or []
    if examples:
        parts.append('<h2>例题</h2><div class="card"><ul>')
        for ex in examples:
            parts.append(f'<li>{_esc(ex)}</li>')
        parts.append('</ul></div>')

    questions = final.get("self_check_questions") or []
    if questions:
        parts.append('<h2>自测</h2><div class="card"><ol>')
        for q in questions:
            parts.append(f'<li>{_esc(q)}</li>')
        parts.append('</ol></div>')

    notes_lec = final.get("notes_to_lecturer") or []
    if notes_lec:
        parts.append('<h2>Notes</h2><div class="card"><ul>')
        for n in notes_lec:
            parts.append(f'<li>{_esc(n)}</li>')
        parts.append('</ul></div>')

    if section_notes:
        parts.append('<h2>分段笔记</h2><div class="card">')
        parts.append(
            '<span class="section-notes-toggle" data-target="sec-notes">展开 · '
            + str(len(section_notes))
            + " 段</span>"
        )
        parts.append('<div id="sec-notes" class="section-notes">')
        for sn in section_notes:
            ts_start = _fmt_ts(sn.get("_chunk_start", 0))
            ts_end = _fmt_ts(sn.get("_chunk_end", 0))
            stitle = _esc(sn.get("section_title", ""))
            parts.append('<div class="section-note">')
            parts.append(f'<div class="ts">{ts_start} – {ts_end}</div>')
            parts.append(f'<h4>{stitle}</h4>')
            bullets = sn.get("summary_bullets") or []
            if bullets:
                parts.append('<ul>')
                for b in bullets:
                    parts.append(f'<li>{_esc(b)}</li>')
                parts.append('</ul>')
            cs = sn.get("concepts") or []
            if cs:
                parts.append('<div class="concepts">')
                for c in cs:
                    parts.append(f'<span class="tag">{_esc(c)}</span>')
                parts.append('</div>')
            parts.append('</div>')
        parts.append('</div></div>')

    parts.append('<h2>完整转录</h2><div class="card">')
    parts.append(
        '<span class="transcript-toggle" data-target="tx">展开 · '
        + str(len(segments))
        + " 段</span>"
    )
    parts.append('<div id="tx" class="transcript">')
    for seg in segments:
        ts = _esc(_fmt_ts(seg.get("start", 0)))
        text = _esc(seg.get("text", ""))
        parts.append(f'<div class="seg"><span class="ts">{ts}</span>{text}</div>')
    parts.append('</div></div>')

    parts.append('<footer>')
    parts.append(
        f'{datetime.now().strftime("%Y-%m-%d %H:%M")} · '
        f'whisper {_esc(transcript.get("model", "?"))} · '
        f'{_esc(transcript.get("device", "?"))} · deepseek'
    )
    parts.append('</footer>')
    parts.append('</div>')

    body = "\n".join(parts)
    page = (
        f"<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(course_title)} · {_esc(sub_title)}</title>"
        f"<style>{CSS}</style></head>"
        f"<body>{body}<script>{JS}</script></body></html>"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return output_path


if __name__ == "__main__":
    import sys
    render_html(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))

"""Render a dark-theme HTML report from summary.json + transcript.json.

Visual language reuses the bilibili-summarizer palette:
  --bg: #0f0f13; --card: #1a1a24; --border: #2a2a3a;
  --text: #e0e0e8; --text-secondary: #a0a0b4;
  --accent: #6c8cff; --accent2: #ff6b9d; --highlight: #ffd166;
"""
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
  --bg: #0f0f13;
  --card: #1a1a24;
  --card-2: #20202c;
  --border: #2a2a3a;
  --text: #e0e0e8;
  --text-secondary: #a0a0b4;
  --accent: #6c8cff;
  --accent2: #ff6b9d;
  --highlight: #ffd166;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text); }
body { font-family: system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; line-height: 1.75; padding: 32px 0; }
.container { max-width: 860px; margin: 0 auto; padding: 0 24px; }
.badge { display: inline-block; background: linear-gradient(135deg, var(--accent), var(--accent2)); color: white; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 500; letter-spacing: 0.5px; }
h1 { font-size: 28px; margin: 12px 0 4px; line-height: 1.3; }
h2 { font-size: 18px; margin: 28px 0 12px; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 6px; }
h3 { font-size: 15px; margin: 18px 0 8px; color: var(--text-secondary); font-weight: 600; }
.meta-row { color: var(--text-secondary); font-size: 13px; margin: 8px 0 16px; }
.meta-row span { margin-right: 16px; }
.meta-row a { color: var(--accent); text-decoration: none; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 18px 22px; margin: 12px 0; }
.purpose { background: linear-gradient(135deg, rgba(108,140,255,0.08), rgba(255,107,157,0.05)); border-color: rgba(108,140,255,0.3); font-size: 16px; }
ul, ol { padding-left: 24px; }
li { margin: 5px 0; }
.outline-item { display: grid; grid-template-columns: 70px 1fr; gap: 12px; padding: 10px 0; border-bottom: 1px dashed var(--border); align-items: start; }
.outline-item:last-child { border-bottom: none; }
.ts { color: var(--highlight); font-family: ui-monospace, "Cascadia Code", Menlo, monospace; font-size: 13px; padding-top: 2px; }
.outline-title { color: var(--text); font-weight: 600; }
.outline-abs { color: var(--text-secondary); font-size: 14px; margin-top: 2px; }
.concepts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.tag { background: var(--card-2); border: 1px solid var(--border); border-radius: 6px; padding: 4px 10px; font-size: 13px; }
.tag b { color: var(--accent); margin-right: 6px; }
.transcript-toggle { cursor: pointer; user-select: none; color: var(--accent); font-size: 14px; }
.transcript-toggle::before { content: "▶  "; }
.transcript-toggle.open::before { content: "▼  "; }
.transcript { display: none; margin-top: 12px; max-height: 600px; overflow-y: auto; background: var(--card-2); border-radius: 8px; padding: 12px 16px; font-size: 13px; line-height: 1.7; }
.transcript.open { display: block; }
.transcript .seg { padding: 4px 0; border-bottom: 1px dotted #232333; }
.transcript .seg:last-child { border-bottom: none; }
.transcript .seg .ts { display: inline-block; min-width: 70px; }
footer { color: var(--text-secondary); font-size: 12px; text-align: center; margin-top: 40px; opacity: 0.7; }
.section-notes-toggle { color: var(--accent); cursor: pointer; user-select: none; font-size: 14px; }
.section-notes-toggle::before { content: "▶  "; }
.section-notes-toggle.open::before { content: "▼  "; }
.section-notes { display: none; margin-top: 12px; }
.section-notes.open { display: block; }
.section-note { background: var(--card-2); border-radius: 8px; padding: 12px 16px; margin: 8px 0; }
.section-note .ts { font-size: 12px; }
.section-note h4 { margin: 0 0 6px; font-size: 14px; color: var(--text); }
.section-note ul { margin: 4px 0; font-size: 13px; }
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

    # Header
    course_title = meta.get("course_title") or "未知课程"
    sub_title = meta.get("sub_title") or "课程录像"
    lecturer = meta.get("lecturer_name") or meta.get("lecturer") or "—"
    course_code = meta.get("course_code") or ""
    room_name = meta.get("room_name") or ""
    start_at = meta.get("start_at")
    if start_at:
        try:
            start_dt = datetime.fromtimestamp(int(start_at))
            class_time = start_dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            class_time = ""
    else:
        class_time = ""
    duration = transcript.get("duration") or meta.get("duration")
    duration_str = _fmt_ts(duration) if duration else "—"
    source_url = meta.get("source_url")

    # Body parts
    parts: list[str] = []
    parts.append('<div class="container">')
    parts.append('<span class="badge">Fudan Pipeline Digest</span>')
    parts.append(f'<h1>{_esc(course_title)} · {_esc(sub_title)}</h1>')

    meta_bits = []
    if course_code:
        meta_bits.append(f"<span>课号 {_esc(course_code)}</span>")
    meta_bits.append(f"<span>讲师 {_esc(lecturer)}</span>")
    if class_time:
        meta_bits.append(f"<span>上课 {_esc(class_time)}</span>")
    if room_name:
        meta_bits.append(f"<span>教室 {_esc(room_name)}</span>")
    meta_bits.append(f"<span>时长 {_esc(duration_str)}</span>")
    if source_url:
        meta_bits.append(f'<span><a href="{_esc(source_url)}" target="_blank">原页面 ↗</a></span>')
    parts.append(f'<div class="meta-row">{"".join(meta_bits)}</div>')

    if final.get("core_purpose"):
        parts.append('<h2>课程目的</h2>')
        parts.append(f'<div class="card purpose">{_esc(final["core_purpose"])}</div>')

    if final.get("overall_summary"):
        parts.append('<h2>整体概述</h2>')
        parts.append(f'<div class="card">{_esc(final["overall_summary"])}</div>')

    outline = final.get("chapter_outline") or []
    if outline:
        parts.append('<h2>章节大纲</h2><div class="card">')
        for item in outline:
            ts = _esc(item.get("ts", ""))
            title = _esc(item.get("title", ""))
            abstract = _esc(item.get("abstract", ""))
            parts.append(
                f'<div class="outline-item"><div class="ts">{ts}</div>'
                f'<div><div class="outline-title">{title}</div>'
                f'<div class="outline-abs">{abstract}</div></div></div>'
            )
        parts.append('</div>')

    concepts = final.get("key_concepts") or []
    if concepts:
        parts.append('<h2>关键术语 / 概念</h2><div class="card"><div class="concepts">')
        for c in concepts:
            term = _esc(c.get("term", "")) if isinstance(c, dict) else _esc(c)
            expl = _esc(c.get("explanation", "")) if isinstance(c, dict) else ""
            parts.append(f'<div class="tag"><b>{term}</b>{expl}</div>')
        parts.append('</div></div>')

    examples = final.get("key_examples") or []
    if examples:
        parts.append('<h2>关键例子 / 应用</h2><div class="card"><ul>')
        for ex in examples:
            parts.append(f'<li>{_esc(ex)}</li>')
        parts.append('</ul></div>')

    questions = final.get("self_check_questions") or []
    if questions:
        parts.append('<h2>自测问题</h2><div class="card"><ol>')
        for q in questions:
            parts.append(f'<li>{_esc(q)}</li>')
        parts.append('</ol></div>')

    notes_lec = final.get("notes_to_lecturer") or []
    if notes_lec:
        parts.append('<h2>讲授观察</h2><div class="card"><ul>')
        for n in notes_lec:
            parts.append(f'<li>{_esc(n)}</li>')
        parts.append('</ul></div>')

    # Section notes (collapsible)
    if section_notes:
        parts.append('<h2>分段笔记</h2><div class="card">')
        parts.append('<span class="section-notes-toggle" data-target="sec-notes">展开 / 折叠 共 ' + str(len(section_notes)) + ' 段</span>')
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

    # Full transcript (collapsible)
    parts.append('<h2>完整转录</h2><div class="card">')
    parts.append('<span class="transcript-toggle" data-target="tx">展开 / 折叠 共 ' + str(len(segments)) + ' 段</span>')
    parts.append('<div id="tx" class="transcript">')
    for seg in segments:
        ts = _esc(_fmt_ts(seg.get("start", 0)))
        text = _esc(seg.get("text", ""))
        parts.append(f'<div class="seg"><span class="ts">[{ts}]</span> {text}</div>')
    parts.append('</div></div>')

    parts.append('<footer>')
    parts.append(
        f'生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")} · '
        f'whisper {_esc(transcript.get("model", "?"))} on {_esc(transcript.get("device", "?"))} '
        f'· 总结 DeepSeek'
    )
    parts.append('</footer>')
    parts.append('</div>')

    body = "\n".join(parts)
    page = (
        f"<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(course_title)} · {_esc(sub_title)} · 总结</title>"
        f"<style>{CSS}</style></head>"
        f"<body>{body}<script>{JS}</script></body></html>"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return output_path


if __name__ == "__main__":
    import sys
    sj = Path(sys.argv[1])
    tj = Path(sys.argv[2])
    out = Path(sys.argv[3])
    render_html(sj, tj, out)

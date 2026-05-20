"""DeepSeek summarization.

Strategy: map-reduce.

1. **Map**: split the transcript into ~8-minute time windows (~1500-2500 tokens
   each). Each chunk is summarized into a structured local-section: bullets +
   key concepts + open questions.

2. **Reduce**: feed all local-section summaries into one final call which
   produces:
     - 课程目的（学这节课的核心 take-away）
     - 章节大纲（带时间戳的目录）
     - 关键术语 / 公式 / 命名实体
     - 与课程整体的关联（如果上下文充足）
     - 适合复习的 3-5 个自测问题

All API calls use the OpenAI-compatible DeepSeek endpoint.
"""
from __future__ import annotations

import json
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

from .config import Config, load_config


@dataclass
class Chunk:
    start: float
    end: float
    text: str


def _make_chunks(segments: list[dict], window_seconds: float = 480.0) -> list[Chunk]:
    chunks: list[Chunk] = []
    if not segments:
        return chunks
    cur_start = segments[0]["start"]
    cur_end = cur_start
    cur_buf: list[str] = []
    for seg in segments:
        if seg["start"] - cur_start >= window_seconds and cur_buf:
            chunks.append(Chunk(start=cur_start, end=cur_end, text="\n".join(cur_buf)))
            cur_start = seg["start"]
            cur_buf = []
        ts = f"[{int(seg['start']//60):02d}:{int(seg['start']%60):02d}] "
        cur_buf.append(ts + seg["text"].strip())
        cur_end = seg["end"]
    if cur_buf:
        chunks.append(Chunk(start=cur_start, end=cur_end, text="\n".join(cur_buf)))
    return chunks


def _fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _client(cfg: Config) -> OpenAI:
    # trust_env=False: don't let Clash/system proxy hijack api.deepseek.com.
    # Long timeouts: DeepSeek can be slow to connect from CN networks; a 2.5h
    # lecture map chunk can also take a while to generate.
    timeout = httpx.Timeout(
        connect=float(cfg.get("deepseek_connect_timeout", 120)),
        read=float(cfg.get("deepseek_read_timeout", 600)),
        write=60.0,
        pool=60.0,
    )
    http_client = httpx.Client(trust_env=False, timeout=timeout)
    return OpenAI(
        api_key=cfg["deepseek_api_key"],
        base_url=cfg["deepseek_base_url"],
        timeout=timeout,
        http_client=http_client,
        max_retries=0,  # we implement our own retry loop with checkpointing
    )


def _chat_with_retry(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.3,
    max_attempts: int = 8,
) -> str:
    """Call DeepSeek with exponential backoff on transient network errors."""
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            rsp = client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                temperature=temperature,
                messages=messages,
            )
            return rsp.choices[0].message.content or ""
        except (APITimeoutError, APIConnectionError, RateLimitError, httpx.TimeoutException) as e:
            last_err = e
            wait = min(2 ** attempt + 1, 60)
            print(
                f"[summarize]   API error ({type(e).__name__}): {e} — "
                f"retry {attempt + 1}/{max_attempts} in {wait}s",
                flush=True,
            )
            time.sleep(wait)
        except Exception as e:
            # Non-transient errors (bad model name, auth, etc.) — fail fast.
            raise RuntimeError(f"DeepSeek API call failed: {e}") from e
    raise RuntimeError(
        f"DeepSeek API still failing after {max_attempts} attempts: {last_err}"
    ) from last_err


_MAP_SYSTEM = textwrap.dedent("""
    你是一名严谨的课程笔记助手。我会贴一段大学课程录像的语音转录（含时间戳）。
    内容可能含 ASR 错误（同音字、术语错写），请基于上下文谨慎纠正明显错误，但不要改变原意。

    请输出 JSON，字段如下：
    {
      "section_title": "本段最贴切的小节标题（≤20 字）",
      "summary_bullets": ["3-6 条要点，每条 1 句话，按讲授顺序"],
      "concepts": ["本段出现的关键术语 / 公式名 / 模型名（短词组）"],
      "examples": ["老师举的例子 / 习题 / 应用场景（可选，没有就空数组）"],
      "open_questions": ["本段未交代清楚或留作思考的点（可选）"]
    }

    只输出 JSON，不要 Markdown 代码块包装。
""").strip()


_REDUCE_SYSTEM = textwrap.dedent("""
    你是一名课程总结专家。我会贴一节大学课程录像的"分段笔记"（每段含 section_title /
    summary_bullets / concepts 等），以及课程的元信息。

    请输出 JSON，字段如下：
    {
      "core_purpose": "这节课老师想让学生达到的 1-2 句核心目的，直击 take-away",
      "overall_summary": "180-260 字的整体概述，要写得像写给同学的复习要点",
      "chapter_outline": [
        { "ts": "MM:SS", "title": "章节标题", "abstract": "1-2 句要点" }
      ],
      "key_concepts": [
        { "term": "术语 / 公式 / 模型", "explanation": "30 字以内的本课语境下的释义" }
      ],
      "key_examples": ["重要例题或应用场景（1-2 句一条）"],
      "self_check_questions": ["3-5 道用于自测的复习题（开放式）"],
      "notes_to_lecturer": ["可选，对老师讲授节奏 / 难点的观察"]
    }

    要求：
    - 输出语言：中文（除非术语本身是英文）
    - chapter_outline 至少 4 段，最多 12 段，按时间顺序
    - 不要复述 ASR 噪音，遇到明显错字可基于上下文重写
    - 只输出 JSON，无 Markdown 包装
""").strip()


def _parse_json_obj(text: str) -> dict:
    """Tolerant JSON parser that handles ```json``` fences and stray prose."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.lstrip().startswith("json"):
            s = s.lstrip()[4:]
    # Find first { and last }
    a = s.find("{")
    b = s.rfind("}")
    if a == -1 or b == -1:
        raise ValueError(f"no JSON object found in:\n{text[:400]}")
    return json.loads(s[a : b + 1])


def summarize_transcript(
    transcript_json_path: Path,
    *,
    cfg: Config | None = None,
    meta: dict | None = None,
    output_dir: Path | None = None,
) -> dict:
    cfg = cfg or load_config()
    transcript_json_path = Path(transcript_json_path)
    output_dir = Path(output_dir or transcript_json_path.parent)

    with transcript_json_path.open("r", encoding="utf-8") as f:
        tr = json.load(f)
    segments = tr["segments"]
    chunks = _make_chunks(segments, window_seconds=480.0)
    print(f"[summarize] {len(segments)} segments → {len(chunks)} chunks", flush=True)

    client = _client(cfg)
    chat_model = cfg["deepseek_summary_model"]

    section_notes_path = output_dir / "section_notes.json"
    section_notes: list[dict] = []
    if section_notes_path.exists():
        try:
            section_notes = json.loads(section_notes_path.read_text(encoding="utf-8"))
            print(
                f"[summarize] resuming from {section_notes_path.name} "
                f"({len(section_notes)}/{len(chunks)} chunks done)",
                flush=True,
            )
        except Exception as e:
            print(f"[summarize] could not load section_notes.json: {e}; starting fresh", flush=True)
            section_notes = []

    start_idx = len(section_notes)
    for i, ch in enumerate(chunks[start_idx:], start=start_idx):
        print(f"[summarize] chunk {i+1}/{len(chunks)}  [{_fmt_ts(ch.start)}-{_fmt_ts(ch.end)}]", flush=True)
        raw = _chat_with_retry(
            client,
            model=chat_model,
            messages=[
                {"role": "system", "content": _MAP_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"时间段：{_fmt_ts(ch.start)} - {_fmt_ts(ch.end)}\n\n"
                        f"语音转录:\n{ch.text}"
                    ),
                },
            ],
        )
        try:
            payload = _parse_json_obj(raw)
        except Exception as e:
            print(f"[summarize]   parse failed: {e}; saving raw", flush=True)
            payload = {"_raw": raw, "_error": str(e)}
        payload["_chunk_start"] = ch.start
        payload["_chunk_end"] = ch.end
        section_notes.append(payload)
        # Checkpoint after every chunk so a midnight timeout doesn't waste progress.
        section_notes_path.write_text(
            json.dumps(section_notes, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print(f"[summarize] reducing {len(section_notes)} section notes → final summary", flush=True)
    reduce_input = {
        "course_meta": meta or {},
        "section_notes": section_notes,
        "duration_seconds": tr.get("duration"),
    }
    reduce_payload = json.dumps(reduce_input, ensure_ascii=False)
    print(
        f"[summarize] calling DeepSeek reduce "
        f"({len(reduce_payload)/1024:.1f} KB input, {len(section_notes)} sections → final JSON; "
        f"may take 2-10 min on slow networks, please wait...)",
        flush=True,
    )
    t_reduce = time.time()
    raw2 = _chat_with_retry(
        client,
        model=chat_model,
        messages=[
            {"role": "system", "content": _REDUCE_SYSTEM},
            {"role": "user", "content": reduce_payload},
        ],
    )
    print(
        f"[summarize] reduce finished in {time.time()-t_reduce:.1f}s "
        f"({len(raw2)} chars returned)",
        flush=True,
    )
    try:
        final = _parse_json_obj(raw2)
    except Exception as e:
        print(f"[summarize] final reduce parse failed: {e}; saving raw", flush=True)
        final = {"_raw": raw2, "_error": str(e)}

    out = {
        "meta": meta or {},
        "transcript_path": str(transcript_json_path),
        "section_notes": section_notes,
        "final": final,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out


if __name__ == "__main__":
    import sys
    transcript = Path(sys.argv[1])
    summarize_transcript(transcript)

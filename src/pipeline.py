"""End-to-end pipeline: livingroom URL → HTML summary.

Usage:
    python -m src.pipeline <livingroom_url>
    python -m src.pipeline --course-id COURSE_ID --sub-id SUB_ID
    python -m src.pipeline --course-id COURSE_ID --all

Flags:
    --skip-cookies    don't refresh cookies (use cached cookie-header.txt)
    --skip-download   reuse existing audio.opus if present
    --skip-transcribe reuse existing transcript.json if present
    --skip-summarize  reuse existing summary.json if present
    --audio-format    opus (default) | wav
    --output-dir PATH override output dir
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from . import auth, browser_signed_url, download, icourse_api, render_html, summarize, transcribe
from .config import load_config


def _safe_slug(name: str) -> str:
    import re
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]", "_", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:120]


def _select_meta(sub_info: dict[str, Any], course_detail: dict[str, Any], course_id: str, sub_id: str, source_url: str) -> dict[str, Any]:
    sub = sub_info.get("data", {}) or {}
    course = (course_detail or {}).get("data", {}) or {}
    return {
        "course_id": course_id,
        "sub_id": sub_id,
        "course_title": sub.get("course_title") or course.get("title"),
        "sub_title": sub.get("sub_title"),
        "lecturer_name": sub.get("lecturer_name"),
        "course_code": course.get("course_code"),
        "room_name": sub.get("room_name"),
        "start_at": sub.get("start_at"),
        "end_at": sub.get("end_at"),
        "duration": sub.get("duration"),
        "structure_name": course.get("structure_name"),
        "term_name": course.get("term_name"),
        "source_url": source_url,
    }


def run_one(
    course_id: str,
    sub_id: str,
    tenant_code: str = "222",
    *,
    skip_cookies: bool = False,
    skip_download: bool = False,
    skip_transcribe: bool = False,
    skip_summarize: bool = False,
    audio_format: str = "opus",
    output_dir: Path | None = None,
    keep_video: bool = False,
) -> Path:
    cfg = load_config()
    t_overall = time.time()

    if not skip_cookies:
        print("[pipeline] refreshing cookies from Chrome via CDP...", flush=True)
        info = auth.refresh_cookies(cfg)
        print(f"[pipeline]   {info['fudan_cookies']} fudan cookies across {len(info['domains'])} domains", flush=True)

    print(f"[pipeline] fetching course / sub metadata course_id={course_id} sub_id={sub_id}", flush=True)
    sub_info = icourse_api.get_sub_info(course_id, sub_id, cfg)
    course_detail = icourse_api.get_course_detail(course_id, cfg)

    source_url = f"https://icourse.fudan.edu.cn/livingroom?course_id={course_id}&sub_id={sub_id}&tenant_code={tenant_code}"
    meta = _select_meta(sub_info, course_detail, course_id, sub_id, source_url)
    print(f"[pipeline] {meta['course_title']} · {meta['sub_title']} · {meta['lecturer_name']}", flush=True)

    course_slug = _safe_slug(meta.get("course_title") or f"course_{course_id}")
    sub_slug = _safe_slug(meta.get("sub_title") or f"sub_{sub_id}")
    out_root = Path(output_dir) if output_dir else cfg.output_dir / course_slug
    out_dir = out_root / sub_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    audio_ext = ".opus" if audio_format == "opus" else ".wav"
    audio_path = out_dir / f"audio{audio_ext}"

    if skip_download and audio_path.exists():
        print(f"[pipeline] skip-download: reusing {audio_path}", flush=True)
    else:
        print("[pipeline] resolving fresh signed video URL via Chrome CDP...", flush=True)
        signed = browser_signed_url.fetch_signed_video_url(cfg, course_id, sub_id, tenant_code)
        print(f"[pipeline] video src = {signed['src'][:100]}...", flush=True)
        codec = "libopus" if audio_format == "opus" else "pcm_s16le"
        download.extract_audio(
            signed_url=signed["src"],
            referer=signed["referer"],
            output_path=audio_path,
            cfg=cfg,
            audio_codec=codec,
            keep_video=keep_video,
        )

    if skip_transcribe and (out_dir / "transcript.json").exists():
        print(f"[pipeline] skip-transcribe: reusing {out_dir / 'transcript.json'}", flush=True)
    else:
        transcribe.transcribe_audio(audio_path, cfg=cfg, output_dir=out_dir)

    if skip_summarize and (out_dir / "summary.json").exists():
        print(f"[pipeline] skip-summarize: reusing {out_dir / 'summary.json'}", flush=True)
    else:
        summarize.summarize_transcript(out_dir / "transcript.json", cfg=cfg, meta=meta, output_dir=out_dir)

    html_path = out_dir / "summary.html"
    render_html.render_html(out_dir / "summary.json", out_dir / "transcript.json", html_path, meta=meta)

    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    elapsed = time.time() - t_overall
    print(f"[pipeline] DONE in {elapsed:.1f}s → {html_path}", flush=True)
    return html_path


def run_course(course_id: str, tenant_code: str = "222", **kwargs) -> list[Path]:
    cfg = load_config()
    if not kwargs.get("skip_cookies", False):
        auth.refresh_cookies(cfg)
        kwargs["skip_cookies"] = True

    items = icourse_api.get_catalogue(course_id, cfg)
    print(f"[pipeline] catalogue: {len(items)} recordings; selecting available playbacks", flush=True)
    out_paths: list[Path] = []
    for it in items:
        if it.get("status") != "6":
            print(f"[pipeline]  skip sub_id={it['sub_id']} ({it['title']}): no playback yet", flush=True)
            continue
        sub_id = it["sub_id"]
        try:
            p = run_one(course_id, sub_id, tenant_code, **kwargs)
            out_paths.append(p)
        except Exception as e:
            print(f"[pipeline]  sub_id={sub_id} failed: {e}", flush=True)
    return out_paths


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("livingroom_url", nargs="?", help="https://icourse.fudan.edu.cn/livingroom?course_id=...&sub_id=...")
    ap.add_argument("--course-id", help="run a specific course_id (with --sub-id or --all)")
    ap.add_argument("--sub-id", help="specific sub_id")
    ap.add_argument("--all", action="store_true", help="run every playback in the course")
    ap.add_argument("--tenant-code", default="222")
    ap.add_argument("--skip-cookies", action="store_true")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--skip-transcribe", action="store_true")
    ap.add_argument("--skip-summarize", action="store_true")
    ap.add_argument("--audio-format", choices=["opus", "wav"], default="opus")
    ap.add_argument("--keep-video", action="store_true", help="keep the downloaded MP4 next to audio.opus")
    ap.add_argument("--output-dir", type=Path)
    args = ap.parse_args()

    kwargs = dict(
        skip_cookies=args.skip_cookies,
        skip_download=args.skip_download,
        skip_transcribe=args.skip_transcribe,
        skip_summarize=args.skip_summarize,
        audio_format=args.audio_format,
        keep_video=args.keep_video,
        output_dir=args.output_dir,
    )

    if args.livingroom_url:
        ids = icourse_api.parse_livingroom_url(args.livingroom_url)
        run_one(
            ids["course_id"],
            ids["sub_id"],
            tenant_code=ids.get("tenant_code", args.tenant_code),
            **kwargs,
        )
    elif args.course_id and args.all:
        run_course(args.course_id, tenant_code=args.tenant_code, **kwargs)
    elif args.course_id and args.sub_id:
        run_one(args.course_id, args.sub_id, tenant_code=args.tenant_code, **kwargs)
    else:
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

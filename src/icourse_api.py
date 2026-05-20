"""Thin client around icourse.fudan.edu.cn JSON APIs.

All endpoints require a valid cookie jar (use auth.refresh_cookies first).
"""
from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

import requests

from .auth import load_cookie_header
from .config import Config, load_config

BASE = "https://icourse.fudan.edu.cn"


def _session(cfg: Config) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
            "Cookie": load_cookie_header(cfg),
        }
    )
    # Make sure no environment proxies leak into requests.
    s.trust_env = False
    return s


def parse_livingroom_url(url: str) -> dict[str, str]:
    """Extract course_id, sub_id, tenant_code from a livingroom URL."""
    qs = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(qs)
    out = {k: v[0] for k, v in params.items() if v}
    for required in ("course_id", "sub_id"):
        if required not in out:
            raise ValueError(f"livingroom URL missing {required}: {url}")
    out.setdefault("tenant_code", "222")
    return out


def get_sub_info(course_id: str, sub_id: str, cfg: Config | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    s = _session(cfg)
    r = s.get(
        f"{BASE}/courseapi/v3/portal-home-setting/get-sub-info",
        params={"course_id": course_id, "sub_id": sub_id},
        headers={"Referer": f"{BASE}/livingroom?course_id={course_id}&sub_id={sub_id}&tenant_code={cfg['tenant_code']}"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def get_course_detail(course_id: str, cfg: Config | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    s = _session(cfg)
    r = s.get(
        f"{BASE}/courseapi/v3/multi-search/get-course-detail",
        params={"course_id": course_id},
        headers={"Referer": f"{BASE}/coursedetail?course_id={course_id}&tenant_code={cfg['tenant_code']}"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def get_catalogue(course_id: str, cfg: Config | None = None) -> list[dict[str, Any]]:
    cfg = cfg or load_config()
    s = _session(cfg)
    r = s.get(
        f"{BASE}/courseapi/v2/course/catalogue",
        params={"course_id": course_id},
        headers={"Referer": f"{BASE}/coursedetail?course_id={course_id}&tenant_code={cfg['tenant_code']}"},
        timeout=20,
    )
    r.raise_for_status()
    body = r.json()
    items = body.get("result", {}).get("data", []) or body.get("data", [])
    # `content` is a JSON-encoded string; unpack for convenience.
    for it in items:
        c = it.get("content")
        if isinstance(c, str):
            try:
                it["content"] = json.loads(c)
            except Exception:
                pass
    return items


def get_danmu(sub_id: str, cfg: Config | None = None, page_size: int = 5000) -> list[dict[str, Any]]:
    """Return all danmu (bullet comments) for a recording. Mostly useless for
    summarization but cheap to grab and occasionally captures Q&A signals.
    """
    cfg = cfg or load_config()
    s = _session(cfg)
    r = s.get(
        f"{BASE}/courseapi/v2/danmu/search",
        params={"sub_id": sub_id, "page": 1, "pageSize": page_size, "sort": "play_time"},
        timeout=20,
    )
    r.raise_for_status()
    body = r.json()
    return body.get("data", {}).get("list", body.get("data", []) if isinstance(body.get("data"), list) else [])


def base_playback_url(sub_info: dict[str, Any]) -> str:
    """Extract the unsigned MP4 URL from a get_sub_info response. This URL is
    NOT directly downloadable — it needs a `?t=` signature appended by the
    player, see browser_signed_url.fetch_signed_video_url.
    """
    data = sub_info.get("data", {})
    content = data.get("content") or {}
    # Try several known shapes
    candidates = [
        content.get("save_playback", {}).get("contents"),
        content.get("playback", {}).get("url"),
    ]
    file_list = content.get("file_list") or {}
    if isinstance(file_list, dict):
        for k, v in file_list.items():
            if isinstance(v, dict) and v.get("file_type", "").endswith("mp4"):
                candidates.append(v.get("file_name"))
    for c in candidates:
        if isinstance(c, str) and c.endswith(".mp4"):
            return c
    raise ValueError("No playback URL found in sub-info")


def slug_for(course_title: str, sub_title: str) -> str:
    """Path-safe identifier for output dir."""
    parts = []
    for s in [course_title or "course", sub_title or "sub"]:
        s = re.sub(r"[\\/:*?\"<>|]", "_", s)
        s = re.sub(r"\s+", "_", s.strip())
        parts.append(s)
    return "__".join(parts)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        info = parse_livingroom_url(sys.argv[1])
        print(json.dumps(info, indent=2))
        sub = get_sub_info(info["course_id"], info["sub_id"])
        print("title:", sub["data"]["sub_title"], "course:", sub["data"]["course_title"])
        print("video:", base_playback_url(sub))

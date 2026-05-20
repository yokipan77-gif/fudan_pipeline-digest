"""Fetch the signed MP4 with Python (full control over HTTP headers), then
transcode the local file with ffmpeg.

Why not let ffmpeg pull HTTP directly?
- The CDN does Origin-based anti-leech (it returns
  `Access-Control-Allow-Origin: https://icourse.fudan.edu.cn` and rejects
  requests that don't send the right Origin). ffmpeg's default HTTP backend
  does not send `Origin`, so it gets 403.
- ffmpeg may probe with `Range: bytes=0-` which historically was 403'd too.
- Splitting fetch/transcode also lets us cache the .mp4 between transcription
  reruns (e.g. tweaking summarization prompts without re-downloading 2.6 GB).

The downside is one big disk write. For a ~2.5h 1080p lecture that's ~2-3 GB,
which is fine on D:\\.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import requests

from .auth import load_cookie_header
from .config import Config, load_config


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)


def _session(cookie: str, referer: str) -> requests.Session:
    s = requests.Session()
    # trust_env=False is critical to bypass Clash (system proxy on 127.0.0.1:7890)
    # which doesn't have the VPN route to icourse.fudan.edu.cn and would 503.
    s.trust_env = False
    s.headers.update({
        "User-Agent": _BROWSER_UA,
        "Accept": "*/*",
        "Accept-Encoding": "identity",  # don't gzip a 2.6 GB MP4
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": referer,
        "Origin": "https://icourse.fudan.edu.cn",
        "Cookie": cookie,
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Dest": "video",
        "Connection": "keep-alive",
    })
    return s


def _content_length(session: requests.Session, url: str) -> int:
    """Cheap HEAD to learn the expected size. Falls back to 0 if HEAD is blocked."""
    try:
        r = session.head(url, allow_redirects=True, timeout=30)
        if r.status_code == 200:
            cl = r.headers.get("Content-Length")
            return int(cl) if cl else 0
    except requests.RequestException:
        pass
    return 0


def _download_mp4(
    session: requests.Session,
    url: str,
    target: Path,
) -> int:
    """Stream the MP4 to `target`. Returns bytes written."""
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = _content_length(session, url)
    # If a complete file already exists, skip the network entirely.
    if target.exists() and expected > 0 and target.stat().st_size == expected:
        print(f"[download] reusing cached MP4 ({expected/1024/1024:.0f} MB): {target.name}", flush=True)
        return expected

    if target.exists():
        target.unlink()

    print(f"[download] GET signed URL...", flush=True)
    with session.get(url, stream=True, allow_redirects=True, timeout=(30, 300)) as r:
        if r.status_code != 200:
            raise RuntimeError(
                f"unexpected status {r.status_code} downloading signed video URL. "
                f"It may be IP-locked, expired, or the cookie is stale.\n"
                f"  body preview: {r.text[:300] if r.text else '(empty)'}"
            )
        total = int(r.headers.get("Content-Length", expected) or 0)
        print(
            f"[download] streaming {total/1024/1024:.0f} MB → {target.name}",
            flush=True,
        )
        written = 0
        last_report = 0.0
        start = time.monotonic()
        with target.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):  # 1 MB chunks
                if not chunk:
                    continue
                f.write(chunk)
                written += len(chunk)
                now = time.monotonic()
                # Throttle progress prints to once every 2 s.
                if now - last_report >= 2.0:
                    elapsed = max(now - start, 0.001)
                    rate = written / 1024 / 1024 / elapsed
                    pct = (written / total * 100) if total else 0
                    print(
                        f"[download]   {written/1024/1024:7.0f} / {total/1024/1024:.0f} MB "
                        f"({pct:5.1f}%, {rate:.1f} MB/s)",
                        flush=True,
                    )
                    last_report = now

    elapsed = max(time.monotonic() - start, 0.001)
    print(
        f"[download] done {written/1024/1024:.0f} MB in {elapsed:.0f}s "
        f"({written/1024/1024/elapsed:.1f} MB/s)",
        flush=True,
    )
    return written


def extract_audio(
    signed_url: str,
    referer: str,
    output_path: Path,
    *,
    cfg: Config | None = None,
    audio_codec: str = "libopus",
    sample_rate: int = 16000,
    bitrate: str = "32k",
    overwrite: bool = True,
    keep_video: bool = False,
) -> Path:
    """Download the signed MP4 to a sibling .mp4 file, transcode audio with
    ffmpeg, then delete the MP4 unless `keep_video=True`.

    For Opus output use .opus or .ogg extension. For raw WAV use audio_codec="pcm_s16le".
    """
    cfg = cfg or load_config()
    cookie = load_cookie_header(cfg)
    ffmpeg = str(cfg.ffmpeg_path)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        return output_path

    # Step 1: download the .mp4 alongside the audio file. Naming it `video.mp4`
    # (not `audio.mp4`) makes it obvious in the output dir.
    mp4_path = output_path.parent / "video.mp4"
    session = _session(cookie, referer)
    _download_mp4(session, signed_url, mp4_path)

    # Step 2: transcode local MP4 → small audio file.
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "warning",
        "-y" if overwrite else "-n",
        "-i", str(mp4_path),
        "-vn",
        "-ar", str(sample_rate),
        "-ac", "1",
        "-c:a", audio_codec,
    ]
    if audio_codec == "libopus":
        cmd += ["-b:a", bitrate, "-application", "voip"]
    cmd += [str(output_path), "-stats"]

    print(f"[transcode] {mp4_path.name} → {output_path.name}", flush=True)
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=sys.stderr)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"ffmpeg failed (exit {e.returncode}) while transcoding local mp4; "
            f"the .mp4 has been kept for inspection at {mp4_path}"
        ) from e

    size = output_path.stat().st_size if output_path.exists() else 0
    print(
        f"[transcode] done: {output_path} ({size/1024/1024:.1f} MB)",
        flush=True,
    )

    # Step 3: delete the big .mp4 unless caller asked to keep it.
    if not keep_video and mp4_path.exists():
        try:
            mp4_path.unlink()
            print(f"[cleanup] removed {mp4_path.name}", flush=True)
        except OSError as e:
            print(f"[cleanup] could not remove {mp4_path}: {e}", flush=True)

    return output_path


if __name__ == "__main__":
    src = sys.argv[1]
    ref = sys.argv[2]
    out = Path(sys.argv[3])
    extract_audio(src, ref, out)

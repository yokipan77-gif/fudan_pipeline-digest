"""Wrap faster-whisper with GPU-first / CPU-fallback init logic.

We re-implement (rather than shell out to bilibili-summarizer's transcribe.py)
because we want JSON output with full segment metadata for downstream
chunking by the summarizer.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Iterable

from .config import Config, load_config

# CTranslate2 (used by faster-whisper) loads CUDA DLLs at module import.
# Add the nvidia wheel's DLLs to PATH up-front so GPU init succeeds.
_nvidia_base = Path(sys.executable).parent / "Lib" / "site-packages" / "nvidia"
for _lib in ("cublas", "cudnn"):
    _bin = _nvidia_base / _lib / "bin"
    if _bin.is_dir():
        os.environ["PATH"] = str(_bin) + os.pathsep + os.environ.get("PATH", "")

# Default to the CN mirror — huggingface.co is unreachable from mainland networks
# without an HTTP proxy, which the user explicitly turns OFF to access Fudan
# internal sites. The mirror is read-only but serves identical files.
# A user can override by setting HF_ENDPOINT in their environment.
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# Enable hf_transfer (a Rust-implemented parallel downloader) when available.
# Without this huggingface_hub does a single-connection GET which the CN mirror
# rate-limits to ~150 kB/s; hf_transfer fan-outs to ~20-100 MB/s on the same link.
try:
    import hf_transfer  # noqa: F401  -- presence check
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
except ImportError:
    pass


# Map of faster-whisper model identifiers to the canonical HF repo. We use this
# to:
#   (1) detect whether the model is fully present in the HF cache;
#   (2) pre-download via huggingface_hub with retries (more robust than letting
#       ctranslate2 reach for missing files at runtime, where it just errors).
_MODEL_REPOS = {
    "tiny":     "Systran/faster-whisper-tiny",
    "base":     "Systran/faster-whisper-base",
    "small":    "Systran/faster-whisper-small",
    "medium":   "Systran/faster-whisper-medium",
    "large-v1": "Systran/faster-whisper-large-v1",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
}


# Files we need from a Systran/faster-whisper-* repo. (No more, no less — the
# repos also ship a README we don't care about, and we skip git LFS metadata.)
_WHISPER_REPO_FILES = (
    "config.json",
    "preprocessor_config.json",
    "tokenizer.json",
    "vocabulary.json",
    "model.bin",
)


def _resilient_session() -> "requests.Session":
    """A requests.Session that survives flaky TLS handshakes to hf-mirror.com.

    - trust_env=False so Clash (if accidentally left on) cannot hijack traffic.
    - urllib3 Retry with connect=8 retries kicks in on TLS handshake timeouts,
      which huggingface_hub's underlying httpx does not retry by default.
    """
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    retry = Retry(
        total=8,
        connect=8,
        read=4,
        backoff_factor=1.5,            # 0, 1.5, 3, 6, 12, 24, 30, 30 s
        status_forcelist=(500, 502, 503, 504),
        respect_retry_after_header=True,
        allowed_methods=frozenset(["GET", "HEAD"]),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
    s = requests.Session()
    s.trust_env = False
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({
        "User-Agent": "fudan-icourse-summarizer/1.0 (+python-requests)",
        "Accept": "*/*",
    })
    return s


def _file_size_via_head(session, url: str) -> tuple[int, bool]:
    """Return (Content-Length, supports_range). (0, False) on failure."""
    import requests
    try:
        h = session.head(url, allow_redirects=True, timeout=30)
        if h.status_code != 200:
            return 0, False
        total = int(h.headers.get("Content-Length", 0) or 0)
        accept_ranges = h.headers.get("Accept-Ranges", "").lower()
        return total, accept_ranges == "bytes" and total > 0
    except requests.RequestException:
        return 0, False


def _download_single_stream(session, url: str, target: Path) -> None:
    """Single-connection streaming download with resume + retry.
    Used for small files (config.json etc.) and as a fallback for big files
    when the server doesn't support Range.
    """
    import requests

    expected, _ = _file_size_via_head(session, url)
    if target.exists() and expected and target.stat().st_size == expected:
        print(f"[whisper] cached: {target.name} ({expected/1024/1024:.2f} MB)", flush=True)
        return

    for attempt in range(6):
        resume_from = target.stat().st_size if target.exists() else 0
        headers = {"Range": f"bytes={resume_from}-"} if resume_from > 0 else {}
        try:
            with session.get(url, headers=headers, stream=True, allow_redirects=True,
                             timeout=(60, 600)) as r:
                if r.status_code == 416:
                    return
                if r.status_code not in (200, 206):
                    raise RuntimeError(f"HTTP {r.status_code} for {url}")
                total_rem = int(r.headers.get("Content-Length", 0) or 0)
                total = total_rem + resume_from
                mode = "ab" if resume_from > 0 else "wb"
                written = resume_from
                start = time.monotonic()
                with target.open(mode) as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        if not chunk:
                            continue
                        f.write(chunk)
                        written += len(chunk)
            elapsed = max(time.monotonic() - start, 0.001)
            print(f"[whisper] done {target.name}: {written/1024/1024:.2f} MB "
                  f"in {elapsed:.1f}s ({(written-resume_from)/1024/1024/elapsed:.2f} MB/s)",
                  flush=True)
            return
        except (requests.ConnectionError, requests.Timeout,
                requests.exceptions.ChunkedEncodingError, OSError) as e:
            wait = min(2 ** attempt + 1, 30)
            print(f"[whisper] {target.name}: {type(e).__name__} — retry {attempt+1}/6 in {wait}s",
                  flush=True)
            time.sleep(wait)
    raise RuntimeError(f"download of {url} failed after 6 attempts")


def _download_chunk_with_retry(session, url: str, start: int, end: int,
                                fileobj_open, written_counter, lock) -> None:
    """Download bytes [start..end] inclusive into the pre-allocated file via
    a Range request. Retries internally on connection errors.

    `fileobj_open()` returns an open file in `r+b` mode (closed by caller).
    """
    import requests

    total_for_chunk = end - start + 1
    bytes_done = 0  # within this chunk

    for attempt in range(8):
        try:
            headers = {"Range": f"bytes={start + bytes_done}-{end}"}
            with session.get(url, headers=headers, stream=True, allow_redirects=True,
                             timeout=(60, 600)) as r:
                if r.status_code not in (200, 206):
                    raise RuntimeError(f"HTTP {r.status_code}")
                f = fileobj_open()
                try:
                    f.seek(start + bytes_done)
                    for block in r.iter_content(chunk_size=256 * 1024):
                        if not block:
                            continue
                        f.write(block)
                        bytes_done += len(block)
                        with lock:
                            written_counter[0] += len(block)
                        if bytes_done >= total_for_chunk:
                            break
                finally:
                    f.close()
            return
        except (requests.ConnectionError, requests.Timeout,
                requests.exceptions.ChunkedEncodingError, OSError) as e:
            wait = min(2 ** attempt, 20)
            # Don't print every retry from every thread — too noisy. Only first few.
            if attempt < 2:
                print(f"[whisper]   chunk {start//(1<<20)}MB: {type(e).__name__}, "
                      f"retry {attempt+1}/8 in {wait}s ({bytes_done}/{total_for_chunk} done)",
                      flush=True)
            time.sleep(wait)
    raise RuntimeError(f"chunk {start}-{end} failed after 8 attempts")


def _download_file_parallel(session, url: str, target: Path,
                             num_threads: int = 16,
                             min_size_for_parallel: int = 64 << 20) -> None:
    """Multi-connection Range download. Falls back to single-stream if the
    server doesn't advertise Range support or the file is small.

    Beats hf-mirror.com's per-connection rate limit by stacking N connections.
    """
    total, supports_range = _file_size_via_head(session, url)

    # Small files / no Range support → simple single stream.
    if not supports_range or total < min_size_for_parallel:
        _download_single_stream(session, url, target)
        return

    # If the final file already exists at the right size, skip.
    if target.exists() and target.stat().st_size == total:
        print(f"[whisper] cached: {target.name} ({total/1024/1024:.0f} MB)", flush=True)
        return

    # If we have a half-written final file from an old single-stream attempt,
    # toss it — we can't resume into it cleanly with the parallel layout.
    if target.exists() and target.stat().st_size != total:
        print(f"[whisper] discarding partial {target.name} "
              f"({target.stat().st_size/1024/1024:.0f}/{total/1024/1024:.0f} MB) "
              f"before parallel download", flush=True)
        target.unlink()

    partial = target.with_suffix(target.suffix + ".part")
    if partial.exists():
        partial.unlink()

    # Pre-allocate the full file (sparse on NTFS — instant).
    with partial.open("wb") as f:
        f.seek(total - 1)
        f.write(b"\0")

    # Carve into N roughly-equal byte ranges.
    chunk_bytes = (total + num_threads - 1) // num_threads
    ranges = []
    for i in range(num_threads):
        s = i * chunk_bytes
        e = min(s + chunk_bytes, total) - 1
        if s <= e:
            ranges.append((s, e))

    written = [0]  # mutable counter shared across threads
    lock = threading.Lock()
    file_lock = threading.Lock()  # serialize file opens (cheap)

    def open_file():
        # Each thread opens its own r+b handle; Windows allows multiple writers
        # at different offsets as long as we don't share the handle.
        return partial.open("r+b")

    print(
        f"[whisper] parallel download: {total/1024/1024:.0f} MB across "
        f"{len(ranges)} connections → {target.name}",
        flush=True,
    )
    start_time = time.monotonic()

    stop_progress = threading.Event()

    def progress_thread():
        last_w = 0
        last_t = time.monotonic()
        while not stop_progress.is_set():
            time.sleep(2.0)
            with lock:
                w = written[0]
            now = time.monotonic()
            inst_rate = (w - last_w) / 1024 / 1024 / max(now - last_t, 0.001)
            avg_rate = w / 1024 / 1024 / max(now - start_time, 0.001)
            pct = w / total * 100
            print(
                f"[whisper]   {target.name}: {w/1024/1024:7.0f} / {total/1024/1024:.0f} MB "
                f"({pct:5.1f}%, now {inst_rate:5.2f} MB/s, avg {avg_rate:5.2f} MB/s)",
                flush=True,
            )
            last_w, last_t = w, now

    pt = threading.Thread(target=progress_thread, daemon=True)
    pt.start()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(_download_chunk_with_retry, session, url, s, e,
                                open_file, written, lock)
                for (s, e) in ranges
            ]
            # Raise any worker exception ASAP.
            for fut in concurrent.futures.as_completed(futures):
                fut.result()
    finally:
        stop_progress.set()
        pt.join(timeout=3)

    elapsed = max(time.monotonic() - start_time, 0.001)
    print(
        f"[whisper] done {target.name}: {total/1024/1024:.0f} MB in {elapsed:.0f}s "
        f"(avg {total/1024/1024/elapsed:.2f} MB/s across {len(ranges)} threads)",
        flush=True,
    )

    partial.replace(target)


def _ensure_whisper_model(model_size: str) -> str:
    """Return a local path to a fully-downloaded faster-whisper model.

    Bypasses huggingface_hub.snapshot_download (which uses httpx and does NOT
    retry TLS handshake timeouts) in favor of a urllib3 Retry-based downloader
    that handles the flaky TLS we see hitting hf-mirror.com from CN networks.

    Files land in `cache/whisper-models/<repo-slug>/` and that path is passed
    to WhisperModel directly.
    """
    if model_size not in _MODEL_REPOS:
        # Some users may already pass a local path or HF repo id; trust them.
        return model_size

    repo_id = _MODEL_REPOS[model_size]
    cfg = load_config()
    local_dir = cfg.cache_dir / "whisper-models" / repo_id.replace("/", "--")
    local_dir.mkdir(parents=True, exist_ok=True)

    endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")
    print(f"[whisper] downloading {repo_id} from {endpoint}", flush=True)
    print(f"[whisper] local dir: {local_dir}", flush=True)

    session = _resilient_session()
    for filename in _WHISPER_REPO_FILES:
        url = f"{endpoint}/{repo_id}/resolve/main/{filename}"
        target = local_dir / filename
        # Big files (model.bin) get N-way parallel Range download to beat
        # hf-mirror.com's per-connection rate cap; small files single-stream.
        _download_file_parallel(session, url, target, num_threads=16)

    model_bin = local_dir / "model.bin"
    if not model_bin.exists() or model_bin.stat().st_size < 1_000_000:
        raise RuntimeError(
            f"model.bin missing or suspiciously small at {model_bin}; "
            f"delete {local_dir} and retry"
        )
    return str(local_dir)


def _gpu_status() -> str:
    """Best-effort one-liner of GPU name + free VRAM. Returns '' if unavailable."""
    try:
        import subprocess as _sp
        out = _sp.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            stderr=_sp.DEVNULL, timeout=5,
        ).decode().strip().splitlines()
        if not out:
            return ""
        # First GPU only (assume primary).
        name, used, total, util = [x.strip() for x in out[0].split(",")]
        return f"{name} · {used}/{total} MiB · util {util}%"
    except Exception:
        return ""


def transcribe_audio(
    audio_path: Path,
    *,
    cfg: Config | None = None,
    output_dir: Path | None = None,
    language: str | None = None,
    model_size: str | None = None,
    beam_size: int = 5,
    vad_filter: bool = True,
    batch_size: int | None = None,
) -> dict:
    """Transcribe `audio_path` and write two files:

    - `<output_dir>/transcript.txt` — human-readable with [start -> end] timestamps
    - `<output_dir>/transcript.json` — full segment list for downstream tooling

    Uses faster-whisper's BatchedInferencePipeline on GPU for 5-10x throughput
    over the naive sequential pipeline (the inner ctranslate2 engine batches
    chunks across the GPU instead of doing one segment at a time).

    Returns the JSON dict that was saved.
    """
    cfg = cfg or load_config()

    # IMPORTANT: HF_ENDPOINT must be set BEFORE faster_whisper / huggingface_hub
    # are imported, because huggingface_hub.constants snapshots the endpoint at
    # module load time. The module-level os.environ.setdefault above handles the
    # default (hf-mirror.com); config can override here.
    hf_endpoint = cfg.get("hf_endpoint")
    if hf_endpoint:
        os.environ["HF_ENDPOINT"] = hf_endpoint
    print(f"[whisper] HF endpoint: {os.environ.get('HF_ENDPOINT', '(default)')}", flush=True)

    # Local imports keep CLI startup snappy when the user only runs --skip-transcribe.
    from faster_whisper import WhisperModel, BatchedInferencePipeline

    audio_path = Path(audio_path)
    output_dir = Path(output_dir or audio_path.parent)
    output_dir.mkdir(parents=True, exist_ok=True)

    model_size = model_size or cfg["whisper_model"]
    language = language or cfg.get("whisper_language", "zh")
    device = cfg.get("whisper_device", "cuda")
    compute_type = cfg.get("whisper_compute_type", "float16")
    batch_size = batch_size or int(cfg.get("whisper_batch_size", 16))

    print(f"[whisper] ensuring model {model_size} is present locally...", flush=True)
    model_dir = _ensure_whisper_model(model_size)
    print(f"[whisper] model dir: {model_dir}", flush=True)

    gpu_before = _gpu_status()
    if gpu_before:
        print(f"[whisper] GPU before load: {gpu_before}", flush=True)

    print(
        f"[whisper] loading {model_size} on {device} ({compute_type}), batch_size={batch_size}",
        flush=True,
    )
    t0 = time.time()
    try:
        model = WhisperModel(model_dir, device=device, compute_type=compute_type)
    except Exception as e:
        # The user explicitly wants the 5070 Ti — don't silently degrade to CPU.
        # CPU on large-v3 for a 2.5h lecture would take hours instead of minutes.
        raise RuntimeError(
            f"failed to load Whisper on {device} ({compute_type}): {e}\n"
            f"This is fatal — CPU fallback would take hours on this size of audio.\n"
            f"Fix CUDA setup (cublas/cudnn DLLs in PATH) and rerun. If you actually\n"
            f"want CPU, set whisper_device=\"cpu\" and whisper_compute_type=\"int8\" in config.json."
        ) from e
    pipeline = BatchedInferencePipeline(model=model)
    print(f"[whisper] model ready in {time.time()-t0:.1f}s", flush=True)

    gpu_after = _gpu_status()
    if gpu_after:
        print(f"[whisper] GPU after load:  {gpu_after}", flush=True)

    print(f"[whisper] transcribing {audio_path.name} (batched x{batch_size})...", flush=True)
    t1 = time.time()
    segments_iter, info = pipeline.transcribe(
        str(audio_path),
        language=language,
        beam_size=beam_size,
        vad_filter=vad_filter,
        word_timestamps=False,
        batch_size=batch_size,
    )

    txt_lines: list[str] = []
    json_segments: list[dict] = []
    last_log = time.time()
    for i, seg in enumerate(segments_iter):
        txt_lines.append(f"[{seg.start:7.1f}s -> {seg.end:7.1f}s] {seg.text.strip()}")
        json_segments.append({
            "i": i,
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
        })
        # Progress print every ~5 s wall; include live GPU utilization so the user
        # can confirm the GPU is actually pegged (and yell if it isn't).
        if time.time() - last_log > 5:
            cov = seg.end / info.duration * 100 if info.duration else 0
            gpu = _gpu_status()
            extra = f" · GPU {gpu}" if gpu else ""
            print(
                f"[whisper] segment {i+1} (audio t={seg.end:.1f}s, {cov:.1f}% covered){extra}",
                flush=True,
            )
            last_log = time.time()

    elapsed = time.time() - t1
    rtf = elapsed / info.duration if info.duration else 0
    print(f"[whisper] done: {len(json_segments)} segments, {elapsed:.1f}s ({rtf:.2f}x realtime)", flush=True)

    header = (
        f"# Transcript\n"
        f"# audio: {audio_path}\n"
        f"# language: {info.language} (p={info.language_probability:.2f})\n"
        f"# duration: {info.duration:.1f}s\n"
        f"# device: {device} ({compute_type}), model={model_size}\n"
        + "=" * 72 + "\n\n"
    )
    (output_dir / "transcript.txt").write_text(header + "\n".join(txt_lines) + "\n", encoding="utf-8")

    result = {
        "audio_path": str(audio_path),
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "device": device,
        "compute_type": compute_type,
        "model": model_size,
        "elapsed_seconds": elapsed,
        "realtime_factor": rtf,
        "segments": json_segments,
    }
    (output_dir / "transcript.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    audio = Path(sys.argv[1])
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else audio.parent
    transcribe_audio(audio, output_dir=out_dir)

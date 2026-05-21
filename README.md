# fudan_pipeline-digest

**Local GPU pipeline** — authorized icourse recordings → Whisper transcription → LLM digest → HTML report.

[![License: MIT](https://img.shields.io/badge/License-MIT-09090b?style=flat-square&labelColor=18181b&color=38bdf8)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-09090b?style=flat-square&labelColor=18181b&color=38bdf8)](requirements.txt)

将已授权访问的课堂录像在本地完成转写与结构化总结。Cookie 与 API Key 仅存本机，仓库仅含代码与下方**合成预览**。

---

## Preview

以下为 `render_html` 输出的合成样例，不含真实课程、师生或转写内容。

| | |
|:---:|:---:|
| ![Header & objective](docs/assets/readme-hero.png) | ![Outline timeline](docs/assets/readme-outline.png) |

<details>
<summary>Scroll preview (GIF)</summary>
<img src="docs/assets/readme-scroll.gif" width="780" alt="Synthetic report scroll preview"/>
</details>

在线查看静态样例 → [docs/showcase/preview.html](./docs/showcase/preview.html)

---

## Architecture

```
Chrome (CDP) ──► signed URL + cookies
       │
       ▼
download.py ──► audio.opus          (Origin-aware fetch, ffmpeg extract)
       │
       ▼
transcribe.py ──► transcript.json   (faster-whisper · GPU batched)
       │
       ▼
summarize.py ──► summary.json       (DeepSeek map-reduce · checkpointed)
       │
       ▼
render_html.py ──► summary.html
```

| Module | Role |
|--------|------|
| `auth.py` | Export session cookies via CDP |
| `browser_signed_url.py` | Read CDN-signed `video.src` |
| `download.py` | MP4 download + audio extraction |
| `transcribe.py` | GPU Whisper inference |
| `summarize.py` | Chunked LLM summarization |
| `pipeline.py` | CLI orchestration |

→ [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)

---

## Setup

```bash
git clone https://github.com/yokipan77-gif/fudan_pipeline-digest.git
cd fudan_pipeline-digest
pip install -r requirements.txt
cp config.example.json config.json
```

**Prerequisites:** Python 3.12+ · ffmpeg 8+ · NVIDIA GPU (recommended) · Chrome remote debugging (9222) · campus VPN · system proxy off

```bash
python -m src.pipeline "https://icourse.fudan.edu.cn/livingroom?course_id=COURSE_ID&sub_id=SUB_ID"
```

Resume after interruption:

```bash
python -m src.pipeline "..." --skip-cookies --skip-download --skip-transcribe
```

→ [USAGE.md](./USAGE.md) · [TEST.md](./TEST.md)

---

## Privacy & compliance

Use only on recordings you are authorized to access. Do not commit `config.json`, `cookies/`, `output/`, or `cache/`.

---

## License

[MIT](./LICENSE)

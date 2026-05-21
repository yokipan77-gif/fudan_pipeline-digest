# fudan_pipeline-digest

[![License: MIT](https://img.shields.io/badge/License-MIT-09090b?style=flat-square&labelColor=18181b&color=38bdf8)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-09090b?style=flat-square&labelColor=18181b&color=38bdf8)](requirements.txt)

> 如果你也在 icourse 上反复拖进度条找「老师刚才那句到底说了啥」——这个项目就是替你干这件事的。

**fudan_pipeline-digest** 是一条跑在本地的流水线：你在浏览器里**本来就有权观看**的课堂录像，丢进来之后，它会帮你完成 **GPU 转写 → LLM 整理 → 生成 HTML 复习页**。  
不用手动下载、不用复制粘贴字幕，跑完打开 `summary.html`，大纲、概念、自测题都在里面。

Cookie 和 API Key 只留在你的硬盘上；仓库里只有代码，以及下面那张**虚构的界面预览**（不含真实师生信息）。

---

## 它能帮你做什么

- **省复习时间** — 2–3 小时的课，最后得到一份带时间戳的结构化笔记，不用从头看录像
- **本地 GPU 转写** — faster-whisper `large-v3`，显存够的话比纯 CPU 快一个数量级
- **长课也不慌** — DeepSeek 分段总结，中途断了可以从 `section_notes.json` 接着跑
- **输出即开即用** — 深色 HTML 报告，浏览器双击就能看，离线也行

适合：想系统复习、想快速定位某段内容、想批量处理一门课所有回放的同学。  
不适合：没有合法访问权限的录像——请别用它干那事。

---

## 快速上手

**第一次用，按这个顺序来：**

```bash
git clone https://github.com/yokipan77-gif/fudan_pipeline-digest.git
cd fudan_pipeline-digest
pip install -r requirements.txt
cp config.example.json config.json   # 填好 deepseek_api_key 和 ffmpeg_path
```

**开跑前的三件小事（每次都要检查）：**

1. 连上校园 VPN，能打开 icourse  
2. **关掉 Clash 等系统代理** — 开着的话 CDP 经常连不上，别问我怎么知道的  
3. Chrome 已登录 icourse，并开着远程调试（端口 9222）

**处理一节课：**

```bash
python -m src.pipeline "https://icourse.fudan.edu.cn/livingroom?course_id=COURSE_ID&sub_id=SUB_ID"
```

整门课批量跑：

```bash
python -m src.pipeline --course-id COURSE_ID --all
```

跑完在这里找报告：`output/<课程名>/<节次名>/summary.html`

**中途中断了？** 别从头来，加上跳过参数续跑就行：

```bash
python -m src.pipeline "..." --skip-cookies --skip-download --skip-transcribe
```

更细的参数说明 → [USAGE.md](./USAGE.md) · 分模块排查 → [TEST.md](./TEST.md)

---

## 常遇到的问题

**Q：CDP 连不上 / 拿不到签名 URL**  
A：八成是 Clash 还在跑。关掉系统代理，在 Chrome 里打开 livingroom 页面并保持播放，再试一次。

**Q：ffmpeg 报 403**  
A：签名 URL 过期了（大约 30 分钟）。去掉 `--skip-download`，重新跑下载那步。

**Q：Whisper 模型下好慢**  
A：首次要从镜像拉 ~3 GB，可能等个把小时。下完缓存在 `cache/`，以后就不用再下了。

**Q：DeepSeek 总结跑一半卡住，终端好几分钟没输出**  
A：reduce 阶段正常现象，耐心等。真超时了直接重跑——已完成的 chunk 在 `section_notes.json` 里，不会白跑。

**Q：GPU 没在用，CPU 慢得要命**  
A：检查 `config.json` 里 `whisper_device` 是不是 `cuda`，以及 CUDA 驱动是否正常。

**Q：预览页 `favicon.ico` 404**  
A：不是 bug。浏览器会自动要网站图标，目录里没这个文件而已，不影响 `preview.html` 正常显示。

---

## 报告长什么样

合成样例（`render_html` 真实输出样式，内容为虚构）：

| | |
|:---:|:---:|
| ![Header & objective](docs/assets/readme-hero.png) | ![Outline timeline](docs/assets/readme-outline.png) |

<details>
<summary>展开滚动预览（GIF）</summary>
<img src="docs/assets/readme-scroll.gif" width="780" alt="Synthetic report scroll preview"/>
</details>

本地也可打开 → [docs/showcase/preview.html](./docs/showcase/preview.html)

---

## 背后怎么跑的

```
Chrome (CDP) ──► 签名 URL + cookies
       ▼
  下载音频 (ffmpeg)
       ▼
  Whisper GPU 转写
       ▼
  DeepSeek 分段总结
       ▼
  summary.html
```

各模块职责与设计取舍 → [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)

需要 Python 3.12+ · ffmpeg 8+ · NVIDIA GPU（推荐）· DeepSeek 或兼容 API

---

## 隐私与合规

请只处理你有权访问的录像，遵守学校平台使用规定。  
切勿提交 `config.json`、`cookies/`、`output/`、`cache/` 到 Git。

---

## License

[MIT](./LICENSE)

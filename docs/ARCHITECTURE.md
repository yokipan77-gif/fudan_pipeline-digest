# 架构与设计说明

说明各模块如何协作，以及几个关键设计选择的原因。
不包含凭证、cookie 或机构专属内容。

## 要解决的问题

校园课堂平台通常具备：

- 需认证 CDN 的长 MP4 录像
- 与浏览器会话绑定的短时签名下载 URL
- 缺少符合复习习惯的结构化总结

目标：在本地 GPU 上将**一节已授权录像**转为**可检索转写 + LLM 总结 + HTML 报告**。

## 流水线概览

```
Livingroom / 课程 URL（用户已在 Chrome 登录）
        │
        ▼
┌───────────────────┐
│  auth.py          │  CDP → 导出会话 cookie 到本地 `cookies/`
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ browser_signed_   │  复用已开 tab 或后台新开 tab；
│ url.py            │  读取 `<video>.src` 中的 CDN 签名 URL
└─────────┬─────────┘
          ▼
┌───────────────────┐
│  download.py      │  Python `requests` 下载 MP4（需 Origin 头）；
│                   │  ffmpeg 抽取 16 kHz 单声道 Opus（默认不保留视频）
└─────────┬─────────┘
          ▼
┌───────────────────┐
│  transcribe.py    │  faster-whisper（GPU 批处理）→ transcript.json
└─────────┬─────────┘
          ▼
┌───────────────────┐
│  summarize.py     │  DeepSeek map-reduce → summary.json
└─────────┬─────────┘
          ▼
┌───────────────────┐
│  render_html.py   │  深色主题 HTML 报告
└───────────────────┘
```

## 关键设计决策

### 1. 为何用 Chrome CDP 读签名 URL？

CDN 的 MP4 带**会话绑定签名**（`clientUUID` + `t=` 时间戳 token）。
仅导出 cookie 的普通 HTTP 客户端不够——播放器会动态设置 `video.src`。

我们通过 DevTools Protocol 从**已登录**的 Chrome 实例读取签名 URL，而非重写登录流程。

### 2. 为何用 Python 下载，而非 ffmpeg HTTP？

CDN 会拒绝缺少 `Origin: https://<平台域名>` 的请求。
ffmpeg 的 HTTP 客户端无法稳定发送该头 → 403。

Python 以浏览器风格请求头流式下载，ffmpeg 只处理本地/临时文件。

### 3. 为何 map-reduce 总结？

2–3 小时课堂转写超出单次 LLM 上下文舒适区。

- **Map**：约 8 分钟窗口 → 结构化分段笔记（断点写入 `section_notes.json`）
- **Reduce**：汇总全部分段 → 课程目的、大纲、概念、自测题

指数退避重试应对不稳定 API。

### 4. 为何 GPU 批处理 Whisper？

CUDA 上 `BatchedInferencePipeline` 对 `large-v3` 吞吐约为顺序 CPU 的 10–20 倍。

模型权重下载一次到 `cache/whisper-models/` 后复用。

### 5. 运行约束

| 约束 | 应对 |
|------|------|
| 系统代理（Clash）劫持 localhost CDP | 所有 HTTP 客户端 `trust_env=False` |
| 签名 URL 有效期（约 30 分钟） | 每次运行开始时刷新 |
| 国内 Whisper 模型下载不稳定 | 自定义并行下载 + hf-mirror.com |
| DeepSeek API 超时 | 长 connect/read 超时 + 分段断点 |

## 模块一览

| 模块 | 职责 |
|------|------|
| `config.py` | 加载 `config.json`，解析路径 |
| `auth.py` | CDP WebSocket 导出 cookie |
| `icourse_api.py` | 课程元数据 JSON API（可选 enrichment） |
| `browser_signed_url.py` | CDP 代理封装，提取 video src |
| `download.py` | MP4 下载 + ffmpeg 抽音频 |
| `transcribe.py` | faster-whisper 封装 |
| `summarize.py` | DeepSeek map-reduce |
| `render_html.py` | HTML 报告 |
| `pipeline.py` | CLI 编排 |

## 扩展点

便于 fork 的扩展方向：

- **其他 LMS**：为你的站点播放器实现 `signed_url.py` + `api.py`
- **其他 LLM**：替换 `summarize.py` 客户端（OpenAI 兼容 API）
- **其他 ASR**：替换 `transcribe.py`，保持 `transcript.json`  schema
- **仅本地视频**：跳过 CDP/签名 URL，指向本地文件（未来 / fork）

## 法律与伦理（维护者）

- 只发布**代码**——不含样例视频、转写、cookie 或课程 PDF
- 明确用户须遵守机构使用条款
- 勿宣传为绕过工具；仅自动化处理用户已在浏览器中可访问的内容

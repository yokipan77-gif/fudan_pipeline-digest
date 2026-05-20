# 使用说明

将已授权课堂录像转为转写文本与 HTML 学习报告。

克隆后进入项目根目录，所有命令在该目录下执行（PowerShell / CMD 均可）。

---

## 1. 一次性准备

### 1.1 进入项目目录

```powershell
cd fudan_pipeline-digest   # 你的克隆目录
```

### 1.2 配置文件

```powershell
copy config.example.json config.json
```

编辑 `config.json`，至少确认：

| 字段 | 说明 |
|---|---|
| `deepseek_api_key` | DeepSeek API Key |
| `deepseek_summary_model` | 如 `deepseek-v4-pro` / `deepseek-chat` |
| `ffmpeg_path` | ffmpeg 8.1+ 可执行文件路径 |
| `whisper_model` | 默认 `large-v3`（只需下载一次，缓存在 `cache/`） |
| `output_dir` | 输出根目录 |

### 1.3 运行前环境（每次批量处理前检查）

1. **连校园 VPN**（能访问 `icourse.fudan.edu.cn`）
2. **关闭 Clash 系统代理**（否则 CDP / 校园网会冲突）
3. **Chrome 已登录 icourse**，且开着远程调试（9222）
4. **CDP 代理在跑**（web-access skill，`localhost:3456`）

Whisper 模型首次使用会从 `hf-mirror.com` 下载约 3 GB，之后所有课程复用，**不用重复下载**。

---

## 2. 主命令（推荐）

### 2.1 处理单节课（livingroom 链接）

在 Chrome 里打开目标录像页，复制地址栏 URL，然后：

```powershell
python -m src.pipeline "https://icourse.fudan.edu.cn/livingroom?course_id=34945&sub_id=563930&tenant_code=222"
```

**也可以不预先打开页面**——脚本会通过 CDP 自动开 tab 拿签名；但**已打开并播放中的 tab 更快、更稳**。

### 2.2 用 course_id + sub_id

```powershell
python -m src.pipeline --course-id 34945 --sub-id 563930
```

### 2.3 批量处理整门课所有录像

```powershell
python -m src.pipeline --course-id 34945 --all
```

会自动拉课程目录，跳过还没有回放的条目（`status != 6`）。

---

## 3. 常用参数

```text
python -m src.pipeline [livingroom_url] [选项]
```

| 参数 | 作用 |
|---|---|
| `--skip-cookies` | 不刷新 cookie，用 `cookies/cookie-header.txt` 缓存 |
| `--skip-download` | 已有 `audio.opus` 则跳过下载 |
| `--skip-transcribe` | 已有 `transcript.json` 则跳过 Whisper |
| `--skip-summarize` | 已有 `summary.json` 则跳过 DeepSeek 总结 |
| `--keep-video` | 保留下载的 `video.mp4`（默认转完音频就删） |
| `--audio-format opus` | 输出 Opus（默认，体积小） |
| `--audio-format wav` | 输出 WAV（体积大，一般不需要） |
| `--output-dir PATH` | 自定义输出根目录 |
| `--tenant-code 222` | 租户码，默认 222 |

查看完整帮助：

```powershell
python -m src.pipeline --help
```

---

## 4. 断点续跑 / 重跑某一步

输出目录结构（每节课一个子文件夹）：

```
output/<课程名>/<节次名>/
  audio.opus          # 音频
  transcript.json     # 字幕（结构化）
  transcript.txt      # 字幕（可读）
  section_notes.json  # 分段笔记（map 阶段，可断点续跑）
  summary.json        # 最终总结
  summary.html        # 报告（双击打开）
  meta.json           # 课程元信息
```

### 场景 A：下载 + 转录已完成，只重跑总结

```powershell
python -m src.pipeline "https://icourse.fudan.edu.cn/livingroom?course_id=34945&sub_id=563930&tenant_code=222" --skip-cookies --skip-download --skip-transcribe
```

### 场景 B：只想重新生成 HTML（不改总结内容）

手动改完 `summary.json` 后：

```powershell
python -m src.render_html "output/<课程名>/<节次名>/summary.json" "output/<课程名>/<节次名>/transcript.json" "output/<课程名>/<节次名>/summary.html"
```

### 场景 C：DeepSeek 总结中途断了

直接重跑总结即可——`section_notes.json` 里已完成的 chunk 会自动跳过：

```powershell
python -m src.pipeline --course-id 34945 --sub-id 563930 --skip-cookies --skip-download --skip-transcribe
```

### 场景 D：只想换 prompt / 模型重总结

删除或改名 `summary.json`，保留 `section_notes.json`，再跑：

```powershell
python -m src.pipeline --course-id 34945 --sub-id 563930 --skip-cookies --skip-download --skip-transcribe
```

---

## 5. 分模块单独运行（调试 / 高级）

```powershell
# 从 Chrome 刷新 cookie
python -m src.auth

# 测试拿签名 URL（需 livingroom 页在 Chrome 里）
python -m src.browser_signed_url 34945 563930

# 单独转录
python -m src.transcribe "output/<课程名>/<节次名>/audio.opus" "output/<课程名>/<节次名>"

# 单独总结
python -m src.summarize "output/<课程名>/<节次名>/transcript.json"
```

---

## 6. 典型耗时参考（2.5h 录像，5070 Ti）

| 阶段 | 首次 | 再次跑同一节 |
|---|---|---|
| Cookie + 签名 | ~5 s | ~5 s |
| 下载 MP4 + 抽音频 | ~5 min | 跳过（`--skip-download`） |
| Whisper large-v3 | ~2 min | 跳过（`--skip-transcribe`） |
| DeepSeek map（19 段） | ~15–30 min | 跳过或断点续 |
| DeepSeek reduce | ~3–10 min | 同上 |
| 渲染 HTML | <1 s | <1 s |

**reduce 阶段终端可能几分钟无新输出，属于正常现象。**

---

## 7. 批量处理建议工作流

```powershell
cd fudan_pipeline-digest

# 1. 连 VPN，关 Clash，Chrome 登录 icourse
# 2. 整门课一次性跑（可挂机过夜）
python -m src.pipeline --course-id 34945 --all

# 3. 第二天查看 output/ 下的 summary.html
explorer output
```

某节失败不影响其他节；修复后对该节单独重跑：

```powershell
python -m src.pipeline --course-id 34945 --sub-id 563930 --skip-transcribe
```

---

## 8. 常见问题

| 现象 | 处理 |
|---|---|
| CDP / 签名 URL 失败 | 关 Clash；Chrome 打开 livingroom 并保持播放 |
| ffmpeg 403 | 签名过期，重新跑（不要 `--skip-download`） |
| Whisper 模型下载慢 | 首次约 1h（hf-mirror）；下完永久缓存 |
| DeepSeek 超时 | 直接重跑总结；已支持自动重试 + 断点续跑 |
| GPU 未使用 | 检查 `whisper_device: cuda`；不要改回 CPU |

---

## 9. 最终产物

单节课报告路径：

```
output/<课程名>/<节次名>/summary.html
```

用浏览器打开即可阅读。

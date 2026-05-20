# 自测指南

> 访问校园内网时**关闭**系统代理（如 Clash）；Chrome 须已登录 icourse。

## 0. 一次性准备

```bash
cp config.example.json config.json
# 编辑 config.json — 至少设置 deepseek_api_key 与 ffmpeg_path
```

验证 CDP 代理（若使用 web-access 辅助）：

```bash
curl -s http://localhost:3456/health
```

## 1. 分模块测试

```bash
cd fudan_pipeline-digest
```

### 1.1 Cookie 刷新（约 1–2 s）

```bash
python -m src.auth
ls cookies/
```

### 1.2 课程 API（需 VPN / 校园网）

```bash
python -m src.icourse_api "https://icourse.fudan.edu.cn/livingroom?course_id=...&sub_id=..."
```

### 1.3 签名视频 URL（Chrome 中 livingroom 页正在播放）

```bash
python -m src.browser_signed_url COURSE_ID SUB_ID
```

### 1.4 完整流水线

```bash
python -m src.pipeline "https://icourse.fudan.edu.cn/livingroom?course_id=...&sub_id=..."
```

### 1.5 失败后续跑

```bash
python -m src.pipeline "..." --skip-cookies --skip-download --skip-transcribe
```

## 2. 常见失败

| 现象 | 处理 |
|------|------|
| CDP 连接被拒绝 | 关系统代理；确认 Chrome 调试端口已开 |
| ffmpeg 403 | 签名过期 — 去掉 `--skip-download` 重跑 |
| Whisper 模型下载慢 | 仅首次；缓存在 `cache/` |
| DeepSeek 超时 | 重跑总结；`section_notes.json` 保留进度 |

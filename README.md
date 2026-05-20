# fudan_pipeline-digest

把复旦 **icourse** 上本来就能看的课堂录像，在本地跑一遍：Whisper 转写 → DeepSeek 总结 → 一份 HTML 笔记，复习时浏览器直接打开。

自己用的小工具，开源出来给同校同学参考。

> 请确保你对录像有合法访问权限，遵守学校平台规定。仓库里只有代码和**虚构的界面预览图**，不含真实师生信息、cookie 或 API Key。

---

## 报告长什么样

下面是流水线生成的 HTML 样式示意（内容为虚构示例）：

![界面预览：标题与课程目的](docs/assets/readme-hero.png)

![章节小地图与概念卡片](docs/assets/readme-outline.png)

<details>
<summary>展开滚动预览（GIF）</summary>

![向下浏览报告各区块](docs/assets/readme-scroll.gif)

</details>

完整版还会带上可折叠的全文转录，保存在 `output/<课程>/<节次>/summary.html`。

---

## 怎么用

```bash
git clone https://github.com/yokipan77-gif/fudan_pipeline-digest.git
cd fudan_pipeline-digest
pip install -r requirements.txt
cp config.example.json config.json   # 填 deepseek_api_key、ffmpeg_path
```

跑之前：连校园 VPN，**关掉 Clash 系统代理**，Chrome 登录 icourse 并开远程调试（9222）。

```bash
python -m src.pipeline "https://icourse.fudan.edu.cn/livingroom?course_id=...&sub_id=..."
```

中途断了可以续跑，例如只重跑总结：

```bash
python -m src.pipeline "..." --skip-cookies --skip-download --skip-transcribe
```

更多命令和排错 → [USAGE.md](./USAGE.md)

---

## 大致流程

1. 从 Chrome（CDP）拿带签名的视频地址和 cookie  
2. 下载 MP4，ffmpeg 抽成 Opus  
3. **faster-whisper** `large-v3`，GPU 批处理  
4. **DeepSeek** 分段 map-reduce 写总结，支持断点  
5. 渲染 HTML  

设计细节见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)。分模块自测见 [TEST.md](./TEST.md)。

需要 Python 3.12+、ffmpeg 8+、NVIDIA GPU（推荐）、DeepSeek 或兼容 API。

---

## 许可证

[MIT](./LICENSE)

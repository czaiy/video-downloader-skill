# video-downloader-skill

[AstrBot](https://github.com/AstrBotDevs/AstrBot) 的视频下载技能（SKILL.md 指令包）：
**用户粘贴视频链接 → 自动识别平台 → 解析无水印直链 → 下载 → 发送给用户**。

像 SnapAny 一样工作，底层基于 `yt-dlp`（支持 1000+ 站点）+ `ffmpeg`（音视频合并/转封装）。

## 支持平台

抖音、TikTok、YouTube、Bilibili、快手、小红书、微博、Twitter/X、Instagram 等 1000+ 站点。
针对抖音图文/笔记类内容附带专用解析脚本 `scripts/douyin_note.py` 作为兜底。

## 安装

1. 将本仓库复制到 AstrBot 的技能目录：

   ```
   AstrBot/data/skills/video-downloader/
   ├── SKILL.md
   └── scripts/
       └── douyin_note.py
   ```

2. 安装依赖：

   ```powershell
   pip install yt-dlp
   ```

3. 安装 ffmpeg（技能默认路径 `C:\ffmpeg\bin\ffmpeg.exe`，其他环境请修改 SKILL.md 中的路径）。

4. 重启 AstrBot，发送一条视频链接即可触发。

## 特性

- 默认下载 ≤1080p 无水印版本（用户可指定 4K/原画）
- 支持纯音频提取
- **发送完成后自动删除本地临时文件**，不留存任何下载副本
- 严格的执行约束：最多 6 次工具调用、失败即止，避免无意义重试
- 内置平台话术风格指引，回复自然活泼

## 环境说明

本技能针对 **Windows + PowerShell 5.1** 编写（命令用 `;` 连接）。
其他系统使用时需将 SKILL.md 中的 PowerShell 命令改为等价 shell 命令。

## 许可证

MIT

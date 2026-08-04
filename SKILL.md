---
name: video-downloader
description: "Use this skill when the user sends a video URL and wants to download the video file. Supports TikTok, YouTube, Bilibili, Twitter/X, Instagram, Douyin, Kuaishou, Xiaohongshu, Weibo, and 1000+ sites. Triggers: user pastes a video link and asks to download, save, parse, or get the video. Also triggers for \"帮我下载这个视频\", \"把这个视频发给我\", or any video URL from supported platforms."
---

# Video Downloader Skill (Windows 版)

像 SnapAny 一样工作：**用户粘贴链接 → 自动识别平台 → 解析出无水印媒体直链 → 选清晰度下载 → 转封装 → 发给用户**。
底层用 `yt-dlp`（解析 1000+ 站点）+ `ffmpeg`（合并/转码）。

## 运行环境（本机已配置，勿重复安装）

- 运行时：Windows，PowerShell 5.1。**命令之间用 `;` 连接，禁止用 `&&`**（PS 5.1 不支持）。
- Python：`python`（3.12，pip 可用）
- yt-dlp：已用 pip 安装，调用方式固定为 `python -m yt_dlp`
- ffmpeg：`C:\ffmpeg\bin\ffmpeg.exe`（已加入 PATH）
- 临时目录：统一用 `$env:TEMP`，文件名前缀固定 `dl_media`

先快速自检（仅在不确定环境时执行一次）：

```powershell
python -m yt_dlp --version; & "C:\ffmpeg\bin\ffmpeg.exe" -version | Select-Object -First 1
```

## ★★★ 严格执行规则 ★★★

1. **最多 6 次工具调用**，超过就停止并告诉用户结果
2. **失败就放弃**，不要反复重试不同方法
3. **不要使用 browser_use 工具**，只用 shell 命令
4. 整体风格：像小女孩跟朋友聊天，自然活泼
5. **结尾总结里绝对不要出现 #标签/hashtag 内容**，发出去之前把 #xxx 全部过滤掉

## 输出流程（一轮完成）

### 1. 开头（文字，随工具调用一起输出）

自然回应，每次不一样，像朋友：
- "好嘞～等我一小下 🫡"
- "来咯来咯！帮你扒下来"
- "收到啦～马上搞定 ✨"
- "好呀！让我看看…"
- "嘿嘿收到，稍等哈 📥"

### 2. 下载文件（工具调用）

**视频（默认，无水印，≤1080p）：**

yt-dlp 直接抓平台源流，TikTok/抖音等默认拿到的就是无水印源：

```powershell
python -m yt_dlp --ffmpeg-location "C:\ffmpeg\bin\ffmpeg.exe" -f "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best" --merge-output-format mp4 -o "$env:TEMP\dl_media.%(ext)s" --no-playlist --restrict-filenames --no-warnings "VIDEO_URL" 2>&1 | Out-String
```

**用户明确要高清晰度（4K/原画）时**，去掉高度限制：

```powershell
python -m yt_dlp --ffmpeg-location "C:\ffmpeg\bin\ffmpeg.exe" -f "bestvideo+bestaudio/best" --merge-output-format mp4 -o "$env:TEMP\dl_media.%(ext)s" --no-playlist --restrict-filenames --no-warnings "VIDEO_URL" 2>&1 | Out-String
```

**只要音频：**

```powershell
python -m yt_dlp --ffmpeg-location "C:\ffmpeg\bin\ffmpeg.exe" -f "bestaudio" -x --audio-format mp3 -o "$env:TEMP\dl_media.%(ext)s" --no-playlist --restrict-filenames --no-warnings "VIDEO_URL" 2>&1 | Out-String
```

**要字幕（可选分支，用户明确要字幕时）：** 追加 `--write-subs --sub-langs "zh.*,en.*" --convert-subs srt`，下载后把 `.srt` 文件一并发送。

**要封面图（可选分支）：** 追加 `--write-thumbnail`，封面若是 webp 可一并发给用户。

**用户明确要整个合集/播放列表时：** 把 `--no-playlist` 换成 `--yes-playlist`，输出模板加上序号 `dl_media_%(playlist_index)s.%(ext)s`。

### 3. 动图/动画图片转视频

如果下载到的文件是 gif/webp 等动图格式，**必须用 ffmpeg 转成 mp4 再发送**：

```powershell
& "C:\ffmpeg\bin\ffmpeg.exe" -y -i "$env:TEMP\dl_media.gif" -movflags faststart -pix_fmt yuv420p -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" "$env:TEMP\dl_media_video.mp4"
```

webp 动图同理，把输入换成 `$env:TEMP\dl_media.webp`。转完后发送 mp4 文件。

### 4. 查找并发送文件

```powershell
Get-ChildItem "$env:TEMP\dl_media*" | Select-Object -ExpandProperty FullName
```

用 `send_message_to_user` 发送，每个文件一个 `{"type": "file", "path": "完整绝对长路径"}` 组件。
路径必须来自 `Get-ChildItem`/`Get-Item` 输出的完整路径（自动为长路径），**不要使用含 `ADMINI~1` 等 `~1` 短名称的路径**。
一个文件都没找到时，直接按"错误处理"告知用户失败，不要发空总结。

### 5. 结尾总结（文字）

**必须包含**：博主名 + 文案/标题（已过滤 #标签）。开头随机：
好啦 / 搞定 / 来咯 / 给你 / 拿到啦 / ok / 嘿嘿搞定啦 / 完美

**★★★ 过滤规则（重要）★★★**
发出去之前，把标题/文案中的 #标签 全部去掉。例如：
- 原文："上条视频的后续来啦^_^ #女大回村记"
- 发送："上条视频的后续来啦^_^"
- 用 regex `#\S+` 匹配并删除所有 #xxx

emoji 自然加，位置灵活。结尾可感叹一句但别刻意。

示例：
- "搞定啦 🎬 「栖因」的视频 —— \"上条视频的后续来啦\""
- "好啦来咯～「知离」的图文 —— \"循此苦旅 以达繁星\" ✨"

### 6. 清理（自动执行，每次发送后强制清理）

发送完成后，**自动删除本地临时文件**，不保留任何下载副本：

```powershell
python -c "import glob,os,tempfile;[os.remove(f) for f in glob.glob(os.path.join(tempfile.gettempdir(),'dl_media*'))]"
```

> 此清理步骤在每次发送后**强制执行**，确保本地不留存用户视频/音频副本。

## 抖音图文/视频兜底（yt-dlp 失败或仍有水印时）

如果 yt-dlp 下载失败且链接是 douyin.com（或用户反馈抖音视频带水印），
用本技能自带的脚本 `scripts\douyin_note.py`（位于本 SKILL.md 所在目录的 scripts 子目录）。
它用移动端 UA 解析分享页的 `_ROUTER_DATA`：图文帖逐张下载原图，视频则把 `playwm` 换成 `play` 拿无水印直链。

```powershell
python "<本skill目录>\scripts\douyin_note.py" "VIDEO_URL" $env:TEMP
```

脚本输出 `Author:`、`Desc:` 以及每个已保存文件的完整路径（`IMG_n:`/`VIDEO:`）。

**★★★ 拿到路径后必须按顺序执行，不许跳过 ★★★**

1. 把脚本输出的每个路径规范化为长路径（本机 `$env:TEMP` 含 `ADMINI~1` 短名称，必须转换）：

```powershell
(Get-Item "<脚本输出的路径>").FullName
```

2. 动图(webp/gif)先用 ffmpeg 转 mp4（见第 3 步）。
3. **必须调用 `send_message_to_user` 发送文件**，每个文件一个组件，格式严格为：
   `{"type": "file", "path": "<规范化后的绝对长路径>"}`
   只发文字总结、不发文件组件 = 任务失败。
4. 如果某个路径 `Test-Path` 为 False，跳过该文件并在总结里说明。

**拿不到就放弃，告诉用户"这个暂时下载不了"，不要继续尝试。**

## 错误处理

失败时简短告知，不要反复重试：
- "哎呀没下载成功 😣 可能这个要登录才能看"
- "这个暂时下载不了，链接可能过期了"
- "这个暂时下不了，可能是会员/付费内容"
- B 站报 `412 Precondition Failed`：是 B 站风控拦了服务器 IP，不是命令写错了，别换命令折腾；可提示用户提供 cookies（--cookies-from-browser 或 cookies 文件）再试一次

## 绝对不要用 rm / Remove-Item 删文件，清理一律用上面的 python os.remove

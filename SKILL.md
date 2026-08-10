---
name: video-downloader
description: "Use this skill when the user sends a video URL and wants to download the video file. Supports TikTok, YouTube, Bilibili, Twitter/X, Instagram, Douyin, Kuaishou, Xiaohongshu, Weibo, and 1000+ sites. Also supports Baidu Netdisk (pan.baidu.com) and Quark Netdisk (pan.quark.cn) share links to download shared files. Triggers: user pastes a video link and asks to download, save, parse, or get the video. Also triggers for \"帮我下载这个视频\", \"把这个视频发给我\", \"帮我下载网盘文件\", or any video/netdisk URL from supported platforms."
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
6. **回复结构固定三段式**：开头回应文字（随工具调用一起输出）→ 发送文件组件 → 结尾总结文字。不要改成纯文字播报或先发总结后发文件
7. **不要向用户提及内部工具/脚本/解析站名称**（tikweb/SSSTik/SaveTik/hellotik/dousnap/snapany/yt-dlp 等），用户只需要拿到文件；唯一例外是 SnapAny 消耗了 credit 时按既定规则在总结里说明

## 输出流程（一轮完成）

### 0. 平台路由（第一步必做，先于任何下载命令）

先看链接域名再选路线，**不要无脑先跑 yt-dlp**：
- **网盘分享**（pan.baidu.com / pan.quark.cn）→ 直接跳到「网盘链接解析」章节运行对应脚本，**禁止用 yt-dlp**
- **快手**（v.kuaishou.com / kuaishou.com / chenzhongtech.com）→ 直接跳到「快手兜底」章节运行 `scripts\kuaishou.py`，**禁止用 yt-dlp**（yt-dlp 无快手提取器，必失败）
- **抖音**（douyin.com）→ **跳过 yt-dlp**，直接跳到「抖音解析」章节运行 `scripts\hellotik.py`（2026-08 起 yt-dlp 与抖音官方 API 在服务器 IP 上被风控拦死：空响应/"Fresh cookies needed"，别浪费时间）
- **TikTok**（tiktok.com / vm.tiktok.com / vt.tiktok.com / tiktok.com/t/）→ **跳过 yt-dlp**，直接跳到「TikTok 网页解析」章节运行 `scripts\tikweb.py`（2026-08-11 实测服务器直连 www.tiktok.com 连接超时，yt-dlp 必失败；第三方解析站 tikcdn.io/snapcdn.app 可达）
- **其他平台** → 步骤 2 的 yt-dlp

完整对照见「平台策略速查」表。

### 1. 开头（文字，随工具调用一起输出）

自然回应，每次不一样，像朋友：
- "好嘞～等我一小下 🫡"
- "来咯来咯！帮你扒下来"
- "收到啦～马上搞定 ✨"
- "好呀！让我看看…"
- "嘿嘿收到，稍等哈 📥"

### 2. 下载文件（工具调用）

> ⚠️ **快手/TikTok 链接跳过本节**：快手用「快手兜底」章节脚本；TikTok 用「TikTok 网页解析」章节的 tikweb.py（服务器连不上 www.tiktok.com，yt-dlp 必超时，别试）。

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

用 `send_message_to_user` 发送，每个文件一个组件，**按扩展名选类型**：
- 图片（`.jpeg`/`.jpg`/`.png`/`.gif`）→ `{"type": "image", "path": "完整绝对长路径"}`（微信才会直接显示图片）
- 视频（`.mp4`）→ `{"type": "video", "path": "完整绝对长路径"}`（微信才会显示成可播放的视频；**禁止用 `file`**，否则微信只显示成文件附件）
- ⚠️ `.webp` 不要直接发：微信/.NET 不认 webp 会变成文件。兜底脚本已自动转 jpeg；如果是 yt-dlp 下载的 webp，先用 ffmpeg 转 jpeg 再发

路径必须来自 `Get-ChildItem`/`Get-Item` 输出的完整路径（自动为长路径），**不要使用含 `ADMINI~1` 等 `~1` 短名称的路径**。
一个文件都没找到时，直接按"错误处理"告知用户失败，不要发空总结。

### 5. 结尾总结（文字）

**必须包含**：博主名 + 文案/标题（已过滤 #标签）。开头随机：
好啦 / 搞定 / 来咯 / 给你 / 拿到啦 / ok / 嘿嘿搞定啦 / 完美

**★★★ 禁止机械后缀 ★★★**
**绝对不要**在结尾固定加"无水印版"、"已去水印"、"高清无水印"这类套话——视频本身有没有水印一眼就能看出来，每次都说显得像复读机。

**★★★ 禁止透露内部流程 ★★★**
**绝对不要**在结尾提及"干净三段式"、"免费解析"、"没花 credit"这类内部流程描述——用户只需要拿到文件，不需要知道解析花了多少钱、走了几条链路。**唯一例外**：SnapAny 实际消耗了 credit 时，在总结里如实说明（例如"这个走了云端解析，消耗了 1 个 credit"）。

**★★★ 加一句作品评论（重要）★★★**
根据标题/文案内容，加一句自然可爱的真实反应，像朋友看了视频随口吐槽/夸奖。
- 评论只基于已知信息（标题、博主名、平台），不要编造视频里的具体细节
- 风格参考：反差萌吐槽、夸氛围、接梗、感叹，一次只用一句，别刷屏
- 每次不一样，别形成固定句式

**★★★ 过滤规则（重要）★★★**
发出去之前，把标题/文案中的 #标签 全部去掉。例如：
- 原文："上条视频的后续来啦^_^ #女大回村记"
- 发送："上条视频的后续来啦^_^"
- 用 regex `#\S+` 匹配并删除所有 #xxx

emoji 自然加，位置灵活。

示例：
- "搞定啦 🎬 「栖因」的视频 —— \"上条视频的后续来啦\" 这后续走向还挺意外的哈哈"
- "好啦来咯～「知离」的图文 —— \"循此苦旅 以达繁星\" ✨ 光看标题就很有史诗感"
- "拿到啦 🎬 「森川梨」的作品 —— \"我保证我是天使\" 哈哈这名字配天使摇，反差萌拉满～"

### 6. 清理（⚠️ 不能立刻执行，必须等上传完成）

> **竞态修复**：`send_message_to_user` 调用返回只代表"入队"，后台还在读文件上传到微信。长视频上传要数十秒，**必须等够时间再删**，否则上传读到一半文件已被清理 → 发送失败。

**清理前必须 sleep，时长按文件大小估算**（微信桥接器约 3MB/s 上行，留 2× 余量 + 最少 5 秒）：

```powershell
# 先看要删的文件总大小（MB），再 sleep 足够时间
$totalMB = (Get-ChildItem "$env:TEMP\dl_media*" | Measure-Object Length -Sum).Sum / 1MB; $wait = [Math]::Max(5, [Math]::Ceiling($totalMB / 1.5)); Write-Host "total ${totalMB}MB, waiting ${wait}s for upload to finish..."; Start-Sleep -Seconds $wait; python -c "import glob,os,tempfile;[os.remove(f) for f in glob.glob(os.path.join(tempfile.gettempdir(),'dl_media*'))];print('cleaned')"
```

> **为什么**：send_message_to_user 立刻返回 ≠ 微信发完。小文件（几 MB）几秒传完；长视频（几十~几百 MB）要传很久。sleep 等上传跑完再清临时文件，就不会炸。
> **严禁**：把清理命令紧挨在 send_message_to_user 后面写（PS `;` 连接也不行），必须通过 Start-Sleep 留出上传时间窗口。

## 平台策略速查（先看链接域名，再选路线）

| 平台（域名特征） | 首选路线 | 兜底/备注 |
|---|---|---|
| 抖音 douyin.com | **直接 `scripts\hellotik.py`**（2026-08-10 实测可用，视频/图文） | 失败/限速 → `scripts\dousnap.py`（免费，2026-08-11 实测视频/图文/BGM 全通）→ `scripts\tikweb.py`（机会性）→ SnapAny；**禁先跑 yt-dlp**；douyin_note 改版后已失效，移出主链 |
| **快手 kuaishou.com / chenzhongtech.com** | **直接 `scripts\kuaishou.py`** | 失败 → `scripts\dousnap.py` 机会性尝试（官方宣称支持，未验证）；yt-dlp 无快手提取器，别浪费时间试 |
| 小红书 xiaohongshu.com / xhslink.com | yt-dlp（XiaoHongShu 提取器） | 失败 → `scripts\dousnap.py` 机会性尝试（官方宣称支持，未验证）→ 仍失败就放弃告知用户 |
| B站 bilibili.com | yt-dlp | 412 风控 → `scripts\dousnap.py`（同步直出视频直链+MP3，2026-08-11 实测可用）→ 或提示用户提供 cookies |
| 微博 weibo.com / weibo.cn | yt-dlp（WeiboVideo） | m.weibo.cn/status 格式最稳 |
| **TikTok tiktok.com / vm./vt. / /t/** | **直接 `scripts\tikweb.py`**（2026-08-11 实测可用，无水印/MP3/HD 原画） | **禁用 yt-dlp**（2026-08-11 实测服务器直连 www.tiktok.com 超时，必失败） |
| YouTube / Instagram | yt-dlp | 失败就放弃并告知 |
| **百度网盘 pan.baidu.com** | **直接 `scripts\pan_baidu.py`** | 仅文件不支持文件夹；禁 yt-dlp |
| **夸克网盘 pan.quark.cn** | **直接 `scripts\pan_quark.py`** | 支持文件夹递归；需 config 解析密码；禁 yt-dlp |

**快手特殊说明**：平台源画质封顶约 720p，这是平台限制，属正常现象，不用折腾更高清晰度。

## 快手兜底（直接走脚本，不经 yt-dlp）

链接含 kuaishou.com 或 chenzhongtech.com 时，**跳过 yt-dlp**（yt-dlp 无快手提取器，必失败），直接运行本技能自带脚本 `scripts\kuaishou.py`。
它用移动端 UA 解析分享页的 `window.INIT_STATE` JSON：

- **视频帖**：从 `mainMvUrls` 拿无水印 mp4 直链（kwimgs/yximgs CDN，源画质封顶约 720p）
- **图文帖（图集）**：图片藏在 `ext_params.atlas`；快手 CDN 同路径支持 `.jpg` 直连，脚本优先直下 jpg 原图（1080p+，微信可直接预览），失败才 webp→jpeg 转换
- **单图帖**：coverUrls 兜底

```powershell
python "C:\Users\Administrator\Desktop\Astrbot\data\skills\video-downloader\scripts\kuaishou.py" "分享文本或链接" $env:TEMP
# 用户明确要 BGM/音频时，末尾追加 audio 参数（图集帖 BGM 在 atlas.music，脚本输出 AUDIO:<path>）：
python "C:\Users\Administrator\Desktop\Astrbot\data\skills\video-downloader\scripts\kuaishou.py" "分享文本或链接" $env:TEMP audio
```

> ⚠️ 必须原样复制上面的绝对路径命令执行。
> **不要自己 curl/requests 探测快手短链**——桌面 UA 会被分流到 PC 页面导致解析失败，脚本内部已用移动端 UA 处理。

脚本输出 `Author:`、`Desc:` 及 `VIDEO:<path>`（视频）或多行 `IMG_n:<path>`（图文帖，每张图一行）。**拿到路径后按「抖音兜底」小节的 4 步后处理流程执行**（长路径规范化 → 动图转 mp4 → send_message_to_user 发文件组件，多张图就发多个组件 → 清理）。

## 抖音解析（hellotik 优先，跳过 yt-dlp）

> ⚠️ **2026-08 现状**：抖音把分享页改成纯 SPA（`_ROUTER_DATA` 不再内嵌视频数据），且官方 API（iteminfo/amemv/web detail）对服务器 IP 一律返回空响应——**yt-dlp 和 douyin_note.py 的旧路线全部失效**。抖音链接一律先走 hellotik（免费，2026-08-10 实测视频帖 3 秒出片）。

**首选：hellotik**（支持视频帖 + 图文帖，输出 `Text:`/`VIDEO:`/`IMG_n:`）：

```powershell
python "C:\Users\Administrator\Desktop\Astrbot\data\skills\video-downloader\scripts\hellotik.py" "链接或分享文本" $env:TEMP
# 只要视频加 video 参数、只要图片加 image 参数（缺省全要）
```

**兜底链**（hellotik 报错/限速时按序降级）：
1. `scripts\dousnap.py`（免费，2026-08-11 实测视频/图文/BGM 全通，用法见「DouSnap 解析」章节；需登录 token，已配置）
2. `scripts\tikweb.py`（免费，SSSTik/SaveTik 双引擎，用法见「TikTok 网页解析」章节；SaveTik 宣称支持抖音但 2026-08-11 实测后端 statusCode 326 连不上，属机会性尝试，失败不恋战）
3. SnapAny（付费 1 credit，最后手段）

（`scripts\douyin_note.py` 与 yt-dlp 在 2026-08 改版后均已确认失效，移出主链；douyin_note 文档保留在下方仅供参考，不要再跑）

### douyin_note.py（旧路线，保留备用）

用移动端 UA 解析分享页的 `_ROUTER_DATA`：图文帖逐张下载原图，视频则把 `playwm` 换成 `play` 拿无水印直链。
**注意：2026-08 抖音改版后此脚本基本失效**（分享页不再内嵌数据），仅当 hellotik 不可用时尝试。

```powershell
python "<本skill目录>\scripts\douyin_note.py" "VIDEO_URL" $env:TEMP
# 用户明确要 BGM/音频时，末尾追加 audio 参数（图文帖 BGM 藏在 video.play_addr.uri，
# 注意不是 music.play_url——那个字段是空的；脚本输出 AUDIO:<path>）：
python "<本skill目录>\scripts\douyin_note.py" "VIDEO_URL" $env:TEMP audio
```

脚本输出 `Author:`、`Desc:` 以及每个已保存文件的完整路径（`IMG_n:`/`VIDEO:`/`AUDIO:`）。

**★★★ 拿到路径后必须按顺序执行，不许跳过 ★★★**

1. 把脚本输出的每个路径规范化为长路径（本机 `$env:TEMP` 含 `ADMINI~1` 短名称，必须转换）：

```powershell
(Get-Item "<脚本输出的路径>").FullName
```

2. 动图(webp/gif)先用 ffmpeg 转 mp4（见第 3 步）。静态 `.webp` 图片脚本已自动转成 `.jpeg`，无需处理。
3. **必须调用 `send_message_to_user` 发送文件**，每个文件一个组件，**按扩展名选类型**：
   - 图片（`.jpeg`/`.jpg`/`.png`/`.gif`）→ `{"type": "image", "path": "<规范化后的绝对长路径>"}`
   - 视频（`.mp4`）→ `{"type": "video", "path": "<规范化后的绝对长路径>"}`（禁止用 `file`，否则微信只显示成文件附件）
   图片用 `file` 类型发会只显示成文件不能预览！只发文字总结、不发组件 = 任务失败。
4. 如果某个路径 `Test-Path` 为 False，跳过该文件并在总结里说明。

## TikTok 网页解析（tikweb.py，SSSTik + SaveTik 双引擎，免费）

> ⚠️ **2026-08-11 现状**：本服务器直连 www.tiktok.com 连接超时（yt-dlp 报 connect timeout，必失败），**TikTok 链接一律走 tikweb.py**。第三方解析站及其 CDN（tikcdn.io / dl.snapcdn.app）可正常访问。

```powershell
python "C:\Users\Administrator\Desktop\Astrbot\data\skills\video-downloader\scripts\tikweb.py" "链接或分享文本" $env:TEMP
# 只要 MP3/音频：末尾追加 audio 参数
# 要 HD 原画：末尾追加 hd 参数（SaveTik 的 _original.mp4 原画通道；SaveTik 被限流时自动回退普通无水印版）
```

- **双引擎自动降级**：默认 SSSTik 优先（单 POST `/abc?url=dl` 出 tikcdn.io 无水印直链 + MP3），SaveTik 备选（主页抓 k_token/k_exp → ajaxSearch → JWT 直链）；`hd` 模式顺序反转（只有 SaveTik 有原画通道）
- **实测耗时**：SSSTik 解析+下载约 1~2 分钟（CDN 速度一般），audio 模式约 7 秒
- 输出与其他脚本对齐：`Text:`/`Author:`/`VIDEO:`/`AUDIO:`/`IMG_n:`；图文帖无视频时自动回退下载图片
- 支持短链（vm./vt./tiktok.com/t/）与整段分享文本，脚本内部自动提取 URL
- 拿到路径后按「抖音兜底」小节的 4 步后处理流程执行（长路径规范化 → send_message_to_user 发组件 → 清理）

**★★★ 限流警告（重要）★★**
- **SaveTik 限流极凶**：短时间内连续调用会先 429 后 403 IP 冷却封禁（2026-08-11 实测约 8 次请求后被封）。**同一轮对话最多解析一次 TikTok**，失败了就按错误处理告知用户，不要反复重试
- SSSTik 相对宽松，但也别刷屏
- 抖音链接走本脚本只是机会性尝试（SaveTik 抖音后端当前 326 损坏，SSSTik 不支持抖音）

## DouSnap 解析（dousnap.py，免费，抖音/B站利器）

> ⚠️ **2026-08-11 现状**：DouSnap.com 的 AES 协议已完整逆向（请求/响应全部 AES-128-CBC 加密，密钥固定）。**需要登录 token**（匿名拿不到异步结果），token 已存于 `scripts\dousnap_token.txt`（JWT 无过期声明，账号登出前长期有效；失效时找用户重新登录网站后在 Console 执行 `localStorage.getItem("auth_token")` 获取并更新文件）。
> 实测：抖音视频帖（1.8MB mp4 直链+文案）、抖音图文帖（自动回退下载 4 张图）、抖音 BGM（mp3）、B站（同步直出视频+MP3+字幕）全部通过。text 模式（口播转写）2026-08-11 深夜实测通过。

```powershell
python "C:\Users\Administrator\Desktop\Astrbot\data\skills\video-downloader\scripts\dousnap.py" "链接或分享文本" $env:TEMP
# 只要 MP3/BGM：末尾追加 audio 参数
# 要文案+口播转写：末尾追加 text 参数（不下载文件，输出 Text:/TRANSCRIPT:/SOURCE:）
```

- **流程**：POST doTask 创建任务 → 缓存命中时同步返回直链，否则轮询历史任务接口等结果（脚本内部完成，媒体最长 45 秒、转写最长 90 秒）
- **text 模式（文案/口播提取）**：语音转文字随解析任务附赠，无需额外接口。实测 77 秒口播视频约 13 秒出完整转写；同一链接重复解析秒回（服务端缓存）。纯音乐/静音视频转写为空时只输出文案行。B站外语视频会同时给中文翻译（TRANSCRIPT）和原文（SOURCE）。**适用场景**：用户发链接说"这个视频讲了什么/提取文案/转成文字/总结一下口播内容"——先跑 text 模式拿转写，再用转写内容直接回答或总结，**不必先下载视频**
- ⚠ **失败状态是 `FAILURE`**（不是 FAILED），且 `errorMessage` 字段成功时也会塞"视频处理成功!"，判定只看 status；脚本已内置，失败（如作品被平台风控审核）会带平台原话提前退出，不会傻等超时
- ⚠ 官方 queryTask 接口对抖音恒报"服务拥挤"（匿名/登录都一样，后端问题），脚本改走 userHistoryTasks 接口轮询，**不要自己去调 queryTask**
- 输出与其他脚本对齐：`Text:`/`VIDEO:`/`AUDIO:`/`IMG_n:`；图文帖无视频时自动回退下载图片
- ⚠ **接口不返回作者昵称**（title 恒为"暂无标题"）——结尾总结只有文案可用，博主名跳过或用"这位博主"带过
- 支持短链（v.douyin.com）与整段分享文本；图文帖图片是 douyinpic 签名 webp（带时效，拿到即下载，脚本已处理）
- **限流警告**：解析额度未知，**同一轮对话最多解析一次**，失败就降级下一环，别重试
- 抖音系 CDN（365yg/douyinpic）拒绝第三方 Referer，脚本已用裸 UA 下载，不要改动
- 拿到路径后按「抖音兜底」小节的 4 步后处理流程执行（长路径规范化 → send_message_to_user 发组件 → 清理）

## 音频 / BGM 提取

用户说"提取音频/BGM/音乐/原声"时：

- **抖音/快手图文帖**：跑对应兜底脚本时**末尾追加 `audio` 参数**，脚本额外输出 `AUDIO:<path>`（抖音是 mp3，快手图集是 m4a）
- **dousnap.py 也支持 audio 模式**：抖音视频帖/图文帖的 BGM 都能拿（R2 托管的 mp3），hellotik 限速时可作为音频兜底
- **视频帖要纯音频**：先按正常流程下载视频，再用 ffmpeg 抽音轨：
  ```powershell
  & "C:\ffmpeg\bin\ffmpeg.exe" -i "$env:TEMP\dl_media_video.mp4" -vn -c:a libmp3lame -q:a 2 "$env:TEMP\dl_media_audio.mp3" -y 2>&1 | Out-String
  ```
- **用户没提音频时不要加 audio 参数**（省流量）
- 音频文件用 `{"type": "file", "path": "..."}` 组件发送（不用 image/record）
- ⚠️ 抖音图文帖的 `music.play_url` 是**空的**，BGM 直链在 `video.play_addr.uri`（ies-music CDN 的 mp3）——不要自己去试第三方音乐接口，脚本已内置正确路径
- 脚本输出含 emoji 不会炸：脚本内部已做 UTF-8 防护；你自己写探测代码时也要 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`

## SnapAny 云端解析兜底（付费，1 credit/次）

本地脚本拿不到的媒体走 SnapAny（iiilab 引擎，服务端解析）。**典型场景：抖音图文帖的"动图/live 实况视频"**——分享页只有静态帧，SnapAny 能返回完整的 `douyinvod.com` mp4 直链（实测花火帖 11 秒动图原片）。

```powershell
# types 参数可选：video,image,audio 逗号分隔过滤（缺省全要）
python "C:\Users\Administrator\Desktop\Astrbot\data\skills\video-downloader\scripts\snapany.py" "链接或分享文本" $env:TEMP
python "C:\Users\Administrator\Desktop\Astrbot\data\skills\video-downloader\scripts\snapany.py" "链接或分享文本" $env:TEMP video
```

### Hellotik（免费，抖音首选 + 动图视频首选）

**免费**。解析机制：每周轮换的 WebCrypto AES-GCM 加密请求 + AES-CBC 响应解密（逆向见脚本注释）。返回结构含 title/type/cover/videos[]/pics[]。**2026-08-10 修复后实测：抖音视频帖 3 秒出片**（此前脚本有两处 bug：GCM 密文漏拼 16 字节 tag 导致服务端报"请求数据解密失败"、响应解密 NameError）。

```powershell
# 动图/live 视频首选
python "C:\Users\Administrator\Desktop\Astrbot\data\skills\video-downloader\scripts\hellotik.py" "链接" $env:TEMP video
# 限速时（stderr 提示 rate limited）降级用 snapany
```

- 输出与其他脚本对齐：`Text:`/`VIDEO:`/`IMG_n:`/`AUDIO:`
- 依赖：`pip install pycryptodome`（或 cryptography）；缺库时报错提示安装
- 每次运行会重新抓取动态配置（profile 每周轮换），**不要缓存旧 chunk**
- ⚠️ 限速策略：ticket 接口有 IP 限速（站点文案称约 10 分钟一次，实测 4 分钟内连续两次成功，限流较宽松但仍可能发生）；报 rate limited 时降级 douyin_note.py 或 snapany

- 输出与其他脚本对齐：`Text:`/`VIDEO:`/`IMG_n:`/`AUDIO:`
- key 在 skill 目录 `config.json`（已加入 .gitignore，**禁止提交**）；报错 `snapany_key missing` 就提示用户补 key
- **优先级规则**：本地脚本（douyin_note/kuaishou）永远优先（免费）；只有①本地拿不到用户要的媒体（如动图视频）②或用户明确要"原片/live/实况"时才用 snapany
- 每次成功调用消耗 1 credit，调用前无需请示但要在总结里说明消耗；失败（api error）不扣费
- 视频直链带时效签名，**拿到后立即在同一轮下载**，不要缓存 URL
- 集成策略调整（2026-08-05）：新增 hellotik.py 免费兜底；**动图/live 视频优先走 Hellotik（免费、10分钟限速），Hellotik 限速时降级 SnapAny（付费）**；图片/BGM 仍用本地脚本
- 集成策略调整（2026-08-11）：新增 tikweb.py（SSSTik+SaveTik 双引擎，免费，实测 video/audio/hd 三模式可用）；**TikTok 一律走 tikweb**（实测服务器直连 www.tiktok.com 超时，yt-dlp 对 TikTok 作废）；抖音链改为 hellotik → tikweb（机会性）→ snapany，douyin_note/yt-dlp 移出抖音主链
- 集成策略调整（2026-08-11 晚）：新增 dousnap.py（DouSnap.com 引擎，AES 协议已逆向，免费，登录 token 存于 scripts/dousnap_token.txt）；实测抖音视频/图文/BGM、B站全通；**抖音兜底链更新为 hellotik → dousnap → tikweb（机会性）→ snapany**；B站 412 风控新增 dousnap 兜底；小红书/快手失败时机会性尝试 dousnap（官方宣称支持，未验证）
- 集成策略调整（2026-08-11 深夜）：dousnap.py 新增 text 模式（文案+口播 ASR 转写，随解析任务免费附赠，无需额外接口，实测 77 秒视频约 13 秒出完整转写）；用户要"视频讲了什么/提取文案"时优先用它，不必下载视频；另确认平台失败状态为 FAILURE 且 errorMessage 不可作为失败判据

**拿不到就放弃，告诉用户"这个暂时下载不了"，不要继续尝试。**

## 图片合成视频（compose.py）

当帖子只有静态图片但用户想要视频格式时，用 ffmpeg 把图片合成为幻灯片视频 + 混入 BGM。

**适用场景**：
- 纯图文帖（无动图/live 内容）用户要求视频格式
- 所有 API 兜底都失败时的最后防线
- 用户明确说"做成视频"、"合成视频"、"幻灯片"

**不适用**：帖子有真实动图/live 视频时，优先用 Hellotik/SnapAny 拿原片，不要合成。

```powershell
# 用法：compose.py <outdir> [duration_per_image] [transition_type]
# duration_per_image: 每张图展示秒数（默认 3）
# transition_type: fade/slideleft/slideright/circleopen/dissolve（默认 fade）
python "C:\Users\Administrator\Desktop\Astrbot\data\skills\video-downloader\scripts\compose.py" $env:TEMP 3 fade
```

**前置条件**：outdir 中已有 `dl_media_img*.jpg/jpeg/png/webp` 图片（由 douyin_note.py 等下载）+ 可选 `dl_media_audio.mp3` BGM。

**输出**：`dl_media_composed.mp4`，脚本打印 `COMPOSED:<path>`。

**注意**：
- ffmpeg 必须可用（`C:\ffmpeg\bin\ffmpeg.exe` 或 PATH）
- 图片会统一缩放到 1080x1920（竖屏），黑边填充
- 有音频时自动混入，`-shortest` 截断到音频长度
- 合成后用 `send_message_to_user` 发送，按 Step 6 的 sleep+清理规则处理

## 网盘链接解析（百度网盘 / 夸克网盘）

用户粘贴网盘分享链接/分享文本时，这是文件不是视频，**跳过 yt-dlp**，直接运行对应脚本。两个脚本都走公益解析站，无需登录网盘账号。

| 网盘 | 脚本 | 能力 |
|---|---|---|
| 百度网盘 pan.baidu.com | `scripts\pan_baidu.py` | 支持文件夹递归（最多 3 层） |
| 夸克网盘 pan.quark.cn | `scripts\pan_quark.py` | 支持文件夹递归（最多 2 层） |

两个脚本都用多线程 Range 分片并行下载（公益站直链单连接限速严重，分片并行实测提速可达百倍），并实时刷新进度行（`DIR:`/`DL:`/`OK:`/`WARN:`）。

```powershell
# 末尾 zip 参数：下载完成后把所有文件打包成 dl_media_pan_all.zip，输出 ZIP:<path>
python "C:\Users\Administrator\Desktop\Astrbot\data\skills\video-downloader\scripts\pan_baidu.py" "完整分享文本(含提取码)" $env:TEMP 10 zip
python "C:\Users\Administrator\Desktop\Astrbot\data\skills\video-downloader\scripts\pan_quark.py" "完整分享文本(含提取码)" $env:TEMP 10 zip
```

> ⚠️ **执行方式（重要）**：网盘脚本**禁止设短 timeout**。调用 `astrbot_execute_shell` 时**不要传 timeout 参数**（让它以托管会话方式挂着跑），然后用 `astrbot_shell_session` poll（yield_time_ms 20000~30000）轮询进度直到 completed。之前出过事故：设了 600s 硬超时，多文件下载没跑完进程就被强杀，只抢救出部分文件。轮询时 stdout 能实时看到 `DL:`/`OK:` 进度行，可向用户播报；**不要中途 interrupt 重跑**。

### 长任务自动通知（必须遵守，防止"下完了却忘了发"）

脚本会实时写 `<输出目录>\pan_status.json`（字段：`running`/`done`/`total`/`processed`/`saved`/`current`/`files`/`zip`/`warns`），供外部检查进度。**AI 是被动触发的，对话一结束就"睡着"了，不会自己发现后台任务完成**——曾发生过下载完成后没人发送、用户干等的事故。所以启动网盘脚本时，若预计耗时较长（多文件 / 大文件 / 速度目测 <500KB/s），launch 托管会话后**必须**用 `future_task` 创建唤醒检查任务：

- `action=create`，`run_once=true`，`run_at` = 当前时间 +3 分钟，`name="网盘下载检查"`
- `note` 必须**自包含**（唤醒会话没有前文上下文），照抄模板并填好两个占位符：

> 检查网盘下载任务：读取 `<输出目录>\pan_status.json`。
> ① 文件不存在 = 任务已被处理或未启动，什么都不做，直接结束。
> ② done=true：把 zip 字段指向的文件（若无 zip 则把 files 列表里的文件逐个）发送给用户——长路径先规范化，用 send_message_to_user、session=`<用户会话ID>`、file 组件；按文件大小 sleep 等上传完成后用 python os.remove 清理所有已发文件**和 pan_status.json**；总结一句话即可，**不要主动列文件清单和 warns**（用户问起才据 files/warns 字段回答）。
> ③ done=false 且 running=true：任务还在跑，用 future_task 再排一个 +3 分钟的同样检查（把本 note 原样带上、更新检查次数）；若 total 字段 >0，给用户只发一行：`下载进度：<processed÷total 四舍五入>%`，**不加任何其他内容**。
> ④ 已重排 8 次（约 25 分钟）仍未完成：告知用户任务可能异常并停止排程，保留现场。

- **进度播报极简化**：轮询中或唤醒时播报进度一律只说"下载进度：X%"；只有用户明确询问时，才根据状态文件 files/warns 字段回答"下载了什么 / 哪些没下载及原因"

- `<用户会话ID>` 格式 `platform_id:message_type:session_id`（如 `CZAIY_BOT:FriendMessage:1209845636`、`CZAIY_BOT:GroupMessage:xxx`），从来消息上下文或此前 send_message_to_user 的返回中获取，**必须写进 note**，否则唤醒后发错会话
- 若你自己轮询时任务正好完成并已发送清理：无需额外处理——唤醒任务看到 pan_status.json 不存在会安静退出（这就是清理时必须连 pan_status.json 一起删的原因）
- 短任务（单小文件、预计 1 分钟内完成）不需要排唤醒任务，正常轮询等待即可

- 把用户发来的整段分享文本原样传入，脚本自动提取链接和提取码（支持 `?pwd=`、`提取码:xxxx` 等格式）
- **打包规则（省发送时间）**：多文件分享默认带 `zip` 参数——微信每发一个文件都要走一遍粘贴+发送流程，打包后只发一次，文档类还能压小体积；单文件不加；用户明确要"原文件/不要压缩"时也不加
- 输出 `Pan:`、`FILE_n:<path>`（未打包）或 `ZIP:<path>`（打包后）、`COUNT:`；下载文件名带 `dl_media` 前缀，沿用第 6 步的清理规则；同时实时写 `pan_status.json` 状态文件（供唤醒任务检查，发送清理时要一起删）
- 单个文件下载失败会自动重试 3 次（覆盖 5xx/522/断连等瞬时错误），仍失败才记 WARN + `pan_status.json` 的 warns 并跳过
- 拿到路径后按「抖音兜底」小节的后处理流程执行：长路径规范化 → `send_message_to_user` 发 file 组件（多文件发多个组件）→ sleep+清理
- 限制：单文件 ≤500MB（超了自动跳过并输出 WARN）；百度文件夹最多递归 3 层；夸克文件夹最多递归 2 层
- **夸克解析密码**：存在 skill 目录 `config.json` 的 `quark_parse_pwd` 字段（已 gitignore）。密码**每日轮换**，获取步骤（短剧名/集数会变，以官方文档为准）：https://www.yuque.com/wpurl/vp60ux/xu3codnavvxzdgr9（大致流程：快手极速版搜指定关键词→第一个短剧→文档指定集数→第一句字幕台词）。报"解析密码错误"时先重新抓取该文档确认最新步骤，再提示用户重新获取并更新 config，不要反复重试
- 百度报错含 `-20` = 触发百度验证码，直接告知用户暂不能解析，不要重试
- 公益站可能限速/抽风，失败就按错误处理话术告知，不要死磕

## 错误处理

失败时简短告知，不要反复重试：
- "哎呀没下载成功 😣 可能这个要登录才能看"
- "这个暂时下载不了，链接可能过期了"
- "这个暂时下不了，可能是会员/付费内容"
- B 站报 `412 Precondition Failed`：是 B 站风控拦了服务器 IP，不是命令写错了，别换命令折腾；可提示用户提供 cookies（--cookies-from-browser 或 cookies 文件）再试一次

## 绝对不要用 rm / Remove-Item 删文件，清理一律用上面的 python os.remove

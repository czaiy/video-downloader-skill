# -*- coding: utf-8 -*-
"""
dousnap.py - DouSnap.com 解析引擎（抖音/小红书/快手/B站/微信视频号），纯标准库 + pycryptodome。

侦查结论（2026-08-11 实测）：
  站点: https://www.dousnap.com （Nuxt SPA，主打"文案提取"，但 create 接口同步吐媒体直链）
  API : https://www.dousnap.com/prod-api
  协议: 全站请求/响应 AES-128-CBC + ZeroPadding，base64 传输
        KEY = aaDJL2d9DfhLZO0z   IV = 412ADDSSFA342442
        POST body = JSON.stringify(base64密文)
        GET  query = ?data=<base64密文>  （密文 = AES(JSON字符串)）
        响应为 base64 密文，解密后是 JSON；少数错误响应是明文 JSON。

  流程（必须带登录 token，匿名查不到异步结果）：
    1. POST /transcript/doTask
       明文 body: {"appType":"douchong","workUrl":"<链接>","type":"text","targetLanguage":"zh"}
       头: Authorization: Bearer <token>, Content-Type: application/json
       返回 data 可能同步带结果（缓存命中，如 B站/重复链接），
       否则只有 taskId（抖音/小红书等走异步）。
    2. 轮询 GET /ai-face/userHistoryTasks?data=<enc({})>
       ⚠ 官方的 /transcript/queryTask 实测对抖音恒 500 "服务拥挤"（匿名/登录都一样），
       但历史任务接口能拿到已完成任务的完整结果——用它代替轮询。
       按 taskId 匹配 rows；行内 videoUrl 非空或 imageUrlList 非空即完成。
    3. 结果字段: content=文案, videoUrl=视频直链(365yg/douyin CDN),
       audioUrl=MP3(R2), cover=封面, imageUrlList=图文帖图片(douyinpic 签名 webp)。
       ⚠ 无作者昵称字段；title 恒为"暂无标题"，别用。
    4. 图文帖: videoUrl=="" 且 imageUrlList 有值 → 回退下载图片。

  Token: 环境变量 DOUSNAP_TOKEN，或脚本同目录 dousnap_token.txt（一行 JWT）。
         JWT 无 exp 声明，登出前长期有效。

  限制: 同轮对话最多解析一次，勿重试刷接口；抖音图文/视频均可，
        TikTok(国际版)不在其支持列表。

用法:
    python dousnap.py "<链接或分享文本>" <输出目录> [video|audio|text]
      video(默认): 下载视频；视频不存在时回退下载图文帖图片
      audio:       只下载 MP3/BGM
      text:        只拿文案+口播转写（不下载文件）；语音转文字随任务附赠，
                   ASR 需要时间，最长等 90 秒

输出(stdout)与其他脚本对齐:
    Text:<文案>
    Author:<作者>
    VIDEO:<path>
    AUDIO:<path>
    IMG_n:<path>
    TRANSCRIPT:<口播转写>   （text 模式，textContent 字段）
    SOURCE:<原语言转写>     （text 模式，sourceText 与 textContent 不同时才输出，
                             如 B站外语视频的原文 vs 中文翻译）
退出码: 0 成功, 1 失败。失败原因打印到 stderr。
"""
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from Crypto.Cipher import AES
except ImportError:
    print("dousnap.py needs pycryptodome: pip install pycryptodome", file=sys.stderr)
    sys.exit(1)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
PREFIX = "dl_media"
API = "https://www.dousnap.com/prod-api"
KEY = b"aaDJL2d9DfhLZO0z"
IV = b"412ADDSSFA342442"
POLL_MAX = 45      # 秒（video/audio 模式等媒体）
POLL_GAP = 3       # 秒
TEXT_POLL_MAX = 90  # 秒（text 模式等 ASR 转写）

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------------- AES 协议 ----------------

def _pad(b):
    return b + b"\x00" * ((16 - len(b) % 16) % 16)


def enc_payload(obj):
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    ct = AES.new(KEY, AES.MODE_CBC, IV).encrypt(_pad(s.encode("utf-8")))
    return base64.b64encode(ct).decode("ascii")


def dec_payload(text):
    """解密响应；失败则尝试当作明文 JSON。返回 dict/list。"""
    text = (text or "").strip()
    try:
        raw = AES.new(KEY, AES.MODE_CBC, IV).decrypt(base64.b64decode(text))
        return json.loads(raw.rstrip(b"\x00").decode("utf-8", "replace"))
    except Exception:
        try:
            return json.loads(text)
        except Exception:
            raise EngineError("undecodable response: %s" % text[:120])


class EngineError(Exception):
    pass


def get_token():
    tok = os.environ.get("DOUSNAP_TOKEN", "").strip()
    if tok:
        return tok
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dousnap_token.txt")
    try:
        with open(p, "r", encoding="utf-8") as f:
            tok = f.read().strip()
    except OSError:
        pass
    return tok


def api_call(opener, token, method, path, payload):
    url = API + path
    headers = {
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://www.dousnap.com",
        "Referer": "https://www.dousnap.com/",
        "Authorization": "Bearer " + token,
    }
    if method == "POST":
        headers["Content-Type"] = "application/json"
        body = json.dumps(enc_payload(payload)).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers)
    else:
        q = urllib.parse.urlencode({"data": enc_payload(payload)})
        req = urllib.request.Request(url + "?" + q, headers=headers)
    try:
        resp = opener.open(req, timeout=90)
        text = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise EngineError("http %s on %s" % (e.code, path))
    except Exception as e:
        raise EngineError("request fail %s: %r" % (path, e))
    j = dec_payload(text)
    if not isinstance(j, dict):
        raise EngineError("unexpected response shape on %s" % path)
    return j


def extract_url(text):
    m = re.search(r"https?://[A-Za-z0-9.\-_~:/?#\[\]@!$&'()*+,;=%]+", text or "")
    if not m:
        return None
    return m.group(0).rstrip(".,;，。！？、）】)")


def opener_of():
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=CTX))


# ---------------- 解析流程 ----------------

def create_task(opener, token, url):
    j = api_call(opener, token, "POST", "/transcript/doTask",
                 {"appType": "douchong", "workUrl": url,
                  "type": "text", "targetLanguage": "zh"})
    if j.get("code") != 200:
        raise EngineError("doTask code=%s msg=%s" % (j.get("code"), j.get("msg")))
    data = j.get("data") or {}
    if not data.get("taskId"):
        raise EngineError("doTask no taskId")
    return data


def row_ready(row):
    return bool((row.get("videoUrl") or "").strip()) or bool(row.get("imageUrlList"))


def poll_history(opener, token, task_id, ready=row_ready, timeout=POLL_MAX):
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(POLL_GAP)
        try:
            j = api_call(opener, token, "GET", "/ai-face/userHistoryTasks",
                         {"pageNum": 1, "pageSize": 20})
        except EngineError as e:
            log("history poll fail: %s" % e)
            continue
        for row in (j.get("rows") or []):
            if row.get("taskId") == task_id:
                # 注意: errorMessage 是通用消息字段，成功时也会塞"视频处理成功!"，
                # 只能以 status 判定；失败状态实际为 "FAILURE"
                if row.get("status") in ("FAILED", "FAILURE"):
                    raise EngineError("task failed: %s"
                                      % (row.get("errorMessage") or "unknown error"))
                if ready(row):
                    return row
                log("task row present but not ready yet")
                break
    return None


def resolve_transcript(opener, token, data, timeout=TEXT_POLL_MAX):
    """text 模式: 等待 ASR 转写完成。create 响应已带 textContent 直接用，
    否则轮询历史直到 textContent 出现；任务完成但转写为空（纯音乐等）
    也把 row 返回，由调用方决定降级策略。"""
    if data.get("status") == "SUCCESS" and data.get("textContent"):
        return data
    row = poll_history(opener, token, data.get("taskId"),
                       ready=lambda r: bool((r.get("textContent") or "").strip())
                       or r.get("status") == "SUCCESS",
                       timeout=timeout)
    if row is None:
        raise EngineError("transcript not ready within %ds (taskId=%s)"
                          % (timeout, data.get("taskId")))
    return row


# ---------------- 下载 ----------------

def looks_like_mp4(path):
    try:
        with open(path, "rb") as f:
            head = f.read(64)
        return b"ftyp" in head
    except OSError:
        return False


def download(opener, url, dest, referer=None):
    # 注意: 抖音系 CDN(365yg/douyinpic) 会拒绝第三方 Referer，裸 UA 请求反而稳定
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    resp = opener.open(req, timeout=180)
    written = 0
    with open(dest, "wb") as f:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            written += len(chunk)
    log("downloaded %s (%d bytes)" % (dest, written))
    return written


def img_ext(url):
    if "webp" in url:
        return ".webp"
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1]
    return ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else ".webp"


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    text = sys.argv[1]
    outdir = sys.argv[2]
    want = sys.argv[3].lower() if len(sys.argv) > 3 else "video"
    if want != "text":
        os.makedirs(outdir, exist_ok=True)

    token = get_token()
    if not token:
        log("no DOUSNAP_TOKEN (env or dousnap_token.txt)")
        return 1

    url = extract_url(text)
    if not url:
        log("no url found in input")
        return 1
    log("target url: %s (want=%s)" % (url, want))

    opener = opener_of()
    try:
        data = create_task(opener, token, url)
        log("taskId=%s sync_media=%s" % (data.get("taskId"), bool(row_ready(data))))
        if want == "text":
            row = resolve_transcript(opener, token, data)
        elif row_ready(data):
            row = data
        else:
            row = poll_history(opener, token, data["taskId"])
            if row is None:
                raise EngineError("task %s not finished within %ds "
                                  "(backend queue busy or link unsupported)"
                                  % (data["taskId"], POLL_MAX))
    except EngineError as e:
        log("dousnap fail: %s" % e)
        return 1

    content = (row.get("content") or "").strip()
    video_url = (row.get("videoUrl") or "").strip()
    audio_url = (row.get("audioUrl") or "").strip()
    images = row.get("imageUrlList") or []

    if content:
        print("Text:%s" % content)
    # 接口不提供作者昵称，Author 省略（与其他脚本"有才输出"一致）

    if want == "text":
        transcript = (row.get("textContent") or "").strip()
        source = (row.get("sourceText") or "").strip()
        if not transcript and not content:
            log("no transcript and no caption for this task")
            return 1
        if transcript:
            print("TRANSCRIPT:%s" % transcript)
            if source and source != transcript:
                print("SOURCE:%s" % source)
        else:
            log("caption present but speech transcript empty (pure music / silent video?)")
        return 0

    saved = []
    try:
        if want == "audio":
            if not audio_url:
                log("no audio url in result")
                return 1
            dest = os.path.join(outdir, PREFIX + "_audio.mp3")
            download(opener, audio_url, dest)
            print("AUDIO:%s" % dest)
            saved.append(dest)
        else:
            if video_url:
                dest = os.path.join(outdir, PREFIX + "_video.mp4")
                download(opener, video_url, dest)
                if not looks_like_mp4(dest):
                    log("warning: %s does not look like mp4" % dest)
                print("VIDEO:%s" % dest)
                saved.append(dest)
            elif images:
                log("no video link, falling back to %d images" % len(images))
            else:
                log("result has no video/image media")
                return 1
            if not video_url and images:
                for i, img in enumerate(images, 1):
                    dest = os.path.join(outdir, "%s_img%d%s" % (PREFIX, i, img_ext(img)))
                    try:
                        download(opener, img, dest)
                        print("IMG_%d:%s" % (i, dest))
                        saved.append(dest)
                    except Exception as e:
                        log("image %d fail: %r" % (i, e))
    except urllib.error.HTTPError as e:
        log("download http error %s" % e.code)
        return 1
    except Exception as e:
        log("download fail: %r" % e)
        return 1

    if not saved:
        log("nothing saved")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

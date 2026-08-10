# -*- coding: utf-8 -*-
"""
tikweb.py - TikTok 网页解析双引擎兜底（SSSTik.io + SaveTik.co），纯标准库。

侦查结论（2026-08-11 实测）：
  SSSTik.io（首选，单 POST 出直链）：
    1. GET https://ssstik.io/ （建立会话，模拟浏览器）
    2. POST https://ssstik.io/abc?url=dl  form: id=<链接> locale=en tt=c3NzdGlr
       必须带 htmx 特征头：HX-Request/HX-Trigger/HX-Target/HX-Current-URL
    3. 响应是 HTML 片段：
       - 作者 <h2>..</h2>、文案 <p class="maintext">..</p>
       - 无水印视频: href="https://tikcdn.io/ssstik/<视频id>?st=..&e=.."
       - MP3: class 含 music 的锚点 href="https://tikcdn.io/ssstik/m/<b64透传>"
       - 图文帖: tikcdn.io 图片锚点（尽力提取）
    4. HD 按钮走广告奖励流（data-directurl 二段请求实测 403），放弃；
       带水印 /m/<视频b64> 通道不用。
    5. 抖音链接不支持（返回 error panel）。

  SaveTik.co（备选，提供 HD 原画通道）：
    1. GET https://savetik.co/zh-cn 抓内嵌 k_token / k_exp（每次抓取都是新鲜的）
    2. POST https://savetik.co/api/ajaxSearch  form: q=<链接> lang=zh-cn token exp
       头: X-Requested-With: XMLHttpRequest
    3. 响应 JSON: {status:"ok", data:"<html>"}；
       异常: statusCode 404=视频删除/私密, 326=上游连不上（抖音一律 326，后端已坏）；
       请求过快会返回 429 HTML（nginx 层限流，不是 JSON）。
    4. data HTML 锚点（href 都是 https://dl.snapcdn.app/get?token=<JWT>）：
       - "下载 MP4 HD" -> JWT 指向 v16.tokcdn.com 的 _original.mp4（原画）
       - "下载 MP4"    -> JWT 指向 tiktokcdn 标准无水印 mp4
       - "下载 MP3"    -> JWT 指向 ies-music 音频
       JWT 直接 GET 即可下载（带 Referer: savetik.co），payload.url 是真实 CDN。
    5. 抖音宣称支持，实测 statusCode 326（2026-08-11），仅机会性尝试。

用法:
    python tikweb.py "<链接或分享文本>" <输出目录> [video|audio|hd]
      video(默认): 下载无水印视频；视频不存在时回退下载图文帖图片
      audio:       只下载 MP3/BGM
      hd:          优先 SaveTik 的 HD 原画通道，失败回退普通无水印

输出(stdout)与其他脚本对齐:
    Text:<文案>
    Author:<作者>
    VIDEO:<path>
    AUDIO:<path>
    IMG_n:<path>
退出码: 0 成功, 1 失败。失败原因打印到 stderr。
"""
import html as html_mod
import http.cookiejar
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
PREFIX = "dl_media"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def make_opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPSHandler(context=CTX))


def fetch(opener, url, data=None, headers=None, timeout=60):
    """返回 (status, body_text)。HTTP 错误抛 EngineError。"""
    hdrs = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    if headers:
        hdrs.update(headers)
    body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
    if body is not None:
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    req = urllib.request.Request(url, data=body, headers=hdrs)
    resp = opener.open(req, timeout=timeout)
    return resp.status, resp.read().decode("utf-8", "replace")


def extract_url(text):
    m = re.search(r"https?://[A-Za-z0-9.\-_~:/?#\[\]@!$&'()*+,;=%]+", text or "")
    if not m:
        return None
    return m.group(0).rstrip(".,;，。！？、）】)")


def strip_tags(s):
    return html_mod.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


class EngineError(Exception):
    pass


# ---------------- SSSTik ----------------

def parse_ssstik(page):
    meta = {"engine": "ssstik", "author": "", "title": "",
            "video": None, "audio": None, "images": []}
    m = re.search(r"<h2>(.*?)</h2>", page, re.S)
    if m:
        meta["author"] = strip_tags(m.group(1))
    m = re.search(r'<p class="maintext">(.*?)</p>', page, re.S)
    if m:
        meta["title"] = strip_tags(m.group(1))
    # 无水印视频: tikcdn.io/ssstik/<数字id>?st=
    m = re.search(r'href="(https://tikcdn\.io/ssstik/\d+[^"]*)"', page)
    if m:
        meta["video"] = html_mod.unescape(m.group(1))
    # MP3: class 含 music 的锚点
    m = re.search(r'<a href="([^"]+)"[^>]*class="[^"]*\bmusic\b[^"]*"', page)
    if m:
        meta["audio"] = html_mod.unescape(m.group(1))
    # 图文帖图片（尽力提取: /img/ 路径或明确 image class）
    for m in re.finditer(r'<a href="(https://tikcdn\.io/[^"]+)"[^>]*class="[^"]*(?:image|photo)[^"]*"', page):
        meta["images"].append(html_mod.unescape(m.group(1)))
    if not meta["images"]:
        for m in re.finditer(r'href="(https://tikcdn\.io/ssstik/img/[^"]+)"', page):
            meta["images"].append(html_mod.unescape(m.group(1)))
    return meta


def engine_ssstik(opener, url):
    try:
        opener.open("https://ssstik.io/", timeout=30).read()
    except Exception as e:
        raise EngineError("ssstik homepage fail: %r" % e)
    headers = {
        "Referer": "https://ssstik.io/",
        "HX-Request": "true",
        "HX-Trigger": "_gcaptcha_pt",
        "HX-Target": "target",
        "HX-Current-URL": "https://ssstik.io/",
    }
    try:
        status, page = fetch(opener, "https://ssstik.io/abc?url=dl",
                             data={"id": url, "locale": "en", "tt": "c3NzdGlr"},
                             headers=headers, timeout=60)
    except urllib.error.HTTPError as e:
        raise EngineError("ssstik post http %s" % e.code)
    except Exception as e:
        raise EngineError("ssstik post fail: %r" % e)
    if 'class="panel error"' in page or ("warning" in page[:400] and "tikcdn.io" not in page):
        raise EngineError("ssstik error panel (link invalid or unsupported platform)")
    meta = parse_ssstik(page)
    if not (meta["video"] or meta["audio"] or meta["images"]):
        raise EngineError("ssstik no media in response")
    return meta


# ---------------- SaveTik ----------------

def parse_savetik(data_html):
    meta = {"engine": "savetik", "author": "", "title": "",
            "video": None, "hd": None, "audio": None, "images": []}
    m = re.search(r"<h3>(.*?)</h3>", data_html, re.S)
    if m:
        meta["title"] = strip_tags(m.group(1))
    for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', data_html, re.S):
        href = html_mod.unescape(m.group(1))
        label = strip_tags(m.group(2)).lower()
        if not href.startswith("https://dl.snapcdn.app/get"):
            continue
        if "mp4" in label and "hd" in label:
            meta["hd"] = href
        elif "mp4" in label and not meta["video"]:
            meta["video"] = href
        elif "mp3" in label:
            meta["audio"] = href
        elif any(k in label for k in ("图片", "img", "image", "photo", "picture")):
            meta["images"].append(href)
    return meta


def engine_savetik(opener, url):
    try:
        status, home = fetch(opener, "https://savetik.co/zh-cn", timeout=30)
    except Exception as e:
        raise EngineError("savetik homepage fail: %r" % e)
    tk = re.search(r'k_token="([0-9a-f]+)"', home)
    ex = re.search(r'k_exp="(\d+)"', home)
    if not (tk and ex):
        raise EngineError("savetik token/exp not found in homepage")
    try:
        status, raw = fetch(opener, "https://savetik.co/api/ajaxSearch",
                            data={"q": url, "lang": "zh-cn",
                                  "token": tk.group(1), "exp": ex.group(1)},
                            headers={"Referer": "https://savetik.co/zh-cn",
                                     "X-Requested-With": "XMLHttpRequest"},
                            timeout=60)
    except urllib.error.HTTPError as e:
        raise EngineError("savetik search http %s (429=rate limited)" % e.code)
    except Exception as e:
        raise EngineError("savetik search fail: %r" % e)
    try:
        j = json.loads(raw)
    except ValueError:
        raise EngineError("savetik non-json response (likely 429 rate limited)")
    if j.get("status") != "ok":
        raise EngineError("savetik status != ok: %s" % raw[:160])
    sc = j.get("statusCode")
    if sc:
        raise EngineError("savetik statusCode=%s %s" % (sc, j.get("msg", "")))
    data_html = j.get("data") or ""
    if not data_html.strip():
        raise EngineError("savetik empty data (video not found)")
    meta = parse_savetik(data_html)
    if not (meta["video"] or meta["hd"] or meta["audio"] or meta["images"]):
        raise EngineError("savetik no snapcdn links in data")
    return meta


# ---------------- download ----------------

def looks_like_mp4(path):
    try:
        with open(path, "rb") as f:
            head = f.read(64)
        return b"ftyp" in head
    except OSError:
        return False


def download_media(opener, url, dest, referer):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer})
    resp = opener.open(req, timeout=120)
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


def ext_for(dest, fallback):
    return dest if os.path.splitext(dest)[1] else dest + fallback


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    text = sys.argv[1]
    outdir = sys.argv[2]
    want = sys.argv[3].lower() if len(sys.argv) > 3 else "video"
    os.makedirs(outdir, exist_ok=True)

    url = extract_url(text)
    if not url:
        log("no url found in input")
        return 1
    log("target url: %s (want=%s)" % (url, want))
    is_douyin = "douyin.com" in url

    engines = ([engine_savetik, engine_ssstik] if want == "hd"
               else [engine_ssstik, engine_savetik])

    meta = None
    for eng in engines:
        try:
            meta = eng(make_opener(), url)
            log("engine ok: %s" % meta["engine"])
            break
        except EngineError as e:
            log("engine fail [%s]: %s" % (eng.__name__, e))
        except Exception as e:
            log("engine crash [%s]: %r" % (eng.__name__, e))
    if meta is None:
        log("all engines failed")
        return 1

    referer = ("https://ssstik.io/" if meta["engine"] == "ssstik"
               else "https://savetik.co/")
    opener = make_opener()
    saved = []

    if meta["title"]:
        print("Text:%s" % meta["title"])
    if meta["author"]:
        print("Author:%s" % meta["author"])

    try:
        if want == "audio":
            if not meta["audio"]:
                log("no audio link from engine %s" % meta["engine"])
                return 1
            dest = os.path.join(outdir, PREFIX + "_audio.mp3")
            download_media(opener, meta["audio"], dest, referer)
            print("AUDIO:%s" % dest)
            saved.append(dest)
        else:
            video_url = None
            if want == "hd":
                video_url = meta.get("hd") or meta.get("video")
            else:
                video_url = meta.get("video") or meta.get("hd")
            if video_url:
                dest = os.path.join(outdir, PREFIX + "_video.mp4")
                download_media(opener, video_url, dest, referer)
                if not looks_like_mp4(dest):
                    log("warning: %s does not look like mp4" % dest)
                print("VIDEO:%s" % dest)
                saved.append(dest)
            elif meta["images"]:
                log("no video link, falling back to %d images" % len(meta["images"]))
            else:
                log("engine returned no downloadable media for want=%s" % want)
                return 1
            # 图文帖图片（无视频时兜底，或图文帖本身）
            if not video_url and meta["images"]:
                for i, img in enumerate(meta["images"], 1):
                    dest = os.path.join(outdir, "%s_img%d.jpg" % (PREFIX, i))
                    try:
                        download_media(opener, img, dest, referer)
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

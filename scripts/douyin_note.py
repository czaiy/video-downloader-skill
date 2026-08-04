#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
douyin_note.py - Douyin/TikTok(CN) watermark-free fallback extractor.

Usage:
    python douyin_note.py <share_url> <output_dir>

What it does:
  1. Resolve the short share link (v.douyin.com etc.) with a mobile UA.
  2. Extract the video/note id and fetch the iesdouyin share page.
  3. Parse the embedded _ROUTER_DATA JSON.
  4. For image notes: download every image (no watermark).
  5. For videos: get the play address and swap "playwm" -> "play" to
     obtain the watermark-free source, then download it.

Output (stdout), one line per item:
    Author:<nickname>
    Desc:<description>
    IMG_1:<saved file path>
    VIDEO:<saved file path>

Exit code 0 on success, non-zero on failure. Pure stdlib, no deps.
"""
import json
import os
import re
import ssl
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)
TIMEOUT = 20

try:
    _ctx = ssl.create_default_context()
except Exception:  # pragma: no cover
    _ctx = None


def http_get(url, referer=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": MOBILE_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        **({"Referer": referer} if referer else {}),
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as resp:
        return resp.geturl(), resp.read()


def resolve_share_id(url):
    """Follow redirects of the short link and pull out video/note id."""
    final_url, _ = http_get(url)
    m = re.search(r"(?:video|note|slides)/(\d+)", final_url)
    if m:
        return m.group(1)
    # Some links carry modal_id=xxxx
    m = re.search(r"modal_id=(\d+)", final_url)
    if m:
        return m.group(1)
    m = re.search(r"/(\d{15,25})", final_url)
    return m.group(1) if m else None


def fetch_router_data(item_id):
    for kind in ("note", "video"):
        share_url = f"https://www.iesdouyin.com/share/{kind}/{item_id}/"
        try:
            _, html = http_get(share_url)
            text = html.decode("utf-8", "ignore")
            m = re.search(r"_ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>", text, re.DOTALL)
            if m:
                data = json.loads(m.group(1))
                for v in data.get("loaderData", {}).values():
                    if isinstance(v, dict) and "videoInfoRes" in v:
                        items = v["videoInfoRes"].get("item_list", [])
                        if items:
                            return items[0]
        except Exception:
            continue
    return None


def long_path(p):
    """Return the absolute long-form path (expand 8.3 short names on Windows)."""
    p = os.path.abspath(p)
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(4096)
            n = ctypes.windll.kernel32.GetLongPathNameW(p, buf, 4096)
            if 0 < n < 4096:
                return buf.value
        except Exception:
            pass
    return p


def ensure_jpeg(path):
    """Convert .webp to .jpeg so WeChat can display it inline
    (WeChat/.NET SetImage does not understand webp). Requires PIL;
    falls back to keeping the webp when PIL is unavailable."""
    if not path.lower().endswith(".webp"):
        return path
    try:
        from PIL import Image
    except ImportError:
        return path
    try:
        im = Image.open(path)
        im.load()
        if im.mode in ("RGBA", "LA", "P", "PA"):
            rgba = im.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        out = path[:-5] + ".jpeg"
        im.save(out, "JPEG", quality=95)
        try:
            os.remove(path)
        except OSError:
            pass
        return out
    except Exception as e:
        print(f"jpeg convert failed ({e}), keeping webp", file=sys.stderr)
        return path


def jpeg_variant(url):
    """Douyin tplv CDN serves the same signed asset as jpeg when the
    extension is swapped (e.g. :q80.webp -> :q80.jpeg)."""
    return re.sub(r"(:q\d+)\.webp(?=\?|$)", r"\1.jpeg", url)


def extract_bgm_url(item):
    """Find the BGM direct link. For image notes the full mp3 URL sits in
    video.play_addr.uri (ies-music CDN); music.play_url is usually empty."""
    pa = (item.get("video") or {}).get("play_addr") or {}
    uri = pa.get("uri", "")
    if isinstance(uri, str) and uri.startswith("http") and (".mp3" in uri or "ies-music" in uri):
        return uri
    for u in (pa.get("url_list") or []):
        if isinstance(u, str) and u.startswith("http") and ".mp3" in u and "playwm" not in u:
            return u
    mu = (item.get("music") or {}).get("play_url")
    if isinstance(mu, str) and mu.startswith("http"):
        return mu
    if isinstance(mu, dict):
        urls = mu.get("url_list") or []
        if urls:
            return urls[-1]
    return None


def save(url, path, referer=None):
    _, blob = http_get(url, referer=referer)
    with open(path, "wb") as f:
        f.write(blob)
    return long_path(path)


def main():
    if len(sys.argv) < 3:
        print("usage: douyin_note.py <share_url> <output_dir> [audio]", file=sys.stderr)
        return 2
    url, outdir = sys.argv[1], sys.argv[2]
    want_audio = len(sys.argv) > 3 and sys.argv[3].lower() in ("audio", "--audio", "bgm")
    os.makedirs(outdir, exist_ok=True)

    item_id = resolve_share_id(url)
    if not item_id:
        print("could not resolve item id from share url", file=sys.stderr)
        return 1

    item = fetch_router_data(item_id)
    if not item:
        print("could not fetch router data", file=sys.stderr)
        return 1

    author = (item.get("author") or {}).get("nickname", "")
    desc = item.get("desc", "")
    print(f"Author:{author}")
    print(f"Desc:{desc}")

    # Image note / photo post
    images = item.get("images") or []
    if images:
        for i, img in enumerate(images, 1):
            urls = img.get("url_list") or []
            if not urls:
                continue
            img_url = urls[-1]
            jpeg_url = jpeg_variant(img_url)
            path = None
            if jpeg_url != img_url:
                try:
                    path = save(jpeg_url, os.path.join(outdir, f"dl_media_img{i}.jpeg"),
                                referer="https://www.douyin.com/")
                except Exception:
                    path = None
            if not path:
                ext = ".jpeg" if ".jpeg" in img_url or ".jpg" in img_url else ".webp"
                path = save(img_url, os.path.join(outdir, f"dl_media_img{i}{ext}"),
                            referer="https://www.douyin.com/")
                path = ensure_jpeg(path)
            print(f"IMG_{i}:{path}")
        if want_audio:
            audio_url = extract_bgm_url(item)
            if audio_url:
                try:
                    apath = save(audio_url, os.path.join(outdir, "dl_media_audio.mp3"),
                                 referer="https://www.douyin.com/")
                    print(f"AUDIO:{apath}")
                except Exception as e:
                    print(f"bgm download failed: {e}", file=sys.stderr)
            else:
                print("no bgm direct link found", file=sys.stderr)
        return 0

    # Single video: prefer watermark-free "play" address
    video = item.get("video") or {}
    play = (video.get("play_addr") or {}).get("url_list") or []
    if not play:
        print("no playable address found", file=sys.stderr)
        return 1
    play_url = play[-1].replace("playwm", "play").replace("http://", "https://")
    path = save(play_url, os.path.join(outdir, "dl_media_video.mp4"),
                referer="https://www.douyin.com/")
    print(f"VIDEO:{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

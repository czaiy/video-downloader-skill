#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kuaishou.py - Kuaishou (快手) watermark-free fallback extractor.

Usage:
    python kuaishou.py <share_url_or_text> <output_dir>

What it does:
  1. Extract the share link (v.kuaishou.com/xxx) from raw share text.
  2. Resolve it with a mobile UA; it 302-redirects to the mobile share
     page on v.m.chenzhongtech.com/fw/photo/<photoId>.
  3. Parse the embedded window.INIT_STATE JSON. The route keys are
     obfuscated (caesar-shifted) but all values are intact.
  4. Locate the photo object carrying mainMvUrls -> watermark-free mp4
     CDN links (kwimgs.com / yximgs.com), plus caption / userName.
  5. Download the video (or cover image for picture posts).

Output (stdout), one line per item:
    Author:<nickname>
    Desc:<description>
    VIDEO:<saved file path>
    IMG_1:<saved file path>   (picture posts only)

Exit code 0 on success, non-zero on failure. Pure stdlib, no deps.
Note: Kuaishou caps source quality at ~720p; that is a platform limit.
"""
import json
import os
import re
import ssl
import sys
import urllib.request

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)
TIMEOUT = 20
REFERER = "https://v.m.chenzhongtech.com/"

try:
    _ctx = ssl.create_default_context()
except Exception:  # pragma: no cover
    _ctx = None


def http_get(url, referer=None, max_bytes=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": MOBILE_UA,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        **({"Referer": referer} if referer else {}),
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as resp:
        if max_bytes:
            return resp.geturl(), resp.read(max_bytes)
        return resp.geturl(), resp.read()


def extract_url(text):
    """Pull a usable kuaishou link out of raw share text."""
    m = re.search(r"(https?://v\.kuaishou\.com/[A-Za-z0-9]+)", text)
    if m:
        return m.group(1)
    m = re.search(r"(https?://[^\s\u4e00-\u9fff\"'，。、！？]+)", text)
    return m.group(1) if m else None


def fetch_init_state(url):
    final_url, html_bytes = http_get(url)
    text = html_bytes.decode("utf-8", "ignore")
    m = re.search(r"window\.INIT_STATE\s*=\s*(\{.*)", text)
    if not m:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(m.group(1))
    except ValueError:
        return None
    return data


def find_photo(data):
    """Recursively locate the photo object (video or atlas/image post)."""
    found = {}

    def walk(d):
        if "photo" in found:
            return
        if isinstance(d, dict):
            if "photoId" in d and "userName" in d:
                found["photo"] = d
                return
            for v in d.values():
                walk(v)
        elif isinstance(d, list):
            for v in d:
                walk(v)

    walk(data)
    return found.get("photo")


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


def save(url, path, referer=REFERER):
    _, blob = http_get(url, referer=referer)
    with open(path, "wb") as f:
        f.write(blob)
    return long_path(path)


def main():
    if len(sys.argv) < 3:
        print("usage: kuaishou.py <share_url_or_text> <output_dir>", file=sys.stderr)
        return 2
    outdir = sys.argv[2]
    url = extract_url(sys.argv[1])
    if not url:
        print("no kuaishou link found in input", file=sys.stderr)
        return 1
    os.makedirs(outdir, exist_ok=True)

    data = fetch_init_state(url)
    if not data:
        print("could not read INIT_STATE from share page", file=sys.stderr)
        return 1

    photo = find_photo(data)
    if not photo:
        print("could not locate photo object (private/deleted?)", file=sys.stderr)
        return 1

    author = photo.get("userName", "")
    desc = photo.get("caption", "")
    print(f"Author:{author}")
    print(f"Desc:{desc}")

    mv_urls = photo.get("mainMvUrls") or []
    if mv_urls:
        video_url = mv_urls[0].get("url", "")
        if video_url:
            path = save(video_url, os.path.join(outdir, "dl_media_video.mp4"))
            print(f"VIDEO:{path}")
            return 0

    # Atlas / image post: images live in ext_params.atlas (relative paths
    # under /ufile/atlas/, to be prefixed with one of the CDN hosts).
    atlas = (photo.get("ext_params") or {}).get("atlas") or {}
    img_list = atlas.get("list") or []
    if img_list:
        cdns = [c.get("cdn", "") for c in (atlas.get("cdnList") or []) if c.get("cdn")]
        if not cdns:
            cdns = [c for c in (atlas.get("cdn") or []) if isinstance(c, str) and c]
        if not cdns:
            print("atlas images found but no CDN host", file=sys.stderr)
            return 1
        host = cdns[0]
        for i, rel in enumerate(img_list, 1):
            ext = os.path.splitext(rel)[1] or ".webp"
            img_url = f"https://{host}{rel}"
            path = save(img_url, os.path.join(outdir, f"dl_media_img{i}{ext}"))
            path = ensure_jpeg(path)
            print(f"IMG_{i}:{path}")
        return 0

    # Last resort: single picture post / cover image.
    covers = photo.get("coverUrls") or []
    if covers:
        img_url = covers[0].get("url", "")
        if img_url:
            ext = ".jpeg" if (".jpeg" in img_url or ".jpg" in img_url) else ".webp"
            path = save(img_url, os.path.join(outdir, f"dl_media_img1{ext}"))
            path = ensure_jpeg(path)
            print(f"IMG_1:{path}")
            return 0

    print("no downloadable media found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

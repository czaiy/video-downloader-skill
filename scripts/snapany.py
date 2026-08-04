# -*- coding: utf-8 -*-
"""
snapany.py - SnapAny OpenAPI fallback extractor (paid, 1 credit/post).

SnapAny (iiilab engine) does server-side parsing and can return media that
share-page scrapers cannot (e.g. Douyin live/motion videos on note posts).

Usage:
    python snapany.py <share_url_or_text> <output_dir> [types]

    types: comma-separated filter, any of video,image,audio (default: all)

Config:
    <skill_dir>/config.json  ->  {"snapany_key": "sk_snapany_xxx"}

Output (stdout), one line per item:
    Text:<post caption>
    VIDEO:<saved file path>
    IMG_n:<saved file path>
    AUDIO:<saved file path>

Exit code 0 on success, non-zero on failure. Pure stdlib, no deps.
NOTE: every successful call consumes 1 credit. Use only when local scripts
(douyin_note.py / kuaishou.py) cannot provide the requested media.
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

API_URL = "https://api.snapany.com/openapi/v1/extract/post"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(os.path.dirname(SCRIPT_DIR), "config.json")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

EXT_BY_TYPE = {"video": ".mp4", "image": ".jpg", "audio": ".mp3"}
PREFIX_BY_TYPE = {"video": "VIDEO", "image": "IMG", "audio": "AUDIO"}


def load_key():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            key = (json.load(f) or {}).get("snapany_key", "")
        if key:
            return key.strip()
    except Exception:
        pass
    return ""


def extract_url(text):
    m = re.search(r"https?://\S+", text or "")
    return m.group(0).rstrip("，。,.!") if m else (text or "").strip()


def call_api(url, key):
    body = json.dumps({"url": url}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (video-downloader skill)",
    })
    with urllib.request.urlopen(req, timeout=90, context=CTX) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def save(url, path, headers=None):
    h = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X)"}
    if isinstance(headers, dict):
        for k, v in headers.items():
            if v:
                h[k] = v
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=180, context=CTX) as resp, open(path, "wb") as f:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    return path


def main():
    if len(sys.argv) < 3:
        print("usage: snapany.py <share_url_or_text> <output_dir> [types]", file=sys.stderr)
        return 2
    url = extract_url(sys.argv[1])
    outdir = sys.argv[2]
    wanted = None
    if len(sys.argv) > 3 and sys.argv[3].strip():
        wanted = {t.strip().lower() for t in sys.argv[3].split(",") if t.strip()}
    if not url:
        print("no url found in input", file=sys.stderr)
        return 1

    key = load_key()
    if not key:
        print(f"snapany_key missing in {CONFIG_PATH}", file=sys.stderr)
        return 1

    os.makedirs(outdir, exist_ok=True)
    try:
        res = call_api(url, key)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:200]
        print(f"api error {e.code}: {detail}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"api request failed: {e}", file=sys.stderr)
        return 1

    text = res.get("text", "")
    if text:
        print(f"Text:{text}")
    medias = res.get("medias") or []
    if not medias:
        print("api returned no medias", file=sys.stderr)
        return 1

    counters = {"video": 0, "image": 0, "audio": 0}
    saved = 0
    for m in medias:
        t = m.get("media_type")
        rurl = m.get("resource_url", "")
        if t not in EXT_BY_TYPE or not rurl:
            continue
        if wanted and t not in wanted:
            continue
        counters[t] += 1
        if t == "image":
            fname = f"dl_media_img{counters[t]}{EXT_BY_TYPE[t]}"
        else:
            fname = f"dl_media_{t}{EXT_BY_TYPE[t]}"
        try:
            path = save(rurl, os.path.join(outdir, fname), m.get("headers"))
        except Exception as e:
            print(f"download failed ({t}#{counters[t]}): {e}", file=sys.stderr)
            continue
        prefix = PREFIX_BY_TYPE[t]
        label = f"{prefix}_{counters[t]}" if t == "image" else prefix
        print(f"{label}:{path}")
        saved += 1

    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main())

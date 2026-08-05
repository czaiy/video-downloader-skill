#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pan_baidu.py - Baidu Netdisk (百度网盘) share link parser & downloader.

Backend: 闪链 public parse API (mf.dp.wpurl.cc), no auth needed.
Flow (reverse-engineered 2026-08-05):
  POST /api/v1/user/parse/get_file_list   {url, surl, pwd, dir, parse_password}
       -> {uk, shareid, randsk, uname, list:[{fs_id, server_filename, size, is_dir, path}]}
       dir = full path from share root, e.g. "/我的资源/子文件夹" (folders recurse!)
  POST /api/v1/user/parse/get_download_links {randsk, uk, shareid, fs_id[], surl, dir, pwd,
       token:"guest", parse_password, vcode_str, vcode_input}
       -> [{filename, urls:[dlink...], ua}]   (dlink expires in ~8h)
  NOTE: randsk/uk/shareid MUST come from the get_file_list call of the SAME
  directory that contains the file, otherwise backend answers 20005 参数错误.

Usage:
    python pan_baidu.py "<share text or url>" <output_dir> [max_files] [zip]

Notes:
  - Folders are traversed recursively (depth <= MAX_DEPTH).
  - Backend bursts are rate-limited: every API call retries with backoff.
  - Error message containing "-20" means the backend hit a Baidu captcha;
    nothing we can do headless -> report and stop.
  - Single files larger than MAX_SINGLE_BYTES are skipped (WeChat upload).
  - Downloads use multi-connection Range chunks (see pan_common.py).

Output (stdout), one line per item:
    Pan:百度网盘
    Sharer:<nickname>
    COUNT:<number of downloaded files>
    FILE_1:<saved path>
    ZIP:<zip path>            (when zip mode and >=2 files)
    WARN:<reason>             (skipped / failed items)

Exit code 0 if at least one file was downloaded, non-zero otherwise.
Pure stdlib, no deps.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
import zipfile

from pan_common import safe_name, download_file, log, StatusFile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

API_BASE = "https://mf.dp.wpurl.cc/api/v1/user/parse"
TOKEN = "guest"
PARSE_PASSWORD = ""
TIMEOUT = 30
MAX_SINGLE_BYTES = 500 * 1024 * 1024  # 500MB cap per file
MAX_DEPTH = 3                          # folder recursion limit
API_PAUSE = 3                          # seconds between parse API calls
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
NETDISK_UA = "netdisk;2.0.30.6;PC;PC-Windows;10.0.19045;WindowsBaiduYunGuanJia"


class CaptchaError(Exception):
    pass


def _post_once(path, payload):
    req = urllib.request.Request(
        f"{API_BASE}/{path}",
        data=json.dumps(payload).encode(),
        headers={
            "User-Agent": DESKTOP_UA,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://mf.dp.wpurl.cc/user/parse",
            "Origin": "https://mf.dp.wpurl.cc",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def api_call(path, payload, tries=4):
    """POST with retry/backoff (backend burst rate-limiting is common)."""
    for i in range(tries):
        try:
            return _post_once(path, payload)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            if "-20" in body:
                raise CaptchaError("百度验证码")
            log(f"API:{path} HTTP {e.code} (attempt {i+1}/{tries})")
        except Exception as e:
            log(f"API:{path} {type(e).__name__} (attempt {i+1}/{tries})")
        if i < tries - 1:
            time.sleep(12 + 6 * i)
    raise IOError(f"API {path} 多次失败，解析站可能暂时不可用")


def parse_share(text):
    import re
    m = re.search(r"pan\.baidu\.com/s/1([A-Za-z0-9_-]+)", text)
    if m:
        surl = "1" + m.group(1)
    else:
        m = re.search(r"[?&]surl=([A-Za-z0-9_-]+)", text)
        surl = m.group(1) if m else ""
    pwd = ""
    m = re.search(r"[?&]pwd=([A-Za-z0-9]{4})", text)
    if m:
        pwd = m.group(1)
    else:
        m = re.search(r"提取码[:：]?\s*([A-Za-z0-9]{4})", text)
        if m:
            pwd = m.group(1)
    return surl, pwd


def walk_dir(base_payload, dir_path, depth):
    """
    List dir_path and recurse into subfolders.
    Returns list of (item, ctx) where ctx holds the randsk/uk/shareid/dir
    of the directory containing the item.
    """
    fl = api_call("get_file_list", {**base_payload, "dir": dir_path})
    if fl.get("code") != 200 or not fl.get("data"):
        raise IOError(f"获取目录失败 {dir_path}: {fl.get('message', 'unknown')}")
    data = fl["data"]
    ctx = {"randsk": data.get("randsk", ""), "uk": data.get("uk"),
           "shareid": data.get("shareid"), "dir": dir_path}
    out = []
    entries = data.get("list", []) or []
    subdirs = []
    for x in entries:
        if x.get("is_dir"):
            subdirs.append(x)
        else:
            out.append((x, ctx))
    if depth < MAX_DEPTH:
        for d in subdirs:
            time.sleep(API_PAUSE)
            sub = walk_dir(base_payload, d.get("path"), depth + 1)
            log(f"DIR:{d.get('server_filename')} -> {len(sub)} 个文件")
            out.extend(sub)
    else:
        for d in subdirs:
            log(f"WARN:目录层级过深，跳过 {d.get('path')}")
    return out


def zip_files(paths, outdir):
    dest = os.path.join(outdir, "dl_media_pan_all.zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in paths:
            zf.write(p, os.path.basename(p))
    for p in paths:
        os.remove(p)
    return dest


def main():
    if len(sys.argv) < 3:
        print("Usage: pan_baidu.py <share_text_or_url> <output_dir> [max_files] [zip]", file=sys.stderr)
        return 2
    text, outdir = sys.argv[1], sys.argv[2]
    max_files = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    want_zip = len(sys.argv) > 4 and sys.argv[4].lower() == "zip"
    os.makedirs(outdir, exist_ok=True)
    st = StatusFile(outdir, "百度网盘")

    surl, pwd = parse_share(text)
    if not surl:
        print("ERROR: 未找到有效的百度网盘分享链接", file=sys.stderr)
        st.add_warn("未找到有效的分享链接"); st.finish()
        return 1

    base_payload = {
        "url": f"https://pan.baidu.com/s/{surl}",
        "surl": surl, "pwd": pwd, "parse_password": PARSE_PASSWORD,
    }

    # 1. recursive listing
    try:
        items = walk_dir(base_payload, "/", 1)
    except CaptchaError:
        print("ERROR: 解析遇到百度验证码，暂无法自动处理", file=sys.stderr)
        st.add_warn("百度验证码"); st.finish()
        return 1
    except IOError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        st.add_warn(str(e)); st.finish()
        return 1
    if not items:
        print("ERROR: 分享里没有可下载的文件", file=sys.stderr)
        st.add_warn("分享里没有可下载的文件"); st.finish()
        return 1

    print("Pan:百度网盘")
    st.update(total=min(len(items), max_files))

    # 2. download each file (dlink per file, throttled backend -> pause)
    saved = 0
    saved_paths = []
    seen_names = set()
    for item, ctx in items:
        if saved >= max_files:
            log(f"WARN:已达到 max_files={max_files}，剩余文件跳过")
            break
        fs_id = item.get("fs_id")
        name = safe_name(item.get("server_filename") or f"file_{fs_id}")
        if name in seen_names:  # same name from nested folders
            name = f"{saved+1}_{name}"
        seen_names.add(name)
        st.update(current=name)
        size = int(item.get("size") or 0)
        if size > MAX_SINGLE_BYTES:
            log(f"WARN:跳过超大文件 {name}（{size/1024/1024:.0f}MB > 500MB）")
            st.add_warn(f"跳过超大文件 {name}（{size/1024/1024:.0f}MB > 500MB）")
            st.bump()
            continue
        try:
            dl = api_call("get_download_links", {
                "randsk": ctx["randsk"], "uk": ctx["uk"], "shareid": ctx["shareid"],
                "fs_id": [fs_id],
                "surl": surl, "dir": ctx["dir"], "pwd": pwd,
                "token": TOKEN, "parse_password": PARSE_PASSWORD,
                "vcode_str": "", "vcode_input": "",
            })
        except CaptchaError:
            print("ERROR: 解析遇到百度验证码，暂无法自动处理", file=sys.stderr)
            st.add_warn("百度验证码，中止"); st.finish()
            return 0 if saved else 1
        except IOError as e:
            log(f"WARN:文件 {name} 获取直链失败: {e}")
            st.add_warn(f"获取直链失败 {name}: {e}")
            st.bump()
            continue
        if dl.get("code") != 200 or not dl.get("data"):
            msg = str(dl.get("message", ""))
            if "-20" in msg:
                print("ERROR: 解析遇到百度验证码，暂无法自动处理", file=sys.stderr)
                st.add_warn("百度验证码，中止"); st.finish()
                return 0 if saved else 1
            log(f"WARN:文件 {name} 获取直链失败: {msg}")
            st.add_warn(f"获取直链失败 {name}: {msg}")
            st.bump()
            time.sleep(API_PAUSE)
            continue
        entry = dl["data"][0] if isinstance(dl.get("data"), list) else dl["data"]
        urls = entry.get("urls") or []
        if not urls:
            log(f"WARN:文件 {name} 没拿到直链")
            st.add_warn(f"没拿到直链 {name}")
            st.bump()
            continue
        dlink = urls[0] if isinstance(urls[0], str) else urls[0].get("url", "")
        dest = os.path.join(outdir, f"dl_media_pan{saved+1}_{name}")
        ok = False
        for ua in (DESKTOP_UA, NETDISK_UA):  # UA fallback for CDN 403
            hdrs = {"User-Agent": ua, "Accept": "*/*",
                    "Referer": "https://pan.baidu.com/"}
            ok, got, err = download_file(dlink, dest, hdrs, label=name,
                                         max_bytes=MAX_SINGLE_BYTES)
            if ok:
                break
        if not ok:
            log(f"WARN:下载失败 {name}: {err}")
            st.add_warn(f"下载失败 {name}: {err}")
            st.bump()
        else:
            saved += 1
            saved_paths.append(dest)
            st.add_file(dest)
            st.bump()
        time.sleep(API_PAUSE)

    zip_path = None
    if want_zip and len(saved_paths) >= 2:
        try:
            zip_path = zip_files(saved_paths, outdir)
            log(f"ZIP:{zip_path}")
        except Exception as e:
            log(f"WARN:打包zip失败，改发原文件: {e}")
            st.add_warn(f"打包zip失败: {e}")
            for i, p in enumerate(saved_paths, 1):
                log(f"FILE_{i}:{p}")
    else:
        for i, p in enumerate(saved_paths, 1):
            log(f"FILE_{i}:{p}")
    st.finish(zip_path)
    log(f"COUNT:{saved}")
    return 0 if saved > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

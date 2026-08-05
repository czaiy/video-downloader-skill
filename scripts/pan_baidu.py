#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pan_baidu.py - Baidu Netdisk (百度网盘) share link parser & downloader.

Backend: 闪链 public parse API (mf.dp.wpurl.cc), no auth needed.
Flow (reverse-engineered 2026-08-05):
  POST /api/v1/user/parse/get_file_list   {url, surl, pwd, dir, parse_password}
       -> {uk, shareid, randsk, uname, list:[{fs_id, server_filename, size, is_dir, path, md5}]}
  POST /api/v1/user/parse/get_download_links {randsk, uk, shareid, fs_id[], surl, dir, pwd,
       token:"guest", parse_password, vcode_str, vcode_input}
       -> [{filename, urls:[dlink...], ua}]   (dlink expires in ~8h)

Usage:
    python pan_baidu.py "<share text or url>" <output_dir> [max_files]

Notes:
  - Folders are NOT supported by the backend (allow_folder=false); dirs are
    skipped with a WARN line.
  - Error message containing "-20" means the backend hit a Baidu captcha;
    nothing we can do headless -> report and stop.
  - Single files larger than MAX_SINGLE_BYTES are skipped (WeChat upload).

Output (stdout), one line per item:
    Pan:百度网盘
    Sharer:<nickname>
    COUNT:<number of downloaded files>
    FILE_1:<saved path>
    WARN:<reason>        (skipped dirs / oversized files)

Exit code 0 if at least one file was downloaded, non-zero otherwise.
Pure stdlib, no deps.
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

API_BASE = "https://mf.dp.wpurl.cc/api/v1/user/parse"
TOKEN = "guest"
PARSE_PASSWORD = ""
TIMEOUT = 30
DL_TIMEOUT = 600
MAX_SINGLE_BYTES = 500 * 1024 * 1024  # 500MB cap per file
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
NETDISK_UA = "netdisk;2.0.30.6;PC;PC-Windows;10.0.19045;WindowsBaiduYunGuanJia"

try:
    _ctx = ssl.create_default_context()
except Exception:
    _ctx = None


def api_call(path, payload):
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
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def parse_share(text):
    """Extract surl + pwd from raw share text / url."""
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


def safe_name(name):
    return re.sub(r'[\\/:*?"<>|\r\n]', "_", name).strip() or "file"


def download(url, dest, size_hint=0):
    last_err = None
    for ua in (DESKTOP_UA, NETDISK_UA):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": ua,
                "Accept": "*/*",
                "Referer": "https://pan.baidu.com/",
            })
            with urllib.request.urlopen(req, timeout=DL_TIMEOUT, context=_ctx) as resp:
                tmp = dest + ".part"
                got = 0
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                if size_hint and got < size_hint * 0.95:
                    os.remove(tmp)
                    raise IOError(f"incomplete download {got}/{size_hint}")
                os.replace(tmp, dest)
            return os.path.getsize(dest)
        except Exception as e:  # try next UA
            last_err = e
    raise IOError(f"download failed: {last_err}")


def main():
    if len(sys.argv) < 3:
        print("Usage: pan_baidu.py <share_text_or_url> <output_dir> [max_files]", file=sys.stderr)
        return 2
    text, outdir = sys.argv[1], sys.argv[2]
    max_files = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    os.makedirs(outdir, exist_ok=True)

    surl, pwd = parse_share(text)
    if not surl:
        print("ERROR: 未找到有效的百度网盘分享链接", file=sys.stderr)
        return 1

    # 1. file list
    fl = api_call("get_file_list", {
        "url": f"https://pan.baidu.com/s/{surl}",
        "surl": surl, "pwd": pwd, "dir": "/", "parse_password": PARSE_PASSWORD,
    })
    if fl.get("code") != 200 or not fl.get("data"):
        msg = fl.get("message", "unknown error")
        print(f"ERROR: 获取文件列表失败: {msg}", file=sys.stderr)
        return 1
    data = fl["data"]
    files = [x for x in data.get("list", []) if not x.get("is_dir")]
    dirs = [x for x in data.get("list", []) if x.get("is_dir")]
    for d in dirs:
        print(f"WARN:跳过文件夹 {d.get('server_filename')}（接口暂不支持文件夹）")
    if not files:
        print("ERROR: 分享里没有可下载的文件（或只有文件夹）", file=sys.stderr)
        return 1

    uname = data.get("uname", "")
    print(f"Pan:百度网盘")
    if uname:
        print(f"Sharer:{uname}")

    # 2. download each file
    saved = 0
    for item in files[:max_files]:
        fs_id = item.get("fs_id")
        name = safe_name(item.get("server_filename") or f"file_{fs_id}")
        size = int(item.get("size") or 0)
        if size > MAX_SINGLE_BYTES:
            print(f"WARN:跳过超大文件 {name}（{size/1024/1024:.0f}MB > 500MB）")
            continue
        try:
            dl = api_call("get_download_links", {
                "randsk": data.get("randsk", ""),
                "uk": data.get("uk"),
                "shareid": data.get("shareid"),
                "fs_id": [fs_id],
                "surl": surl, "dir": "/", "pwd": pwd,
                "token": TOKEN, "parse_password": PARSE_PASSWORD,
                "vcode_str": "", "vcode_input": "",
            })
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if "-20" in body:
                print("ERROR: 解析遇到百度验证码，暂无法自动处理", file=sys.stderr)
            else:
                print(f"ERROR: 获取直链失败: {body[:200]}", file=sys.stderr)
            return 1 if saved == 0 else 0
        if dl.get("code") != 200 or not dl.get("data"):
            msg = dl.get("message", "")
            if "-20" in str(msg):
                print("ERROR: 解析遇到百度验证码，暂无法自动处理", file=sys.stderr)
                return 1 if saved == 0 else 0
            print(f"ERROR: 获取直链失败: {msg}", file=sys.stderr)
            return 1 if saved == 0 else 0
        entry = dl["data"][0]
        urls = entry.get("urls") or []
        if not urls:
            print(f"WARN:文件 {name} 没拿到直链")
            continue
        dest = os.path.join(outdir, f"dl_media_pan{saved+1}_{name}")
        try:
            got = download(urls[0], dest, size)
        except Exception as e:
            print(f"WARN:下载失败 {name}: {e}")
            continue
        saved += 1
        print(f"FILE_{saved}:{dest}")

    print(f"COUNT:{saved}")
    return 0 if saved > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

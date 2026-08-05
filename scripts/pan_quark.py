#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pan_quark.py - Quark Netdisk (夸克网盘) share link parser & downloader.

Backend: 闪链 Quark parse API (kk.wpurl.cc), no auth needed. The server
keeps a Quark account pool: it saves shared files to its own account and
hands back a direct download URL. Flow (reverse-engineered 2026-08-05):
  POST /api/get_stoken.php    {pwd_id, passcode, pwd}
       -> {code:0, stoken, stoken_url}
  POST /api/get_file_list.php {pwd_id, stoken_url, pdir_fid, page, pwd}
       -> {code:0, list:[{file_name, size, fid, pdir_fid, share_fid_token, dir}]}
  POST /api/file_save.php     {fid_list, fid_token_list, pdir_fid, pwd_id, stoken, pwd}
       -> {code:0, file_id}          (file transferred into server account)
  POST /api/get_link.php      {id: file_id, pwd}
       -> {code:0, download_url, header}

Usage:
    python pan_quark.py "<share text or url>" <output_dir> [max_files]

Notes:
  - `pwd` above is the parse-site access password (empty on the public site),
    NOT the share extraction code (that is `passcode`).
  - Directories are skipped with a WARN line (v1).
  - Single files larger than MAX_SINGLE_BYTES are skipped (WeChat upload).

Output (stdout), one line per item:
    Pan:夸克网盘
    COUNT:<number of downloaded files>
    FILE_1:<saved path>
    WARN:<reason>

Exit code 0 if at least one file was downloaded, non-zero otherwise.
Pure stdlib, no deps.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import zipfile

from pan_common import safe_name, download_file, log

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

API_BASE = "https://kk.wpurl.cc/api"
TIMEOUT = 60
MAX_SINGLE_BYTES = 500 * 1024 * 1024
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


def load_site_pwd():
    """Read the kk.wpurl.cc parse password.
    Priority: env QUARK_PARSE_PWD > skill config.json key quark_parse_pwd.
    The password is free but obtained manually once via the official guide:
    https://www.yuque.com/wpurl/vp60ux/xu3codnavvxzdgr9
    """
    v = os.environ.get("QUARK_PARSE_PWD", "").strip()
    if v:
        return v
    cfg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
    try:
        with open(cfg, encoding="utf-8") as f:
            return str(json.load(f).get("quark_parse_pwd", "")).strip()
    except Exception:
        return ""


def fetch_page(pwd_id, stoken_url, pdir_fid, page, site_pwd):
    fl = api_call("get_file_list.php", {
        "pwd_id": pwd_id, "stoken_url": stoken_url,
        "pdir_fid": pdir_fid, "page": str(page), "pwd": site_pwd,
    })
    if fl.get("code") != 0:
        raise IOError(f"获取文件列表失败: {fl.get('msg')}")
    return fl.get("list") or []


def is_dir(e):
    return bool(e.get("dir")) or e.get("file_type") == 0 or bool(e.get("isDirectory"))


def collect_files(pwd_id, stoken_url, site_pwd, pdir_fid="0", prefix="", depth=0, max_depth=2):
    """Recursively collect files; folders are walked up to max_depth."""
    out = []
    page = 1
    while True:
        batch = fetch_page(pwd_id, stoken_url, pdir_fid, page, site_pwd)
        for e in batch:
            name = e.get("file_name") or ""
            if is_dir(e):
                if depth < max_depth:
                    out.extend(collect_files(
                        pwd_id, stoken_url, site_pwd, e.get("fid"),
                        f"{prefix}{name}_", depth + 1, max_depth))
                else:
                    log(f"WARN:跳过过深文件夹 {prefix}{name}（最多 {max_depth} 层）")
            else:
                e["_prefix"] = prefix
                out.append(e)
        if len(batch) < 50 or page >= 5:
            break
        page += 1
    return out


def _post_once(path, payload):
    req = urllib.request.Request(
        f"{API_BASE}/{path}",
        data=json.dumps(payload).encode(),
        headers={
            "User-Agent": DESKTOP_UA,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://kk.wpurl.cc/",
            "Origin": "https://kk.wpurl.cc",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def api_call(path, payload, tries=4):
    """POST with retry/backoff (public parse sites are often flaky)."""
    for i in range(tries):
        try:
            return _post_once(path, payload)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            log(f"API:{path} HTTP {e.code} {body[:120]} (attempt {i+1}/{tries})")
        except Exception as e:
            log(f"API:{path} {type(e).__name__} (attempt {i+1}/{tries})")
        if i < tries - 1:
            time.sleep(8 + 4 * i)
    raise IOError(f"API {path} 多次失败，解析站可能暂时不可用")


def parse_share(text):
    """Extract pwd_id + passcode from raw share text / url."""
    m = re.search(r"pan\.quark\.cn/s/([A-Za-z0-9]+)", text)
    pwd_id = m.group(1) if m else ""
    passcode = ""
    m = re.search(r"[?&]pwd=([A-Za-z0-9]{4})", text) or \
        re.search(r"提取码[:：]?\s*([A-Za-z0-9]{4})", text) or \
        re.search(r"密码[:：]?\s*([A-Za-z0-9]{4})", text)
    if m:
        passcode = m.group(1)
    return pwd_id, passcode


def build_dl_headers(api_header):
    """Merge get_link.php `header` into HTTP headers.
    cookie_puus -> Cookie: __puus=... (required to avoid 412)."""
    h = {
        "User-Agent": DESKTOP_UA,
        "Accept": "*/*",
        "Referer": "https://pan.quark.cn/",
    }
    if api_header:
        for k, v in api_header.items():
            if not k or not v:
                continue
            lk = str(k).lower()
            if "cookie" in lk:
                h["Cookie"] = str(v)
            else:
                h[str(k)] = str(v)
    return h

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
        print("Usage: pan_quark.py <share_text_or_url> <output_dir> [max_files]", file=sys.stderr)
        return 2
    text, outdir = sys.argv[1], sys.argv[2]
    max_files = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    want_zip = len(sys.argv) > 4 and sys.argv[4].lower() == "zip"
    os.makedirs(outdir, exist_ok=True)

    pwd_id, passcode = parse_share(text)
    if not pwd_id:
        print("ERROR: 未找到有效的夸克网盘分享链接", file=sys.stderr)
        return 1
    site_pwd = load_site_pwd()
    if not site_pwd:
        print("ERROR: 缺少夸克解析密码。请从官方指引获取一次"
              "（https://www.yuque.com/wpurl/vp60ux/xu3codnavvxzdgr9），"
              "填入 skill config.json 的 quark_parse_pwd 或环境变量 QUARK_PARSE_PWD",
              file=sys.stderr)
        return 1

    # 1. stoken
    st = api_call("get_stoken.php", {"pwd_id": pwd_id, "passcode": passcode, "pwd": site_pwd})
    if st.get("code") != 0:
        print(f"ERROR: 获取分享令牌失败: {st.get('msg')}", file=sys.stderr)
        return 1
    stoken = st.get("stoken", "")
    stoken_url = st.get("stoken_url", "")

    # 2. file list (recursive folder walk)
    try:
        files = collect_files(pwd_id, stoken_url, site_pwd)
    except Exception as e:
        print(f"ERROR: 获取文件列表失败: {e}", file=sys.stderr)
        return 1
    if not files:
        print("ERROR: 分享里没有可下载的文件", file=sys.stderr)
        return 1

    print("Pan:夸克网盘", flush=True)

    # 3. per file: save -> direct link -> download
    saved = 0
    saved_paths = []
    for item in files[:max_files]:
        name = safe_name((item.get("_prefix") or "") + (item.get("file_name") or "file"))
        size = int(item.get("size") or 0)
        if size > MAX_SINGLE_BYTES:
            log(f"WARN:跳过超大文件 {name}（{size/1024/1024:.0f}MB > 500MB）")
            continue
        try:
            fs = api_call("file_save.php", {
                "fid_list": item.get("fid"),
                "fid_token_list": item.get("share_fid_token"),
                "pdir_fid": item.get("pdir_fid", "0"),
                "pwd_id": pwd_id, "stoken": stoken, "pwd": site_pwd,
            })
            if fs.get("code") != 0 or fs.get("file_id") in (None, ""):
                log(f"WARN:转存失败 {name}: {fs.get('msg')}")
                continue
            file_id = str(fs["file_id"])
            gl = api_call("get_link.php", {"id": file_id, "pwd": site_pwd})
            if gl.get("code") != 0 or not gl.get("download_url"):
                log(f"WARN:获取直链失败 {name}: {gl.get('msg')}")
                continue
            dest = os.path.join(outdir, f"dl_media_pan{saved+1}_{name}")
            hdrs = build_dl_headers(gl.get("header"))
            ok, got, err = download_file(gl["download_url"], dest, hdrs,
                                         label=name, max_bytes=MAX_SINGLE_BYTES)
            if not ok:
                log(f"WARN:下载失败 {name}: {err}")
                continue
        except Exception as e:
            log(f"WARN:处理失败 {name}: {e}")
            continue
        saved += 1
        saved_paths.append(dest)

    if want_zip and len(saved_paths) >= 2:
        try:
            log(f"ZIP:{zip_files(saved_paths, outdir)}")
        except Exception as e:
            log(f"WARN:打包zip失败，改发原文件: {e}")
            for i, p in enumerate(saved_paths, 1):
                log(f"FILE_{i}:{p}")
    else:
        for i, p in enumerate(saved_paths, 1):
            log(f"FILE_{i}:{p}")
    log(f"COUNT:{saved}")
    return 0 if saved > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

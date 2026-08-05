# -*- coding: utf-8 -*-
"""
pan_common.py - shared helpers for pan_baidu.py / pan_quark.py

Main feature: multi-connection parallel downloader (HTTP Range chunks).
Public parse APIs throttle single connections hard (~30KB/s observed);
CDN links from both Baidu and Quark support Range requests, so we split
the file into N chunks and download them concurrently, which gives a
several-fold speedup. Falls back to plain streaming when the server does
not honor Range (200 instead of 206).

Pure stdlib, Windows PowerShell friendly.
"""

import os
import re
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

WORKERS = 6          # parallel connections for large files
MIN_PARALLEL = 2 * 1024 * 1024   # only parallelize files >= 2MB
CHUNK_RETRY = 3      # attempts per chunk
CONNECT_TIMEOUT = 20
READ_TIMEOUT = 120   # per-read stall timeout


def log(msg):
    """Print with flush so managed shell sessions show live progress."""
    print(msg, flush=True)


def safe_name(name):
    name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", str(name).strip())
    name = name.strip(" ._")
    return (name[:150] or "file").strip()


class DownloadError(Exception):
    pass


def _open(url, headers, rng=None, timeout=CONNECT_TIMEOUT):
    h = dict(headers)
    if rng:
        h["Range"] = rng
    req = urllib.request.Request(url, headers=h, method="GET")
    return urllib.request.urlopen(req, timeout=timeout)


def _probe(url, headers):
    """Return (total_size or None, supports_range bool)."""
    try:
        with _open(url, headers, rng="bytes=0-0", timeout=CONNECT_TIMEOUT) as r:
            cr = r.headers.get("Content-Range") or ""
            if r.status == 206 and "/" in cr:
                total = cr.rsplit("/", 1)[-1].strip()
                if total.isdigit():
                    return int(total), True
            # some CDNs ignore Range -> treat as no-range
            cl = r.headers.get("Content-Length")
            return (int(cl) if cl and cl.isdigit() else None), False
    except urllib.error.HTTPError as e:
        if e.code == 416:  # range not satisfiable -> file unknown, no range
            return None, False
        raise


def _download_range(url, headers, fh, start, end, label):
    """Download bytes [start, end] into fh at offset start, with retries."""
    pos = start
    for attempt in range(1, CHUNK_RETRY + 1):
        try:
            with _open(url, headers, rng=f"bytes={pos}-{end}", timeout=CONNECT_TIMEOUT) as r:
                while pos <= end:
                    chunk = r.read(512 * 1024)
                    if not chunk:
                        break
                    fh.seek(pos)
                    fh.write(chunk)
                    pos += len(chunk)
            if pos > end:
                return end - start + 1
            raise IOError("stream ended early at %d/%d" % (pos, end + 1))
        except Exception as e:
            if attempt == CHUNK_RETRY:
                raise DownloadError(f"{label} chunk {start}-{end} failed: {type(e).__name__}: {e}")
            time.sleep(2 * attempt)
    return 0


import json as _json


class StatusFile:
    """
    Writes <outdir>/pan_status.json so external watchers (e.g. scheduled
    agent tasks) can check download progress/completion without needing
    the shell session. Atomic replace on every update.
    """

    def __init__(self, outdir, pan_name):
        self.path = os.path.join(outdir, "pan_status.json")
        self.data = {
            "pan": pan_name,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            "running": True,
            "done": False,
            "total": None,
            "processed": 0,
            "saved": 0,
            "current": "",
            "files": [],
            "zip": None,
            "warns": [],
            "finished": None,
        }
        self._write()

    def _write(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def update(self, **kw):
        self.data.update(kw)
        self._write()

    def add_file(self, path):
        self.data["files"].append(path)
        self.data["saved"] = len(self.data["files"])
        self._write()

    def add_warn(self, msg):
        self.data["warns"].append(msg)
        self._write()

    def bump(self):
        """One more item processed (saved / skipped / failed)."""
        self.data["processed"] += 1
        self._write()

    def finish(self, zip_path=None):
        self.data.update({
            "running": False, "done": True,
            "zip": zip_path, "current": "",
            "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        self._write()


def download_file(url, dest, headers, label="file", max_bytes=None, attempts=3):
    """
    Download url -> dest (via .part), parallel Range chunks when possible.
    Outer retry loop handles transient CDN errors (522/5xx/reset).
    Returns (ok, size_bytes, err_msg). Never raises.
    """
    last_err = "unknown"
    for attempt in range(1, attempts + 1):
        ok, size, err = _download_once(url, dest, headers, label, max_bytes)
        if ok:
            return True, size, ""
        last_err = err
        if "too big" in str(err):
            break  # permanent, no point retrying
        if attempt < attempts:
            log(f"RETRY: {label} attempt {attempt}/{attempts} failed ({err}), retry in {4*attempt}s")
            time.sleep(4 * attempt)
    return False, 0, last_err


def _download_once(url, dest, headers, label, max_bytes):
    part = dest + ".part"
    t0 = time.time()
    try:
        total, ranged = _probe(url, headers)
        if max_bytes and total and total > max_bytes:
            return False, 0, f"too big ({total / 1024 / 1024:.0f}MB)"

        if ranged and total and total >= MIN_PARALLEL:
            n = min(WORKERS, max(2, total // (1024 * 1024)))  # ~1MB per worker min
            bounds = []
            step = total // n
            for i in range(n):
                s = i * step
                e = total - 1 if i == n - 1 else (i + 1) * step - 1
                bounds.append((s, e))
            log(f"DL: {label} {total / 1024 / 1024:.1f}MB x{n} connections")
            fh = open(part, "wb")
            try:
                with ThreadPoolExecutor(max_workers=n) as ex:
                    futs = [ex.submit(_download_range, url, headers, fh, s, e, label)
                            for s, e in bounds]
                    for f in as_completed(futs):
                        f.result()  # raises on failure
            finally:
                fh.close()
        else:
            # plain streaming fallback
            with _open(url, headers, timeout=CONNECT_TIMEOUT) as r:
                with open(part, "wb") as fh:
                    got = 0
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
                        got += len(chunk)
                        if max_bytes and got > max_bytes:
                            raise DownloadError("too big (streaming)")
            total = None

        size = os.path.getsize(part)
        if total and size != total:
            return False, size, f"incomplete ({size}/{total})"
        if os.path.exists(dest):
            os.remove(dest)
        os.replace(part, dest)
        secs = max(time.time() - t0, 0.1)
        log(f"OK: {label} {size / 1024 / 1024:.2f}MB @ {size / 1024 / secs:.0f}KB/s")
        return True, size, ""
    except Exception as e:
        try:
            if os.path.exists(part):
                os.remove(part)
        except OSError:
            pass
        return False, 0, f"{type(e).__name__}: {e}"

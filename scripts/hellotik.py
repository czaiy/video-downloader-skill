# -*- coding: utf-8 -*-
"""
hellotik.py - Hellotik (iiilab engine) free fallback extractor.

Reverse-engineered protocol (2026-08):
  1. Fetch main JS chunk, extract active profile (weekly rotated):
       authRoute (e.g. gate-e5eea8) + ticketResponseFields + parseRequestFields
  2. POST /api/{authRoute} {requestURL, isBatch, mode}
       -> {tk_xxx, sd_xxx, ex_xxx}  (ticket + seed + expiry)
  3. Build parse payload (requestURL + local counter fields), encrypt with
       AES-GCM: key=SHA-256(ticket:seed), random 12-byte iv
     POST /api/parse {tk_xxx, pl_xxx, iv_xxx, vr_xxx}
       -> {status:0, encrypt:true, data:<b64>, key:<hint>}
  4. Decrypt response: custom b64 alphabet swap + reverse-8 + XOR-90 on both
       data and key; AES-CBC with hardcoded key, PKCS7 unpad

Output (stdout):
    Text:<title>
    VIDEO:<path>
    IMG_n:<path>
    AUDIO:<path>  (hellotik usually returns no audio; placeholder)

Exit 0 on success. Requires pycryptodome or cryptography + hashlib.
NOTE: ticket endpoint rate-limits to ~1/10min per IP. Use sparingly; prefer
snapany.py when available and credits remain.
"""
import base64
import glob
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOST = "https://www.hellotik.app"
MAIN_CHUNK = "/_next/static/chunks/1989-237e21100086fac9.js"
WEBPACK_CHUNK = "/_next/static/chunks/webpack-b2f23f854e29a67d.js"

ALPHABET_CUSTOM = "ZYXABCDEFGHIJKLMNOPQRSTUVWzyxabcdefghijklmnopqrstuvw9876543210-_"
ALPHABET_STD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
HARDCODED_KEY = "93838338562359368888868323563256"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def _load_crypto():
    try:
        from Crypto.Cipher import AES
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes as c_modes
        from cryptography.hazmat.backends import default_backend
        return AES, Cipher, c_modes, default_backend
    except Exception:
        pass
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes as c_modes
        from cryptography.hazmat.backends import default_backend
        return None, Cipher, c_modes, default_backend
    except Exception:
        return None, None, None, None


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": HOST + "/"})
    with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
        return r.read().decode("utf-8", "ignore")


def http_post(path, body, cookie=""):
    data = json.dumps(body).encode()
    req = urllib.request.Request(HOST + path, data=data, headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0",
        "Origin": HOST, "Referer": HOST + "/zh/", "Cookie": cookie})
    try:
        with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
            return r.status, r.read().decode("utf-8", "ignore"), r.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore"), e.headers.get("Set-Cookie", "")


def load_active_profile():
    js = http_get(HOST + MAIN_CHUNK)
    m = re.search(r"JSON.parse\('(\{.*?\})'\)", js, re.S)
    if not m:
        return None
    raw = m.group(1).replace("\\'", "'").replace('\\"', '"')
    cfg = json.loads(raw)
    pid = cfg.get("activeProfileId") or (cfg["profiles"][0]["id"] if cfg.get("profiles") else None)
    if not pid:
        return None
    for p in cfg.get("profiles", []):
        if p.get("id") == pid:
            return p
    return cfg["profiles"][0] if cfg.get("profiles") else None


def get_ticket(profile, link):
    route = profile["authRoute"]
    sc, body, ck = http_post("/api/" + route, {"requestURL": link, "isBatch": False, "mode": "single"})
    if sc != 200:
        return None, ck
    data = json.loads(body)
    kf = profile["ticketResponseFields"]
    ticket = data.get(kf.get("key", "ticket"))
    seed = data.get(kf.get("seed", "encSeed"))
    if not ticket or not seed:
        return None, ck
    return {"ticket": ticket, "seed": seed}, ck


def encrypt_request(payload, ticket, seed):
    AES, _, _, _ = _load_crypto()
    key = hashlib.sha256(f"{ticket}:{seed}".encode()).digest()
    iv = os.urandom(12)
    pt = json.dumps(payload).encode("utf-8")
    if AES:
        c = AES.new(key, AES.MODE_GCM, nonce=iv)
        ct, tag = c.encrypt_and_digest(pt)
    else:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        c = Cipher(algorithms.AES(key), modes.GCM(iv))
        enc = c.encryptor()
        ct = enc.update(pt) + enc.finalize()
        tag = enc.tag
    ct = ct + tag  # Web Crypto AES-GCM output = ciphertext || 16-byte tag (both libs)
    return base64.b64encode(ct).decode(), base64.b64encode(iv).decode()


def b64_swap(s):
    out = []
    for c in s:
        idx = ALPHABET_CUSTOM.find(c)
        out.append(ALPHABET_STD[idx] if idx != -1 else c)
    return "".join(out)


def reverse8(s):
    return "".join(s[i:i + 8][::-1] for i in range(0, len(s), 8))


def xor90(s):
    return "".join(chr(ord(c) ^ 90) for c in s)


def decrypt_response(data_b64, key_hint):
    AES, Cipher, modes, backend = _load_crypto()
    if not (AES or Cipher):
        return None
    c_raw = base64.b64decode(data_b64).decode("latin-1")
    k_raw = base64.b64decode(key_hint).decode("latin-1")
    c_raw, k_raw = xor90(c_raw), xor90(k_raw)
    c_raw, k_raw = reverse8(c_raw), reverse8(k_raw)
    c_raw, k_raw = b64_swap(c_raw), b64_swap(k_raw)
    ct = base64.b64decode(c_raw)
    iv = base64.b64decode(k_raw)
    key = HARDCODED_KEY.encode("utf-8")
    if AES:
        c = AES.new(key, AES.MODE_CBC, iv)
        raw = c.decrypt(ct)
    else:
        from cryptography.hazmat.primitives.ciphers import Cipher as _C, algorithms as _A, modes as _M
        dec = _C(_A.AES(key), _M.CBC(iv)).decryptor()
        raw = dec.update(ct) + dec.finalize()
    pad = raw[-1]
    if 1 <= pad <= 16 and all(b == pad for b in raw[-pad:]):
        raw = raw[:-pad]
    return json.loads(raw.decode("utf-8"))


def save_media(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X)",
                                                "Referer": "https://www.douyin.com/"})
    with urllib.request.urlopen(req, timeout=180, context=CTX) as r, open(path, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    return path


def main():
    if len(sys.argv) < 3:
        print("usage: hellotik.py <share_url_or_text> <outdir> [types]", file=sys.stderr)
        return 2
    link = sys.argv[1].strip()
    if not link.startswith("http"):
        m = re.search(r"https?://\S+", link)
        link = m.group(0).rstrip("，。,.!") if m else link
    outdir = sys.argv[2]
    wanted = None
    if len(sys.argv) > 3 and sys.argv[3].strip():
        wanted = {t.strip().lower() for t in sys.argv[3].split(",") if t.strip()}

    os.makedirs(outdir, exist_ok=True)
    profile = load_active_profile()
    if not profile:
        print("failed to load active profile", file=sys.stderr)
        return 1

    tk, ck = get_ticket(profile, link)
    if not tk:
        print("ticket request failed (rate limited?)", file=sys.stderr)
        return 1

    pf = profile["parseRequestFields"]
    payload = {"requestURL": link, "isMobile": "false", "isoCode": "Other", "adType": "adsense", "uwx_id": "",
               "successCount": "0", "totalSuccessCount": "0", "firstSuccessDate": None, "geoipIp": ""}
    enc_payload, iv = encrypt_request(payload, tk["ticket"], tk["seed"])
    body = {pf["key"]: tk["ticket"], pf["payload"]: enc_payload, pf["iv"]: iv, pf["version"]: 1}

    sc, body2, _ = http_post("/api/parse", body, cookie=ck)
    resp = json.loads(body2)
    if resp.get("status") != 0:
        print(f"parse error: {resp.get('error') or resp}", file=sys.stderr)
        return 1
    if not resp.get("encrypt"):
        print("unexpected unencrypted response", file=sys.stderr)
        return 1

    dec = decrypt_response(resp["data"], resp["key"])
    if not dec:
        print("decrypt failed", file=sys.stderr)
        return 1

    title = dec.get("title") or ""
    if title:
        print(f"Text:{title}")

    saved = 0
    vurls = []
    if dec.get("url"):
        vurls.append(dec["url"])
    for v in dec.get("videos") or []:
        u = (isinstance(v, dict) and v.get("url")) or (isinstance(v, str) and v)
        if u:
            vurls.append(u)

    if (not wanted or "video" in wanted) and vurls:
        for vi, vu in enumerate(set(vurls)):
            try:
                p = save_media(vu, os.path.join(outdir, f"dl_media_video{vi + 1}.mp4"))
                print(f"VIDEO:{p}")
                saved += 1
                break
            except Exception as e:
                print(f"video download failed: {e}", file=sys.stderr)

    if not wanted or "image" in wanted:
        for ii, img in enumerate(dec.get("pics") or []):
            try:
                p = save_media(img, os.path.join(outdir, f"dl_media_img{ii + 1}.jpg"))
                print(f"IMG_{ii + 1}:{p}")
                saved += 1
            except Exception as e:
                print(f"image download failed: {e}", file=sys.stderr)

    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main())

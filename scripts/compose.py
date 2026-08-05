# -*- coding: utf-8 -*-
"""
compose.py - Slideshow video composer (ffmpeg-based).

Synthesizes a video from static images (+ optional BGM audio).
Use cases:
  - Pure image posts where user wants video format
  - Last-resort fallback when all API extractors fail
  - Creative tool for any image set

Usage:
    python compose.py <outdir> [duration_per_image] [transition_type]

    Reads images from outdir matching: dl_media_img*.jpg / .jpeg / .png / .webp
    Optionally mixes in dl_media_audio.mp3 / .m4a if present.

    duration_per_image: seconds per image (default 3)
    transition_type: fade, slideleft, slideright, circleopen, dissolve (default fade)

Output:
    dl_media_composed.mp4 in outdir
    Prints: COMPOSED:<path>

Requires: ffmpeg on PATH or at C:\ffmpeg\bin\ffmpeg.exe
"""
import glob
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"
if not os.path.exists(FFMPEG):
    FFMPEG = "ffmpeg"

TRANSITIONS = {
    "fade": "fade",
    "slideleft": "slideleft",
    "slideright": "slideright",
    "circleopen": "circleopen",
    "circleclose": "circleclose",
    "dissolve": "dissolve",
    "smoothleft": "smoothleft",
    "smoothright": "smoothright",
}


def find_images(outdir):
    exts = ["jpg", "jpeg", "png", "webp"]
    files = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(outdir, f"dl_media_img*.{ext}")))
    files = sorted(set(files))
    return files


def find_audio(outdir):
    for ext in ["mp3", "m4a", "aac"]:
        p = os.path.join(outdir, f"dl_media_audio.{ext}")
        if os.path.exists(p):
            return p
    return None


def build_ffmpeg_cmd(images, audio, duration, transition, outpath):
    n = len(images)
    if n == 0:
        return None

    # Build input args
    inputs = []
    for img in images:
        inputs.extend(["-loop", "1", "-t", str(duration + 1), "-i", img])
    if audio:
        inputs.extend(["-i", audio])

    # Build filter_complex
    # Scale all inputs to same resolution, then chain xfade transitions
    filter_parts = []
    scale_parts = []
    for i in range(n):
        scale_parts.append(f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]")

    filter_parts.extend(scale_parts)

    # Chain xfade transitions
    if n == 1:
        filter_parts.append(f"[v0]null[out]")
    else:
        # First transition
        offset = duration
        filter_parts.append(f"[v0][v1]xfade=transition={transition}:duration=0.5:offset={offset}[xf0]")
        for i in range(2, n):
            prev = f"[xf{i-2}]"
            cur = f"[v{i}]"
            out = f"[xf{i-1}]"
            offset += duration
            filter_parts.append(f"{prev}{cur}xfade=transition={transition}:duration=0.5:offset={offset}{out}")
        filter_parts.append(f"[xf{n-2}]null[out]")

    filter_complex = ";".join(filter_parts)

    # Build output args
    cmd = [FFMPEG, "-y"] + inputs
    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(["-map", "[out]"])
    if audio:
        audio_idx = n  # audio is the last input
        cmd.extend(["-map", f"{audio_idx}:a"])
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        outpath
    ])
    return cmd


def main():
    if len(sys.argv) < 2:
        print("usage: compose.py <outdir> [duration_per_image] [transition_type]", file=sys.stderr)
        return 2

    outdir = sys.argv[1]
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    transition = sys.argv[3] if len(sys.argv) > 3 else "fade"
    if transition not in TRANSITIONS:
        transition = "fade"
    transition = TRANSITIONS[transition]

    images = find_images(outdir)
    if not images:
        print("no dl_media_img* files found in outdir", file=sys.stderr)
        return 1

    audio = find_audio(outdir)
    outpath = os.path.join(outdir, "dl_media_composed.mp4")

    print(f"Composing: {len(images)} images, {duration}s each, transition={transition}, audio={'yes' if audio else 'no'}", file=sys.stderr)

    cmd = build_ffmpeg_cmd(images, audio, duration, transition, outpath)
    if not cmd:
        print("failed to build ffmpeg command", file=sys.stderr)
        return 1

    result = subprocess.run(cmd, capture_output=True, timeout=120)
    if result.returncode != 0:
        print(f"ffmpeg failed: {result.stderr.decode('utf-8', 'ignore')[-500:]}", file=sys.stderr)
        return 1

    if os.path.exists(outpath):
        sz = os.path.getsize(outpath)
        print(f"COMPOSED:{outpath}", file=sys.stderr)
        print(f"COMPOSED:{outpath}")
        print(f"SIZE_MB:{round(sz/1024/1024, 2)}", file=sys.stderr)
        return 0
    else:
        print("output file not created", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

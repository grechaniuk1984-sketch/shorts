#!/usr/bin/env python3
"""Generate YouTube Shorts (1080x1920) from scripts.json.

Pipeline: edge-tts voice (free) -> Pixabay/Pexels stock clips (free API) ->
word-by-word captions (ASS) -> ffmpeg render (+ optional music).

Usage:
    export PIXABAY_API_KEY=...   # or PEXELS_API_KEY
    python make_videos.py          # all videos
    python make_videos.py 1 4 7    # only these ids
"""
import asyncio
import json
import math
import os
import pathlib
import random
import subprocess
import sys

import edge_tts
import requests

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "output"
CACHE = ROOT / "cache"
MUSIC_DIR = ROOT / "music"

VOICE = os.getenv("VOICE", "en-US-AndrewNeural")
RATE = os.getenv("RATE", "+6%")
W, H, FPS = 1080, 1920, 30
CLIP_SEC = 2.8          # average length of one stock clip
MUSIC_VOLUME = 0.10
PEXELS_KEY = os.getenv("PEXELS_API_KEY", "")
PIXABAY_KEY = os.getenv("PIXABAY_API_KEY", "")


# ---------------------------------------------------------------- helpers
def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
        raise RuntimeError(f"command failed: {' '.join(map(str, cmd[:3]))} ...")


def media_duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)])
    return float(out.decode().strip())


# ---------------------------------------------------------------- voice
async def _tts(text, mp3, words):
    try:
        comm = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary")
    except TypeError:  # older edge-tts: word boundaries are the default
        comm = edge_tts.Communicate(text, VOICE, rate=RATE)
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                end = (chunk["offset"] + chunk["duration"]) / 1e7
                words.append((start, end, chunk["text"]))


def make_voice(text, mp3):
    words = []
    for attempt in range(3):
        try:
            words.clear()
            asyncio.run(_tts(text, mp3, words))
            break
        except Exception as e:  # network hiccup -> retry
            print(f"  tts retry {attempt + 1}: {e}")
            if attempt == 2:
                raise
    dur = media_duration(mp3)
    if not words:  # fallback: spread words evenly
        toks = text.split()
        step = dur / len(toks)
        words = [(i * step, (i + 1) * step, t) for i, t in enumerate(toks)]
    return words, dur


# ---------------------------------------------------------------- captions
def _ass_time(t):
    cs = max(0, round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


ASS_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,104,&H0000F0FF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,9,3,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def make_ass(words, path, per_chunk=2):
    chunks = [words[i:i + per_chunk] for i in range(0, len(words), per_chunk)]
    lines = [ASS_HEADER]
    for i, ch in enumerate(chunks):
        start = ch[0][0]
        nxt = chunks[i + 1][0][0] if i + 1 < len(chunks) else ch[-1][1] + 0.3
        end = max(nxt, start + 0.15)
        text = " ".join(w[2] for w in ch).upper().replace("{", "").replace("}", "")
        pop = r"{\fscx85\fscy85\t(0,90,\fscx100\fscy100)}"
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{pop}{text}")
    pathlib.Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- stock clips
# Every provider returns a list of {"id": str, "link": mp4 url}
def pexels_search(query, per_page=15):
    headers = {"Authorization": PEXELS_KEY}
    for orientation in ("portrait", None):
        params = {"query": query, "per_page": per_page, "size": "medium"}
        if orientation:
            params["orientation"] = orientation
        r = requests.get("https://api.pexels.com/videos/search",
                         headers=headers, params=params, timeout=30)
        r.raise_for_status()
        res = []
        for v in r.json().get("videos", []):
            files = [f for f in v["video_files"]
                     if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
            if not files:
                continue
            big = sorted([f for f in files if f["height"] >= 1280], key=lambda f: f["height"])
            f = big[0] if big else sorted(files, key=lambda f: -f["height"])[0]
            res.append({"id": f"pexels_{v['id']}", "link": f["link"]})
        if res:
            return res
    return []


def pixabay_search(query, per_page=15):
    r = requests.get("https://pixabay.com/api/videos/",
                     params={"key": PIXABAY_KEY, "q": query, "per_page": per_page,
                             "safesearch": "true"}, timeout=30)
    r.raise_for_status()
    res = []
    for h in r.json().get("hits", []):
        vids = h.get("videos", {})
        for size in ("large", "medium", "small"):
            if vids.get(size, {}).get("url"):
                res.append({"id": f"pixabay_{h['id']}", "link": vids[size]["url"]})
                break
    return res


def stock_search(query):
    return pixabay_search(query) if PIXABAY_KEY else pexels_search(query)


def pick_clips(keywords, n):
    pools, used, picks = {}, set(), []
    for i in range(n):
        kw = keywords[i % len(keywords)]
        if kw not in pools:
            pools[kw] = stock_search(kw)
        cand = [v for v in pools[kw] if v["id"] not in used]
        if not cand:
            cand = [v for p in pools.values() for v in p if v["id"] not in used]
        if not cand:
            cand = [v for p in pools.values() for v in p]
        if not cand:
            raise RuntimeError(f"no stock results for {keywords}")
        v = cand[0]
        used.add(v["id"])
        picks.append(v)
    return picks


def download_clip(v):
    CACHE.mkdir(exist_ok=True)
    dest = CACHE / f"{v['id']}.mp4"
    if dest.exists():
        return dest
    with requests.get(v["link"], stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for part in r.iter_content(1 << 16):
                fh.write(part)
    return dest


# ---------------------------------------------------------------- render
def build(item):
    OUT.mkdir(exist_ok=True)
    name = f"{item['id']:02d}_{item['slug']}"
    out = OUT / f"{name}.mp4"
    if out.exists():
        print(f"[skip] {name} already exists")
        return
    print(f"[make] {name}")

    work = CACHE / f"work_{name}"
    work.mkdir(parents=True, exist_ok=True)
    text = f"{item['hook']} {item['script']}"

    words, dur = make_voice(text, work / "voice.mp3")
    total = dur + 0.5
    make_ass(words, work / "subs.ass")

    n = max(3, math.ceil(total / CLIP_SEC))
    seg = total / n
    clips = pick_clips(item["keywords"], n)

    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},setsar=1,fps={FPS},eq=brightness=-0.04:saturation=1.1")
    seg_files = []
    for i, v in enumerate(clips):
        src = download_clip(v)
        seg_name = f"seg_{i:02d}.mp4"
        run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(src.resolve()),
             "-t", f"{seg:.3f}", "-vf", vf, "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-pix_fmt", "yuv420p", seg_name], cwd=work)
        seg_files.append(seg_name)

    (work / "list.txt").write_text("".join(f"file '{s}'\n" for s in seg_files))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
         "-c", "copy", "video.mp4"], cwd=work)

    music = sorted(MUSIC_DIR.glob("*.mp3")) if MUSIC_DIR.exists() else []
    cmd = ["ffmpeg", "-y", "-i", "video.mp4", "-i", "voice.mp3"]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(random.choice(music).resolve())]
        fc = (f"[0:v]ass=subs.ass[v];"
              f"[1:a]apad=whole_dur={total:.3f}[a1];"
              f"[2:a]volume={MUSIC_VOLUME}[a2];"
              f"[a1][a2]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    else:
        fc = f"[0:v]ass=subs.ass[v];[1:a]apad=whole_dur={total:.3f}[a]"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            "-t", f"{total:.3f}", str(out.resolve())]
    run(cmd, cwd=work)

    (OUT / f"{name}.txt").write_text(
        f"TITLE:\n{item['title']} #shorts\n\n"
        f"DESCRIPTION:\n{item['hook']}\n\n#shorts #history #facts #historyfacts #didyouknow\n",
        encoding="utf-8")
    print(f"[done] {out.name} ({total:.1f}s)")


def main():
    if not (PIXABAY_KEY or PEXELS_KEY):
        sys.exit("Set PIXABAY_API_KEY (free: https://pixabay.com/api/docs/) "
                 "or PEXELS_API_KEY")
    items = json.loads((ROOT / "scripts.json").read_text(encoding="utf-8"))
    wanted = {int(a) for a in sys.argv[1:] if a.strip().isdigit()}
    for item in items:
        if wanted and item["id"] not in wanted:
            continue
        try:
            build(item)
        except Exception as e:
            print(f"[fail] {item['slug']}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()

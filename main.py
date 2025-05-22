import base64
import os
import json
import subprocess
import re

import cv2
import pandas as pd
from PIL import Image
import openai
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VIDEO_FILE = "chat_with_video.mp4"
FRAME_DIR = "frames"
TITLE_DIR = "titles"
SEGMENT_DIR = "segments"
CACHE_FILE = "ocr_cache.json"
INTERVAL_SECONDS = 3    # seconds between sampled frames
FRAME_JUMP = 3          # stride for coarse end detection
MAX_GAP_SECONDS = 60
MIN_SEGMENT_DURATION = 5
SIMILARITY_THRESHOLD = 0.7
DEBUG_MODE = True


if not os.getenv("OPENAI_API_KEY"):
    print("OPEN AI API KEY NOT FOUND!")

openai.api_key = os.getenv("OPENAI_API_KEY")
MODEL = "gpt-4o-mini"  # adjust as needed

# Create folders if they don't exist
for dir_path in [FRAME_DIR, TITLE_DIR, SEGMENT_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_frame_path(idx: int) -> str:
    return os.path.join(FRAME_DIR, f"frame_{idx+1:04d}.jpg")


def get_title_path(idx: int) -> str:
    return os.path.join(TITLE_DIR, f"frame_{idx+1:04d}.jpg")

# Fuzzy-similarity utilities
try:
    from rapidfuzz import fuzz
    USING_RAPIDFUZZ = True
    print("USING RAPIDFUZZ")
except ImportError:
    from difflib import SequenceMatcher
    USING_RAPIDFUZZ = False
    print("NOT USING RAPIDFUZZ")


def calculate_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if USING_RAPIDFUZZ:
        return fuzz.token_sort_ratio(a, b) / 100.0  # type: ignore
    return SequenceMatcher(None, a, b).ratio()  # type: ignore


def is_same_youtube_id(id1, id2) -> bool:
    if not id1 or not id2:
        return False
    if id1.lower() == id2.lower():
        return True
    score = calculate_similarity(id1, id2)
    print(id1, id2, "SCORE:", score)
    return score >= SIMILARITY_THRESHOLD


def is_similar_title(t1: str, t2: str) -> bool:
    if not t1 or not t2:
        return False
    if "No Title" in (t1, t2):
        return False
    return calculate_similarity(t1, t2) >= SIMILARITY_THRESHOLD

# RapidOCR for text detection
RAPIDOCR_AVAILABLE = False
OCR_ENGINE = None
try:
    from rapidocr_onnxruntime import RapidOCR
    OCR_ENGINE = RapidOCR()
    RAPIDOCR_AVAILABLE = True
    print("USING RAPIDOCR! YAY!")
except Exception as e:
    print(e)
    print("RAPIDOCR NOT FOUND! WTF!")
    # No fallback - we're specifically switching to RapidOCR


def ocr_extract_text(img: 'cv2.Mat') -> str:
    # Preprocess: grayscale, upscale, threshold, blur
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    blur = cv2.medianBlur(th, 3)

    if RAPIDOCR_AVAILABLE:
        try:
            # RapidOCR expects RGB image
            rgb_image = cv2.cvtColor(blur, cv2.COLOR_GRAY2RGB)
            # Run RapidOCR
            ocr_result = OCR_ENGINE(rgb_image)

            # Handle different versions of RapidOCR API
            if len(ocr_result) == 3:
                result, boxes_list, _ = ocr_result
            elif len(ocr_result) == 2:
                result, boxes_list = ocr_result
            else:
                print(f"Unexpected RapidOCR result format: {ocr_result}")
                return ""

            # Extract text from result
            if result and isinstance(result, list):
                try:
                    # Try standard format: list of [text, confidence] pairs
                    return " ".join([text for text, _ in result]) if result else ""
                except ValueError:
                    # If that fails, just join whatever elements are there
                    return " ".join([str(item) for item in result if item])
            else:
                return ""
        except Exception as e:
            print(f"RapidOCR error: {e}")
            return ""
    else:
        # No OCR engine available
        print("No OCR engine available")
        return ""


def get_text_from_image(path: str) -> str:
    img = cv2.imread(path)
    if img is None:
        return None
    text = ocr_extract_text(img)
    return text.replace("\n", " ").strip() if text else None

# ---------------------------------------------------------------------------
# GPT-based title extraction (called once)
# ---------------------------------------------------------------------------
def get_title_with_gpt(frame_path: str) -> str:
    # 1. Read & base64-encode the image
    with open(frame_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    # 2. Build the messages using the multimodal schema
    messages = [
        {
            "role": "system",
            "content": (
                "You are an assistant that extracts video titles from provided images. "
                "Respond strictly with JSON: {\"title\": \"…\"}."
            )
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Forsen is watching a YouTube video. What is the exact title? "
                        "Respond ONLY with JSON in the form:\n"
                        "{\"title\":\"<the video's title>\"}."
                    )
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}"
                    }
                }
            ]
        }
    ]

    # 3. Call the chat completion endpoint
    resp = openai.chat.completions.create(
        model=MODEL,
        messages=messages,
    )

    # 4. Parse the JSON out of GPT's response
    content = resp.choices[0].message.content
    data = json.loads(content)
    return data.get("title", "")
# ---------------------------------------------------------------------------
# YouTube ID extraction via regex
# ---------------------------------------------------------------------------
def extract_youtube_id(text: str) -> str:
    if not text:
        return None
    patterns = [
        r'(?:youtu\.be/|youtube\.com/watch\?v=)([\w-]{11})',
        r'youtube\.com/embed/([\w-]{11})',
        r'([\w-]{11})'
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            potential = m.group(1)
            has_alpha = False
            for c in potential:
                if c.isalpha():
                    has_alpha = True

            if not has_alpha:
                return None
            return potential
    return None

# ---------------------------------------------------------------------------
# Frame extraction (unchanged)
# ---------------------------------------------------------------------------
def extract_frames_from_video():
    # Create frame dir if doesn't exist

    if os.listdir(FRAME_DIR):
        print(f"ℹ️ Using existing frames in {FRAME_DIR}")
        return
    print(f"Extracting frames every {INTERVAL_SECONDS}s…")
    subprocess.run([
        "ffmpeg", "-i", VIDEO_FILE,
        "-vf", f"fps=1/{INTERVAL_SECONDS},crop=in_w*0.4:in_h*0.0475:in_w*0.03:in_h*0.875",
        f"{TITLE_DIR}/frame_%04d.jpg",
        "-hide_banner", "-loglevel", "error"
    ], check=True)
    subprocess.run([
        "ffmpeg", "-i", VIDEO_FILE,
        "-vf", f"fps=1/{INTERVAL_SECONDS},crop=in_w*0.4:in_h*0.06:in_w*0.055:in_h*0.03",
        f"{FRAME_DIR}/frame_%04d.jpg",
        "-hide_banner", "-loglevel", "error"
    ], check=True)
    print("✅ Frames & title crops extracted.")

# ---------------------------------------------------------------------------
# Binary-search for exact segment start (uses OCR)
# ---------------------------------------------------------------------------
def find_exact_start(idx, yt_id, total, last_end):
    lookback = int(MAX_GAP_SECONDS / INTERVAL_SECONDS) + 1
    start = max(last_end + 1, idx - lookback)
    end = idx
    res = idx

    # Grab the reference text at the detected frame for fuzzy comparison
    ref_txt = get_text_from_image(get_frame_path(idx)) or ""

    while start <= end:
        mid = (start + end) // 2
        txt = get_text_from_image(get_frame_path(mid)) or ""
        cid = extract_youtube_id(txt)

        # True if exact/fuzzy ID match, or if the OCR text is similar enough to the reference
        if (cid and is_same_youtube_id(cid, yt_id)) or calculate_similarity(txt, ref_txt) >= SIMILARITY_THRESHOLD:
            res = mid
            end = mid - 1
        else:
            start = mid + 1

    return res

# ---------------------------------------------------------------------------
# Merge overlapping or similar segments
# ---------------------------------------------------------------------------
def merge_similar_segments(segs):
    if not segs:
        return []
    segs = sorted(segs, key=lambda x: x[1])
    merged = []
    i = 0
    while i < len(segs):
        cid, st, ed, title = segs[i]
        j = i + 1
        while j < len(segs):
            ncid, nst, ned, ntitle = segs[j]
            gap = nst - ed
            if gap <= MAX_GAP_SECONDS and (is_same_youtube_id(cid, ncid) or is_similar_title(title, ntitle)):
                ed = max(ed, ned)
                cid = ncid if len(ncid) > len(cid) else cid
                title = ntitle if len(ntitle) > len(title) else title
                j += 1
            else:
                break
        merged.append((cid, st, ed, title))
        i = j
    return merged

# ---------------------------------------------------------------------------
# Segment detection using OCR for IDs and a single GPT call for title
# ---------------------------------------------------------------------------
def find_youtube_segments():
    extract_frames_from_video()
    total = len([f for f in os.listdir(FRAME_DIR) if f.endswith('.jpg')])

    title_map: dict[str, str] = {}   # yt_id → extracted title
    raw = []
    last_end = -1
    idx = 0

    while idx < total:
        if idx % 50 == 0:
            print(f"Progress: {idx}/{total}")

        txt = get_text_from_image(get_frame_path(idx))
        yt_id = extract_youtube_id(txt)

        if yt_id and idx > last_end:
            # 1) If we've never seen this video-id, extract its title now:
            if yt_id not in title_map:
                # pick a reasonable "title crop" frame—here I use the same idx,
                # but you could pick `mid_idx` of the block or any representative frame
                title_frame = get_title_path(idx)
                try:
                    title_map[yt_id] = get_title_with_gpt(title_frame)
                except Exception as e:
                    title_map[yt_id] = ""
                    print(f"⚠️ GPT vision failed for {yt_id}@frame{idx}: {e}")
                print(f"🎥 Extracted title for {yt_id}: {title_map[yt_id]}")

            video_title = title_map[yt_id]

            # 2) Find exact segment boundaries as before
            rs = find_exact_start(idx, yt_id, total, last_end)
            start_f = max(last_end + 1, rs - 1, 0)

            # coarse jump to find the next change
            nf = start_f + 1
            while nf < total and not extract_youtube_id(get_text_from_image(get_frame_path(nf))):
                nf += 1
            end_f = nf - 1 if nf < total else total - 1

            raw.append((
                yt_id,
                start_f * INTERVAL_SECONDS,
                end_f   * INTERVAL_SECONDS,
                video_title
            ))
            last_end = end_f
            idx = end_f + 1
        else:
            idx += FRAME_JUMP

    return merge_similar_segments(raw)

# ---------------------------------------------------------------------------
# Clip extraction (unchanged)
# ---------------------------------------------------------------------------
def extract_segment_clips(segs):
    os.makedirs(SEGMENT_DIR, exist_ok=True)

    def get_unique_filename(base_name):
        """Generate a unique filename with Part suffix if needed."""
        name, ext = os.path.splitext(base_name)
        candidate = os.path.join(SEGMENT_DIR, base_name)
        part = 2
        while os.path.exists(candidate):
            candidate = os.path.join(SEGMENT_DIR, f"{name} Part {part}{ext}")
            part += 1
        return candidate

    for i, (yt_id, st, ed, title) in enumerate(segs, 1):
        safe = re.sub(r'[\\/*?:"<>|]', '', title)
        truncated = f"Forsen Reacts to {safe[:78]}.mp4"
        out = get_unique_filename(truncated[:100])
        dur = ed - st
        print(f"Extracting {i}/{len(segs)}: {yt_id} ({dur}s) → {out}")
        try:
            subprocess.run([
                "ffmpeg", "-ss", str(st), "-i", VIDEO_FILE,
                "-t", str(dur), "-c:v", "copy", "-c:a", "copy", out
            ], check=True)
        except subprocess.CalledProcessError:
            subprocess.run([
                "ffmpeg", "-ss", str(st), "-i", VIDEO_FILE,
                "-t", str(dur), out
            ], check=True)

if __name__ == "__main__":
    print("=== YouTube Segment Detector (one GPT call per video) ===")
    segments = find_youtube_segments()
    filt = [(cid, st, ed, t) for cid, st, ed, t in segments if (ed - st) >= MIN_SEGMENT_DURATION]
    if not filt:
        print("No segments meet the minimum duration.")
    else:
        for cid, st, ed, title in filt:
            m1, s1 = divmod(st, 60)
            m2, s2 = divmod(ed, 60)
            print(f"ID {cid}: {m1}:{s1:02d}–{m2}:{s2:02d} (Title: {title})")
        df = pd.DataFrame(filt, columns=["YouTube ID","Start (s)","End (s)","Title"])
        df.to_csv("segments.csv", index=False)
        print("Saved segments.csv")
        extract_segment_clips(filt)
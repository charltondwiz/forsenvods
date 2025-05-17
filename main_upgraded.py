import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import rapidfuzz.fuzz as rfuzz

# Optional PyAV for faster decode
try:
    import av
    PYAV_AVAILABLE = True
except ImportError:
    PYAV_AVAILABLE = False

# Optional PaddleOCR GPU
try:
    import paddleocr
    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False

# ---------------------------------------------------------------------------
# Config and setup
# ---------------------------------------------------------------------------

DEBUG_DIR = Path("debug")
DEBUG_DIR.mkdir(exist_ok=True)

@dataclass
class Config:
    vod_file: Path
    interval_sec: int = 3
    url_roi: Tuple[float, float, float, float] = (0.055, 0.03, 0.4, 0.06)
    title_roi: Tuple[float, float, float, float] = (0.03, 0.875, 0.4, 0.0475)
    similarity_threshold: float = 0.7
    min_segment_sec: int = 5
    out_dir: Path = Path("segments")
    cache_file: Path = Path("ocr_cache.json")
    show_progress: bool = True

# Simple print-based logger
class _PrintLogger:
    def info(self, *args, **kwargs): print(*args)
    def warning(self, *args, **kwargs): print(*args)
    def error(self, *args, **kwargs): print(*args)
    def debug(self, *args, **kwargs): pass

log = _PrintLogger()
init_logging = lambda verbose: None

# ---------------------------------------------------------------------------
# OCR helper
# ---------------------------------------------------------------------------

ALLOWED = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:/.?=&_"

def init_paddle() -> Optional[paddleocr.PaddleOCR]:
    if not PADDLE_AVAILABLE:
        return None
    try:
        log.info("Initializing PaddleOCR GPU...")
        return paddleocr.PaddleOCR(use_angle_cls=False, use_gpu=True, lang="en")  # type: ignore
    except Exception as e:
        log.warning("PaddleOCR init failed, falling back to Tesseract:", e)
        return None

import re

def ocr_text(img: np.ndarray, paddle: Optional[paddleocr.PaddleOCR]) -> str:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    if paddle:
        res = paddle.ocr(thresh, cls=False, det=False, rec=True)
        text = "".join([r[0][0] for r in res]) if res else ""
    else:
        import pytesseract
        cfg = f"--oem 3 --psm 7 -c tessedit_char_whitelist={ALLOWED} -l eng"
        text = pytesseract.image_to_string(thresh, config=cfg)
    return re.sub(r"\s+", " ", text.strip())

# ---------------------------------------------------------------------------
# Video frame iterator optimized
# ---------------------------------------------------------------------------

def iter_rois_cpu(cfg: Config):
    cap = cv2.VideoCapture(str(cfg.vod_file))
    fps = cap.get(cv2.CAP_PROP_FPS)
    stride = int(round(cfg.interval_sec * fps))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # precompute absolute ROI coords
    def to_abs(rel):
        x, y, w, h = rel
        x1, y1 = int(x * width), int(y * height)
        return x1, y1, int(w * width), int(h * height)
    url_box = to_abs(cfg.url_roi)
    title_box = to_abs(cfg.title_roi)

    idx = 0
    grabbed = True
    while grabbed:
        # grab frames until next stride
        for _ in range(stride):
            grabbed = cap.grab()
            if not grabbed:
                break
        if not grabbed:
            break
        _, frame = cap.retrieve()

        # debug dump every 90th sample
        if idx % 90 == 0:
            p = DEBUG_DIR / f"raw_frame_{idx:05d}.png"
            cv2.imwrite(str(p), frame)

        # crops
        x1, y1, w, h = url_box
        url_crop = frame[y1:y1+h, x1:x1+w]
        x1, y1, w, h = title_box
        title_crop = frame[y1:y1+h, x1:x1+w]

        yield idx, url_crop, title_crop
        idx += 1
    cap.release()

if PYAV_AVAILABLE:
    def iter_rois_av(cfg: Config):
        container = av.open(str(cfg.vod_file))
        stream = container.streams.video[0]
        W, H = stream.codec_context.width, stream.codec_context.height
        url_box = (int(cfg.url_roi[0]*W), int(cfg.url_roi[1]*H), int(cfg.url_roi[2]*W), int(cfg.url_roi[3]*H))
        title_box = (int(cfg.title_roi[0]*W), int(cfg.title_roi[1]*H), int(cfg.title_roi[2]*W), int(cfg.title_roi[3]*H))
        sec_per_pts = 1.0 / stream.average_rate
        target_time = 0.0
        idx = 0

        for frame in container.decode(video=0):
            pts = frame.pts * sec_per_pts
            if pts + 1e-3 < target_time:
                continue
            img = frame.to_ndarray(format="bgr24")
            if idx % 90 == 0:
                p = DEBUG_DIR / f"raw_frame_{idx:05d}.png"
                cv2.imwrite(str(p), img)

            x1, y1, w, h = url_box
            url_crop = img[y1:y1+h, x1:x1+w]
            x1, y1, w, h = title_box
            title_crop = img[y1:y1+h, x1:x1+w]

            yield idx, url_crop, title_crop
            idx += 1
            target_time += cfg.interval_sec

# ---------------------------------------------------------------------------
# Similarity & ID extraction
# ---------------------------------------------------------------------------

def id_similarity(a: str, b: str) -> float:
    return rfuzz.ratio(a, b) / 100.0

import re
youtube_patterns = [re.compile(r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|embed/|v/))([\w-]{11})"),
                    re.compile(r"\b([\w-]{11})\b")]

def extract_youtube_id(text: str) -> Optional[str]:
    for pat in youtube_patterns:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None

# ---------------------------------------------------------------------------
# Segment detection
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    vid: str
    start_sec: int
    end_sec: int
    title: str


def detect_segments(cfg: Config, paddle: Optional[paddleocr.PaddleOCR], total_frames: int) -> List[Segment]:
    cache: Dict[int, Tuple[str, str]] = json.loads(cfg.cache_file.read_text()) if cfg.cache_file.exists() else {}
    segments: List[Segment] = []
    current_id: Optional[str] = None
    current_title: str = ""
    seg_start: int = 0

    iterator = iter_rois_av(cfg) if PYAV_AVAILABLE else iter_rois_cpu(cfg)

    for idx, url_crop, title_crop in iterator:
        ts = idx * cfg.interval_sec
        if idx in cache:
            url_text, title_text = cache[idx]
        else:
            url_text = ocr_text(url_crop, paddle)
            title_text = ocr_text(title_crop, paddle)
            cache[idx] = (url_text, title_text)
            if idx % 100 == 0:
                cfg.cache_file.write_text(json.dumps(cache))

        yid = extract_youtube_id(url_text) or "__NONE__"
        if current_id is None:
            current_id, current_title, seg_start = yid, title_text, ts
            continue

        if id_similarity(current_id, yid) >= cfg.similarity_threshold:
            continue

        seg_end = ts
        if current_id != "__NONE__" and seg_end - seg_start >= cfg.min_segment_sec:
            segments.append(Segment(current_id, seg_start, seg_end, current_title))

        current_id, current_title, seg_start = yid, title_text, ts

    cfg.cache_file.write_text(json.dumps(cache))
    return segments

# ---------------------------------------------------------------------------
# Clip export
# ---------------------------------------------------------------------------

def export_clip(cfg: Config, seg: Segment):
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    h, m, s = seg.start_sec//3600, (seg.start_sec%3600)//60, seg.start_sec%60
    ts = f"{h:02d}-{m:02d}-{s:02d}"
    safe = re.sub(r"[^\w\- ]", "", (seg.title or "video")[:80]).strip() or "video"
    out = cfg.out_dir / f"Forsen Reacts to {safe} [{ts}].mp4"
    cmd = ["ffmpeg", "-y", "-hwaccel", "cuda", "-i", str(cfg.vod_file),
           "-ss", str(seg.start_sec), "-to", str(seg.end_sec),
           "-c:v", "h264_nvenc", "-c:a", "copy", str(out)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        log.error(f"FFmpeg error exporting {out.name}")
        out.unlink(missing_ok=True)

# ---------------------------------------------------------------------------\# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("vod", type=Path)
    p.add_argument("--interval", type=int, default=3)
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--no-progress", action="store_true")
    args = p.parse_args()

    cfg = Config(vod_file=args.vod, interval_sec=args.interval,
                 show_progress=not args.no_progress)
    init_logging(args.verbose)

    if not cfg.vod_file.exists():
        log.error("Input file not found", cfg.vod_file)
        sys.exit(1)

    # compute total samples for progress bar
    if PYAV_AVAILABLE:
        import av
        duration = av.open(str(cfg.vod_file)).duration / 1e6
    else:
        cap = cv2.VideoCapture(str(cfg.vod_file))
        duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
        cap.release()
    total = int(duration / cfg.interval_sec) + 1

    paddle = init_paddle()
    segments = detect_segments(cfg, paddle, total)
    log.info(f"Detected {len(segments)} segments")
    for seg in segments:
        export_clip(cfg, seg)
    log.info("Done.")

if __name__ == "__main__":
    main()

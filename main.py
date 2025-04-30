import os
import json
import subprocess
import re
from PIL import Image
import pytesseract
import cv2
import shutil
import pandas as pd
from datetime import datetime

try:
    from rapidfuzz import fuzz

    USING_RAPIDFUZZ = True
except ImportError:
    from difflib import SequenceMatcher

    USING_RAPIDFUZZ = False
    print("⚠️ rapidfuzz not found. Using slower difflib.SequenceMatcher instead.")
    print("   Install rapidfuzz with: pip install rapidfuzz")

# === CONFIG ===
VIDEO_FILE = "chat_with_video.mp4"
FRAME_DIR = "frames"
TITLE_DIR = "titles"
SEGMENT_DIR = "segments"
CACHE_FILE = "ocr_cache.json"
INTERVAL_SECONDS = 3
SIMILARITY_THRESHOLD = 0.4  # Threshold for fuzzy matching YouTube IDs (0.4 = 40% similar)
DEBUG_MODE = True  # Set to False to reduce logging
FRAME_JUMP = 10  # Number of frames to jump when scanning for changes
MAX_GAP_SECONDS = 60  # Maximum gap in seconds to consider segments as part of the same video
MIN_SEGMENT_DURATION = 5  # Minimum duration in seconds for a segment to be considered valid
last_title = ""

# Ensure required directories exist
os.makedirs(FRAME_DIR, exist_ok=True)
os.makedirs(SEGMENT_DIR, exist_ok=True)
os.makedirs(TITLE_DIR, exist_ok=True)
os.makedirs("post_processed", exist_ok=True)


# === UTILITIES ===
def get_frame_path(index):
    return os.path.join(FRAME_DIR, f"frame_{index + 1:04d}.jpg")


def get_title_path(index):
    return os.path.join(TITLE_DIR, f"frame_{index + 1:04d}.jpg")


def load_cache():
    return json.load(open(CACHE_FILE)) if os.path.exists(CACHE_FILE) else {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


# === STRING SIMILARITY CHECK ===
def calculate_similarity(str1, str2):
    """
    Calculate string similarity ratio between two strings.
    Uses rapidfuzz if available (faster and more accurate), otherwise falls back to SequenceMatcher.
    Returns a value between 0 and 1, where 1 means identical.
    """
    if not str1 or not str2:
        return 0

    # Make sure we're working with strings
    str1 = str(str1)
    str2 = str(str2)

    if USING_RAPIDFUZZ:
        # Using the token sort ratio which handles out-of-order substrings well
        return fuzz.token_sort_ratio(str1, str2) / 100.0
    else:
        # Fallback to SequenceMatcher
        return SequenceMatcher(None, str1, str2).ratio()


def is_similar_title(title1, title2):
    """
    Check if two video titles are similar using fuzzy matching.
    """
    if not title1 or not title2:
        return False

    # If either is "No Title", check if the other has content
    if title1 == "No Title" and title2 and title2 != "No Title":
        return False
    if title2 == "No Title" and title1 and title1 != "No Title":
        return False

    # Exact match
    if title1 == title2:
        return True

    # Fuzzy match above threshold
    similarity = calculate_similarity(title1, title2)
    if similarity >= SIMILARITY_THRESHOLD:
        if DEBUG_MODE:
            print(f"  📑 Title match: '{title1}' ≈ '{title2}' (similarity: {similarity:.2f})")
        return True

    return False


def is_same_youtube_id(id1, id2):
    """
    Check if two YouTube IDs are likely the same, accounting for OCR errors
    using fuzzy string matching.
    """
    # If either ID is None, they're not the same
    if id1 is None or id2 is None:
        return False

    # Exact match
    if id1 == id2:
        return True

    # Special handling for known patterns in your data
    # For cases like "AnglsoeuSs", "Anlabeuss", "Angylbeuss", etc.
    if id1.lower().startswith("angl") and id2.lower().startswith("angl"):
        return True
    if id1.lower().startswith("angl") and id2.lower().startswith("anyl"):
        return True
    if id1.lower().startswith("anyl") and id2.lower().startswith("angl"):
        return True

    # Special handling for "impWa" patterns
    if id1.lower().startswith("impwa") and id2.lower().startswith("impwa"):
        return True
    if id1.lower().startswith("impma") and id2.lower().startswith("impwa"):
        return True
    if id1.lower().startswith("impa") and id2.lower().startswith("impwa"):
        return True
    if id1.lower().startswith("imym") and id2.lower().startswith("impwa"):
        return True
    if id1.lower().startswith("imym") and id2.lower().startswith("impma"):
        return True

    # Special handling for similar looking IDs with different cases
    if id1.lower() == id2.lower():
        return True

    # Check first 5 characters - if they match, likely the same video with OCR errors
    if len(id1) >= 5 and len(id2) >= 5 and id1[:5].lower() == id2[:5].lower():
        if DEBUG_MODE:
            print(f"  👀 Prefix match: {id1} ≈ {id2} (first 5 chars match)")
        return True

    # Fuzzy match above threshold
    similarity = calculate_similarity(id1, id2)
    if similarity >= SIMILARITY_THRESHOLD:
        if DEBUG_MODE:
            print(f"  👀 Fuzzy match: {id1} ≈ {id2} (similarity: {similarity:.2f})")
        return True

    return False


# === EXTRACT YOUTUBE ID FROM URL ===
def extract_youtube_id(url):
    """Extract YouTube ID from various formats of YouTube URLs."""
    if not url or url == "None":
        return None

    # Check if the URL is just "youtube" or similar basic word without ID
    if url.lower() in ["youtube", "youtube.com"]:
        return None

    # Try different YouTube URL patterns for standard 11-char IDs
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})',  # Standard and shortened
        r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',  # Embed URLs
        r'youtube\.com/v/([a-zA-Z0-9_-]{11})',  # Old embed
        r'youtube\.com/user/\w+/\w+/([a-zA-Z0-9_-]{11})'  # User page
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    # Try more flexible patterns for non-standard IDs
    flexible_patterns = [
        r'youtube\.com/watch\?v=([a-zA-Z0-9_-]{5,})',  # Any length ID after watch?v=
        r'youtu\.be/([a-zA-Z0-9_-]{5,})'  # Any length ID after youtu.be/
    ]

    for pattern in flexible_patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    # If no pattern matches but URL seems like it might be just the ID itself
    if re.match(r'^[a-zA-Z0-9_-]{5,}$', url):
        return url

    # Extract anything that looks like an ID from the URL
    id_match = re.search(r'v=([a-zA-Z0-9_-]{5,})', url)
    if id_match:
        return id_match.group(1)

    # No valid YouTube ID found
    return None


# === EXTRACT FRAMES FROM VIDEO ===
def extract_frames_from_video():
    if not os.listdir(FRAME_DIR):
        print(f"Extracting frames from {VIDEO_FILE} at {INTERVAL_SECONDS} second intervals...")
        subprocess.run([
            "ffmpeg", "-i", VIDEO_FILE,
            "-vf", f"fps=1/{INTERVAL_SECONDS}, crop=in_w*0.4:in_h*0.06:in_w*0.055:in_h*0.03",
            f"{FRAME_DIR}/frame_%04d.jpg",
            "-hide_banner", "-loglevel", "error"
        ])
        print(f"Frames extracted to {FRAME_DIR}/")

        print("Extracting titles from frames...")
        subprocess.run([
            "ffmpeg", "-i", VIDEO_FILE,
            "-vf", f"fps=1/{INTERVAL_SECONDS}, crop=in_w*0.4:in_h*0.0475:in_w*0.03:in_h * 0.875",
            f"{TITLE_DIR}/frame_%04d.jpg",
            "-hide_banner", "-loglevel", "error"
        ])
    else:
        print(f"Using existing frames in {FRAME_DIR}/")


# === PERFORM OCR WITH PYTESSERACT ===
def get_text_from_image(frame_path, post_process_folder="post_processed", allow_space=False):
    """Extract text from an image using Pytesseract OCR with preprocessing."""
    try:
        # Read image using OpenCV
        img_cv = cv2.imread(frame_path)
        if img_cv is None:
            print(f"⚠️ Failed to read image: {frame_path}")
            return None

        # Convert to grayscale
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

        # Resize for better OCR (1.5x or 2x)
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

        # Use Otsu's threshold instead of adaptive
        _, thresh = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

        # Optional: Denoise (comment out if text becomes blurry)
        processed_img = cv2.medianBlur(thresh, 3)

        # Convert back to PIL Image for pytesseract
        pil_img = Image.fromarray(processed_img)

        allowed_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:/.?=&_"
        if allow_space:
            allowed_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.!?&_()-+=, "

        custom_config = (
            r'--oem 3 --psm 7 '
            f'-c tessedit_char_whitelist="{allowed_chars}"'
        )
        # === Save processed image ===
        try:
            os.makedirs(post_process_folder, exist_ok=True)
            save_name = os.path.basename(frame_path)
            save_path = os.path.join(post_process_folder, save_name)

            success = cv2.imwrite(save_path, processed_img)
            if success:
                print(f"✅ Saved processed image to {save_path}")
            else:
                print(f"❌ Failed to save image at {save_path}")

        except Exception as save_err:
            print(f"❗ Error saving image: {save_err}")

        text = pytesseract.image_to_string(pil_img, config=custom_config)

        # Clean up
        return text.strip().replace('\n', ' ')
    except Exception as e:
        print(f"Error during OCR: {e}")
        return None


# === CALL TESSERACT WITH CACHING ===
def get_youtube_url_from_frame(index, cache):
    frame_path = get_frame_path(index)
    if not os.path.exists(frame_path):
        return "None"

    cache_key = str(index)
    if cache_key in cache:
        return cache[cache_key]

    print(f"🔍 OCR checking frame {index}")

    # Get text from image using OCR
    extracted_text = get_text_from_image(frame_path)

    # Look for YouTube URLs in the extracted text
    youtube_url = None
    if extracted_text:
        # Common patterns for YouTube URLs
        url_patterns = [
            r'https?://(?:www\.)?youtube\.com/watch\?v=[a-zA-Z0-9_-]+',
            r'https?://youtu\.be/[a-zA-Z0-9_-]+',
            r'youtube\.com/watch\?v=[a-zA-Z0-9_-]+'
        ]

        for pattern in url_patterns:
            matches = re.findall(pattern, extracted_text)
            if matches:
                youtube_url = matches[0]
                break

    # If no URL found, just return the raw text for ID extraction to handle
    result = youtube_url if youtube_url else extracted_text if extracted_text else "None"

    cache[cache_key] = result
    save_cache(cache)
    return result


# === GET YOUTUBE ID FROM FRAME ===
def get_youtube_id_from_frame(index, cache):
    """Get YouTube ID from frame by using Tesseract OCR and extracting ID from URL"""
    text_or_url = get_youtube_url_from_frame(index, cache)
    youtube_id = extract_youtube_id(text_or_url)

    if DEBUG_MODE:
        if youtube_id:
            global last_title
            print(f"  🔎 Frame {index}: Found ID '{youtube_id}' from text '{text_or_url}'")
            title_path = get_title_path(index)
            if os.path.exists(title_path):
                title = get_text_from_image(title_path, post_process_folder="post_processed_titles", allow_space=True)
                print(f"  🎥 Title: {title}")
                last_title = title if title else "No Title"
            else:
                print(f"  ⚠️ Title frame not found: {title_path}")
        else:
            print(f"  🔎 Frame {index}: No YouTube ID found from text '{text_or_url}'")

    return youtube_id, text_or_url, last_title


def cleanup_directories():
    """
    Removes the directories 'frames', 'post_processed', 'titles' and the file 'ocr_cache.json'
    This is equivalent to: rm -rf frames post_processed titles; rm ocr_cache.json
    """
    # List of directories to remove
    directories = ['frames', 'post_processed', 'post_processed_titles', 'titles']

    # Remove directories
    for directory in directories:
        if os.path.exists(directory):
            try:
                shutil.rmtree(directory)
                print(f"Successfully removed directory: {directory}")
            except Exception as e:
                print(f"Error removing directory {directory}: {e}")
        else:
            print(f"Directory does not exist: {directory}")

    # Remove the ocr_cache.json file
    if os.path.exists('ocr_cache.json'):
        try:
            os.remove('ocr_cache.json')
            print("Successfully removed file: ocr_cache.json")
        except Exception as e:
            print(f"Error removing ocr_cache.json: {e}")
    else:
        print("File does not exist: ocr_cache.json")


# === FIND EXACT START WITH BINARY SEARCH ===
def find_exact_start(frame_index, youtube_id, cache, total_frames, last_segment_end):
    """
    Use binary search to find the exact start frame of a YouTube segment.
    Respects the last_segment_end boundary - won't look for a start before this frame.
    """
    # Only look back up to 30 frames, but not before the end of the last segment
    start_search_range = max(last_segment_end + 1, frame_index - 30)

    print(f"  🔍 Binary searching for segment START between frames {start_search_range}-{frame_index}")

    start = start_search_range
    end = frame_index
    result = frame_index  # Default to current frame

    while start <= end:
        mid = (start + end) // 2
        check_id, _, _ = get_youtube_id_from_frame(mid, cache)

        if is_same_youtube_id(check_id, youtube_id):
            # This frame has our target ID - try to find an earlier frame
            result = mid
            end = mid - 1
            print(f"    ✓ Frame {mid} has target ID, updating result → {result}")
        else:
            # This frame doesn't have our ID - look later
            start = mid + 1
            print(f"    ✗ Frame {mid} doesn't have target ID, searching ({start}-{end})")

    print(f"  ✅ Segment starts at frame {result}")
    return result


# === EFFICIENTLY FIND SEGMENT END ===
def find_segment_end(start_frame, youtube_id, cache, total_frames):
    """
    Find where a YouTube segment ends by jumping ahead with FRAME_JUMP
    until the ID changes, then use binary search for the exact boundary.
    """
    # Start from the frame after the segment start
    current_frame = start_frame
    last_matching_frame = current_frame

    print(f"  🔍 Scanning forward to find segment end from frame {current_frame}")

    # Jump ahead by FRAME_JUMP frames until we find a frame that doesn't match our ID
    while current_frame < total_frames:
        check_id, _, _ = get_youtube_id_from_frame(current_frame, cache)

        if is_same_youtube_id(check_id, youtube_id):
            # Still the same segment
            last_matching_frame = current_frame
            current_frame += FRAME_JUMP
        else:
            # Found a different ID or no ID - segment might end here
            print(f"    ✓ Found potential segment end at frame {current_frame}")
            break

    if current_frame >= total_frames:
        # Reached the end of the video without finding the end of this segment
        print(f"    ⚠️ Segment extends to the end of the video")
        return total_frames - 1

    # Now use binary search to find the exact end between last_matching_frame and current_frame
    start = last_matching_frame
    end = current_frame

    print(f"  🔍 Binary searching for exact segment END between frames {start}-{end}")

    result = start  # Default to the last frame where we definitely found our ID

    while start <= end:
        mid = (start + end) // 2
        check_id, _, _ = get_youtube_id_from_frame(mid, cache)

        if is_same_youtube_id(check_id, youtube_id):
            # This frame still has our target ID - look later
            result = mid  # Update result to this confirmed matching frame
            start = mid + 1
            print(f"    ✓ Frame {mid} still has target ID, updating result → {result}")
        else:
            # This frame doesn't have our ID - try to find an earlier frame
            end = mid - 1
            print(f"    ✗ Frame {mid} doesn't have target ID, searching ({start}-{end})")

    print(f"  ✅ Segment ends at frame {result}")
    return result


# === FIND ALL YOUTUBE SEGMENTS ===
def find_youtube_segments():
    # Extract frames if not already done
    extract_frames_from_video()

    # Get total number of frames
    total_frames = len([f for f in os.listdir(FRAME_DIR) if f.endswith(".jpg")])
    print(f"Total frames: {total_frames}")

    cache = load_cache()
    raw_segments = []  # Store all detected segments before merging

    # Step through the video
    frame_index = 0

    # Keep track of the last segment's end to avoid overlaps
    last_segment_end = -1

    while frame_index < total_frames:
        # Print progress every 50 frames
        if frame_index % 50 == 0:
            print(f"\n📊 Progress: {frame_index}/{total_frames} ({frame_index / total_frames * 100:.1f}%)")

        # Check if current frame has a YouTube ID
        youtube_id, youtube_url, title = get_youtube_id_from_frame(frame_index, cache)

        if youtube_id:
            # Found a YouTube ID - check if it's part of an existing segment
            if raw_segments and frame_index <= last_segment_end:
                # Skip - we're still in a previously detected segment
                frame_index += FRAME_JUMP
                continue

            print(f"🎬 Found YouTube at frame {frame_index} (ID: {youtube_id})")

            # Find exact start of this segment (might be before current frame, but after last segment)
            segment_start_frame = find_exact_start(frame_index, youtube_id, cache, total_frames, last_segment_end)

            # Find where this segment ends - stepping forward until the ID changes
            segment_end_frame = find_segment_end(segment_start_frame, youtube_id, cache, total_frames)

            # Check if there's another YouTube ID in the next frame (for exact boundary)
            next_frame = segment_end_frame + 1
            next_youtube_id = None

            if next_frame < total_frames:
                next_youtube_id, _, _ = get_youtube_id_from_frame(next_frame, cache)

            # If there's a new YouTube ID in the next frame, use the current frame (no buffer)
            # Otherwise (it's likely the last segment), use 5 frames buffer
            if next_youtube_id and not is_same_youtube_id(youtube_id, next_youtube_id):
                print(f"  📊 Found new YouTube ID in next frame - using current frame as end (no buffer)")
                buffered_end_frame = segment_end_frame  # Use the current frame with no buffer
            else:
                print(f"  📊 No new YouTube ID detected - using 5 frame buffer")
                buffered_end_frame = min(segment_end_frame + 5, total_frames - 1)

            # Convert frames to timestamps
            start_time = segment_start_frame * INTERVAL_SECONDS
            end_time = buffered_end_frame * INTERVAL_SECONDS
            duration = end_time - start_time

            # Only add segments with minimum duration (at least 2 seconds)
            if duration >= 2:
                print(f"  📋 YouTube segment ({youtube_id}) from {start_time}s to {end_time}s (duration: {duration}s)")
                raw_segments.append((youtube_id, start_time, end_time, title, segment_start_frame, buffered_end_frame))

            # Update last segment end and jump past this segment
            last_segment_end = buffered_end_frame
            frame_index = buffered_end_frame + 1
        else:
            # No YouTube in this frame, move forward
            frame_index += FRAME_JUMP

    # Merge overlapping and adjacent segments with similar IDs
    merged_segments = merge_similar_segments(raw_segments)
    return merged_segments


# === MERGE SIMILAR SEGMENTS ===
def merge_similar_segments(segments):
    """
    Merge segments that have similar YouTube IDs OR similar titles and are close in time.
    This helps correct for OCR errors and brief interruptions in detection.
    """
    if not segments:
        return []

    # Sort segments by start time
    sorted_segments = sorted(segments, key=lambda x: x[1])

    # We'll merge segments in a completely different way:
    # 1. Start with first segment
    # 2. Keep merging adjacent segments if they match by ID OR title
    # 3. When no more merges are possible, start a new merged segment

    all_merged_segments = []
    i = 0

    while i < len(sorted_segments):
        # Start a new merged segment
        current = sorted_segments[i]
        curr_id, curr_start, curr_end, curr_title, curr_start_frame, curr_end_frame = current

        # Try to extend this segment as much as possible
        j = i + 1
        merged_count = 1

        while j < len(sorted_segments):
            next_seg = sorted_segments[j]
            next_id, next_start, next_end, next_title, next_start_frame, next_end_frame = next_seg

            # Calculate time gap
            time_gap = next_start - curr_end

            # Debug print - always show what we're considering
            print(f"\nConsidering merge: Segment {i} ({curr_id}, {curr_start}-{curr_end}s)")
            print(f"                  with Segment {j} ({next_id}, {next_start}-{next_end}s)")
            print(f"                  Time gap: {time_gap}s")
            print(f"                  Current title: '{curr_title}'")
            print(f"                  Next title: '{next_title}'")

            # Check ID similarity
            ids_match = is_same_youtube_id(curr_id, next_id)
            print(f"                  IDs match: {ids_match}")

            # Check title similarity
            titles_match = is_similar_title(curr_title, next_title)
            print(f"                  Titles match: {titles_match}")

            # Decision to merge if:
            # 1. Time gap is within threshold AND
            # 2. Either IDs match OR titles match
            should_merge = time_gap <= MAX_GAP_SECONDS and (ids_match or titles_match)

            if should_merge:
                # Merge the segments!
                print(f"  🔄 MERGING: {curr_id} ({curr_start}-{curr_end}s) with {next_id} ({next_start}-{next_end}s)")
                print(f"         Time gap: {time_gap}s, IDs match: {ids_match}, Titles match: {titles_match}")

                # Choose the better ID (prefer the longer, more complete one)
                id_to_use = curr_id if len(curr_id) >= len(next_id) else next_id

                # Choose the better title
                title_to_use = curr_title
                if (next_title and len(next_title) > len(curr_title or "")) and not re.search(
                        r'[^\w\s\[\]\(\)\-\+\.,;:!?]', next_title):
                    title_to_use = next_title

                # Update current segment boundaries
                curr_end = next_end
                curr_end_frame = next_end_frame
                curr_id = id_to_use
                curr_title = title_to_use

                merged_count += 1
                j += 1
            else:
                # Can't merge, stop extending this segment
                print(f"  ❌ NOT MERGING: Gap {time_gap}s too large or content doesn't match")
                break

        # Add the merged segment to our results
        merged_segment = (curr_id, curr_start, curr_end, curr_title)
        all_merged_segments.append(merged_segment)

        if merged_count > 1:
            print(f"  ✅ Created merged segment from {merged_count} segments: {curr_id} ({curr_start}-{curr_end}s)")

        # Move to the next unprocessed segment
        i = j

    print(f"\n✅ Merged {len(sorted_segments)} raw segments into {len(all_merged_segments)} final segments")
    return all_merged_segments


# === CREATE SEGMENT CLIPS ===
def extract_segment_clips(segments):
    for i, (youtube_id, start_time, end_time, title) in enumerate(segments):
        # Clean up title for filename
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title or "")  # Remove invalid filename characters
        if not safe_title or len(safe_title.strip()) < 2:
            safe_title = f"Video {i + 1}"

        # Format timestamp for filename
        timestamp = datetime.fromtimestamp(start_time).strftime("%H-%M-%S")

        output_file = os.path.join(SEGMENT_DIR, f"Forsen Reacts to {safe_title[:80]}.mp4")
        duration = end_time - start_time

        print(f"Extracting segment {i + 1}/{len(segments)}: {youtube_id} ({duration}s)")

        try:
            subprocess.run([
                "ffmpeg", "-i", VIDEO_FILE,
                "-ss", str(start_time),
                "-t", str(duration),
                "-c:v", "copy", "-c:a", "copy",
                output_file
            ], check=True)
            print(f"  ✅ Saved to {output_file}")
        except subprocess.CalledProcessError as e:
            print(f"  ❌ Error extracting segment: {e}")
            # Try again with re-encoding instead of stream copying
            try:
                print("  🔄 Retrying with re-encoding...")
                subprocess.run([
                    "ffmpeg", "-i", VIDEO_FILE,
                    "-ss", str(start_time),
                    "-t", str(duration),
                    output_file
                ], check=True)
                print(f"  ✅ Saved to {output_file} (with re-encoding)")
            except Exception as retry_error:
                print(f"  ❌ Retry failed: {retry_error}")


# === MAIN EXECUTION ===
if __name__ == "__main__":
    print("=== YouTube Segment Detector ===")
    segments = find_youtube_segments()

    if segments:
        # Filter out very short segments (likely errors)
        filtered_segments = []
        for youtube_id, start_time, end_time, title in segments:
            duration = end_time - start_time
            if duration >= MIN_SEGMENT_DURATION:
                filtered_segments.append((youtube_id, start_time, end_time, title))
            else:
                print(f"⚠️ Skipping short segment: {youtube_id} ({duration}s)")

        segments = filtered_segments

        print("\n=== Results ===")
        for youtube_id, start_time, end_time, title in segments:
            minutes_start = int(start_time // 60)
            seconds_start = int(start_time % 60)
            minutes_end = int(end_time // 60)
            seconds_end = int(end_time % 60)
            duration = end_time - start_time
            minutes_duration = int(duration // 60)
            seconds_duration = int(duration % 60)

            print(
                f"YouTube ID: {youtube_id}, Start: {minutes_start}:{seconds_start:02d}, End: {minutes_end}:{seconds_end:02d}, Duration: {minutes_duration}:{seconds_duration:02d} (Title: {title})")

        # Save to CSV
        df = pd.DataFrame(segments, columns=["YouTube ID", "Start (s)", "End (s)", "Title"])
        # Add duration column
        df["Duration (s)"] = df["End (s)"] - df["Start (s)"]
        # Convert seconds to MM:SS format for readability
        df["Start"] = df["Start (s)"].apply(lambda x: f"{int(x // 60)}:{int(x % 60):02d}")
        df["End"] = df["End (s)"].apply(lambda x: f"{int(x // 60)}:{int(x % 60):02d}")
        df["Duration"] = df["Duration (s)"].apply(lambda x: f"{int(x // 60)}:{int(x % 60):02d}")

        df.to_csv("segments.csv", index=False)
        print(f"\nSaved results to segments.csv")

        # Extract segment clips
        extract_segment_clips(segments)

        # Cleanup temporary files if needed
        # cleanup_directories()
    else:
        print("No YouTube segments detected in the video.")
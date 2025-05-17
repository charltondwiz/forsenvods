#!/usr/bin/env bash
# Twitch VOD + Chat Downloader/Renderer for Windows Git Bash
# Usage: ./twitch_downloader.sh VOD_ID [output_filename]

set -euo pipefail
IFS=$'\n\t'

# ———————— Config & cleanup ————————
VOD_ID="${1:-}"
OUTPUT_FILE="${2:-chat_with_video.mp4}"
VIDEO_FILE="forsen2.mp4"
CHAT_JSON="chat.json"
CHAT_VIDEO="chat.mp4"

if [[ -z "$VOD_ID" ]]; then
  echo "Error: VOD ID required"
  echo "Usage: $0 VOD_ID [output_filename]"
  exit 1
fi

rm -f *.mp4 "$CHAT_JSON" 2>/dev/null

echo "=========================================="
echo "  Twitch VOD Downloader - VOD ID: $VOD_ID"
echo "=========================================="

# ———————— Step 1: Download VOD with retry ————————
echo "Downloading VOD..."
for attempt in $(seq 1 100); do
  echo "  attempt $attempt/100…"
  if twitch-dl download -q source "$VOD_ID" -o "$VIDEO_FILE" -c; then
    echo "✔ VOD saved to $VIDEO_FILE"
    break
  else
    echo "✖ Download failed, retrying in 5s…"
    sleep 5
  fi
done

if [[ ! -s "$VIDEO_FILE" ]]; then
  echo "Error: VOD download never succeeded."
  exit 1
fi

# ———————— Step 2: Get duration ————————
VOD_DURATION_INT=$(ffprobe -v error \
  -show_entries format=duration \
  -of csv=p=0 "$VIDEO_FILE" \
  | cut -d. -f1)

echo "VOD duration: ${VOD_DURATION_INT}s"

# ———————— Step 3: Download + render chat ————————
echo "Downloading chat history…"
if ! ./TwitchDownloaderCLI.exe chatdownload \
     --id "$VOD_ID" \
     -o "$CHAT_JSON" -E -e "${VOD_DURATION_INT}s"
then
  echo "Error: chatdownload failed"
  exit 1
fi

echo "Rendering chat to video…"
if ! ./TwitchDownloaderCLI.exe chatrender \
     -i "$CHAT_JSON" \
     -h 1080 -w 422 --framerate 30 --font-size 18 --update-rate 0.2 \
     -e "${VOD_DURATION_INT}s" -o "$CHAT_VIDEO"
then
  echo "Error: chatrender failed"
  exit 1
fi

# ———————— Step 4: Combine them side-by-side ————————
echo "Combining video + chat…"
if ! ffmpeg -y \
    -i "$VIDEO_FILE" -i "$CHAT_VIDEO" \
    -filter_complex "[0:v]scale=-2:1080:flags=lanczos[v0];[1:v]scale=-2:1080:flags=lanczos[v1];[v0][v1]hstack=2[out]" \
    -map "[out]" -map "0:a?" \
    -c:v libx264 -preset veryfast -crf 23 \
    -c:a aac -r 30 -shortest \
    "$OUTPUT_FILE"
then
  echo "Error: ffmpeg combine failed"
  exit 1
fi

echo "✔ Done! Output → $OUTPUT_FILE"

# ———————— Optional cleanup & post-hooks ————————
rm -rf frames segments post_processed titles post_processed_titles
[[ -f ocr_cache.json ]] && rm ocr_cache.json

[[ -f main.py ]]     && python main.py
[[ -f uploader.py ]] && python uploader.py

echo "=========================================="
echo "All finished."
echo "=========================================="

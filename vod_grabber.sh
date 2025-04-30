#!/bin/bash
# Twitch VOD Downloader and Processor
# Usage: ./twitch_downloader.sh VOD_ID [output_filename]
set -e  # Exit on error

# Clean up any existing files
rm -f *.mp4 chat.json

# Check if VOD ID is provided
if [ -z "$1" ]; then
  echo "Error: VOD ID is required"
  echo "Usage: ./twitch_downloader.sh VOD_ID [output_filename]"
  exit 1
fi

VOD_ID=$1
OUTPUT_FILE=${2:-"chat_with_video.mp4"}
VIDEO_FILE="forsen2.mp4"
CHAT_FILE="chat.mp4"

echo "=========================================="
echo "  Twitch VOD Downloader - VOD ID: $VOD_ID"
echo "=========================================="

# Step 1: Download VOD with reliable approach
echo "Downloading VOD..."

# Create a simple loop for twitch-dl with basic error handling
for attempt in {1..100}; do
    echo "Download attempt $attempt of 100..."
    
    # Run twitch-dl with a Bash-based timeout implementation (no external timeout command needed)
    twitch-dl download -q source $VOD_ID -o "$VIDEO_FILE" -c 1 &
    download_pid=$!
    
    # Monitor the process for 300 seconds (5 minutes)
    timeout_counter=0
    while kill -0 $download_pid 2>/dev/null && [ $timeout_counter -lt 300 ]; do
        sleep 1
        ((timeout_counter++))
    done
    
    # Check if process is still running after timeout period
    if kill -0 $download_pid 2>/dev/null; then
        echo "Download timed out after 300 seconds, killing process"
        kill $download_pid 2>/dev/null || kill -9 $download_pid 2>/dev/null
    else
        # Wait for process to fully complete
        wait $download_pid 2>/dev/null
    fi
    
    # Check if download succeeded
    if [ -f "$VIDEO_FILE" ] && [ $(du -k "$VIDEO_FILE" | cut -f1) -gt 10000 ]; then
        echo "Successfully downloaded VOD after $attempt attempts!"
        break
    fi
    
    echo "Attempt $attempt failed. Waiting 5 seconds before retry..."
    sleep 5
done

# If twitch-dl failed completely, try streamlink
if [ ! -f "$VIDEO_FILE" ] || [ $(du -k "$VIDEO_FILE" | cut -f1) -lt 10000 ]; then
    echo "twitch-dl failed after 100 attempts. Trying streamlink..."
    
    # Check if streamlink is installed and install if needed
    if ! command -v streamlink &> /dev/null; then
        echo "Installing streamlink..."
        pip install streamlink
    fi
    
    # Try streamlink with multiple quality options
    for quality in "best" "1080p60" "1080p" "720p60" "720p"; do
        echo "Trying streamlink with quality: $quality"
        # Run streamlink with Bash-based timeout
        streamlink --force --hls-live-restart --retry-streams 5 --retry-max 10 "https://www.twitch.tv/videos/$VOD_ID" "$quality" -o "$VIDEO_FILE" &
        streamlink_pid=$!
        
        # Monitor the process for 600 seconds (10 minutes)
        timeout_counter=0
        while kill -0 $streamlink_pid 2>/dev/null && [ $timeout_counter -lt 600 ]; do
            sleep 1
            ((timeout_counter++))
        done
        
        # Check if process is still running after timeout period
        if kill -0 $streamlink_pid 2>/dev/null; then
            echo "Streamlink download timed out after 600 seconds, killing process"
            kill $streamlink_pid 2>/dev/null || kill -9 $streamlink_pid 2>/dev/null
        else
            # Wait for process to fully complete
            wait $streamlink_pid 2>/dev/null
        fi
        
        # Check if download succeeded
        if [ -f "$VIDEO_FILE" ] && [ $(du -k "$VIDEO_FILE" | cut -f1) -gt 10000 ]; then
            echo "Successfully downloaded VOD using streamlink!"
            break
        fi
    done
fi

# Final fallback: YouTube-DL
if [ ! -f "$VIDEO_FILE" ] || [ $(du -k "$VIDEO_FILE" | cut -f1) -lt 10000 ]; then
    echo "All previous methods failed. Trying youtube-dl as last resort..."
    
    # Check if youtube-dl is installed and install if needed
    if ! command -v youtube-dl &> /dev/null && ! command -v yt-dlp &> /dev/null; then
        echo "Installing yt-dlp (modern youtube-dl)..."
        pip install yt-dlp
    fi
    
    # Try with youtube-dl/yt-dlp with timeout
    if command -v yt-dlp &> /dev/null; then
        yt-dlp -f best "https://www.twitch.tv/videos/$VOD_ID" -o "$VIDEO_FILE" &
        dl_pid=$!
    else 
        youtube-dl -f best "https://www.twitch.tv/videos/$VOD_ID" -o "$VIDEO_FILE" &
        dl_pid=$!
    fi
    
    # Monitor the process for 600 seconds (10 minutes)
    timeout_counter=0
    while kill -0 $dl_pid 2>/dev/null && [ $timeout_counter -lt 600 ]; do
        sleep 1
        ((timeout_counter++))
    done
    
    # Check if process is still running after timeout period
    if kill -0 $dl_pid 2>/dev/null; then
        echo "Download timed out after 600 seconds, killing process"
        kill $dl_pid 2>/dev/null || kill -9 $dl_pid 2>/dev/null
    else
        # Wait for process to fully complete
        wait $dl_pid 2>/dev/null
    fi
fi

# Verify we have a valid file
if [ ! -f "$VIDEO_FILE" ] || [ ! -s "$VIDEO_FILE" ]; then
    echo "All download methods failed. Please try a different VOD ID or check your connection."
    exit 1
fi

echo "VOD download completed successfully!"

# Get VOD duration in seconds
VOD_DURATION=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$VIDEO_FILE")
VOD_DURATION_INT=$(printf "%.0f" "$VOD_DURATION")
echo "VOD duration: $VOD_DURATION_INT seconds"

# Step 2: Download and render chat with VOD duration limit
echo "Downloading and rendering chat..."

# Download chat with duration limit
echo "Downloading chat with duration limit..."
./TwitchDownloaderCLI chatdownload --id $VOD_ID -o chat.json -E -e "${VOD_DURATION_INT}s"

# Fix JSON if needed due to truncation
echo "Checking and fixing chat JSON if needed..."
python3 -c '
import json, sys
try:
    with open("chat.json", "r") as f:
        data = json.load(f)
    print("Chat JSON is valid")
except json.JSONDecodeError as e:
    print(f"JSON decode error: {e}")
    try:
        with open("chat.json", "r") as f:
            content = f.read()
        
        # Find the last complete message
        last_obj_end = content.rfind("},")
        if last_obj_end > 0:
            print(f"Found last complete object at position {last_obj_end}")
            # Cut at the last complete message and properly close the JSON structure
            fixed_content = content[:last_obj_end+1] + "\n  ]\n}"
            
            # Test if our fix worked
            json.loads(fixed_content)
            print("Successfully repaired truncated JSON!")
            
            # Write the fixed content
            with open("chat.json", "w") as f:
                f.write(fixed_content)
        else:
            print("Could not find pattern to repair truncated JSON")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
'

# Render chat with duration limit and performance optimizations
echo "Rendering chat with duration limit..."
./TwitchDownloaderCLI chatrender -i chat.json \
  -h 1080 -w 422 --framerate 30 --font-size 18 --update-rate 0.2 \
  -e "${VOD_DURATION_INT}s" -o chat.mp4

if [ $? -ne 0 ]; then
  echo "Error: Failed to download or render chat"
  exit 1
fi
echo "Chat download and render complete!"

# Step 3: Combine video and chat with improved options
echo "Combining video and chat..."

# Try preferred hardware accelerated method first
ffmpeg -hwaccel videotoolbox -i "$VIDEO_FILE" -i "$CHAT_FILE" \
-filter_complex "[0:v]scale=-2:1080:flags=lanczos[v0];[1:v]scale=-2:1080:flags=lanczos[v1];[v0][v1]hstack=inputs=2[out]" \
-map "[out]" -map "0:a?" -c:v h264_videotoolbox -c:a aac -r 30 -shortest "$OUTPUT_FILE"

# If the first attempt fails, try a CPU-based fallback method
if [ $? -ne 0 ]; then
  echo "Hardware acceleration failed, trying CPU fallback..."
  ffmpeg -i "$VIDEO_FILE" -i "$CHAT_FILE" \
  -filter_complex "[0:v][1:v]hstack=inputs=2[out]" \
  -map "[out]" -map "0:a?" -c:v libx264 -preset veryfast -crf 28 -c:a aac -r 30 -shortest "$OUTPUT_FILE"
  
  if [ $? -ne 0 ]; then
    echo "Error: Failed to combine video and chat"
    exit 1
  fi
fi

echo "Video processing complete!"
echo "=========================================="
echo "All done! Output file: $OUTPUT_FILE"
echo "=========================================="

# Clean up temporary files but keep the main outputs
echo "Cleaning up temporary files..."
rm -rf frames segments post_processed titles post_processed_titles
[ -f ocr_cache.json ] && rm ocr_cache.json

# Run post-processing scripts if they exist
if [ -f main.py ]; then
  echo "Running post-processing script main.py..."
  python main.py
fi

if [ -f uploader.py ]; then
  echo "Running uploader script..."
  python uploader.py
fi

echo "Processing complete! Find your output at: $OUTPUT_FILE"
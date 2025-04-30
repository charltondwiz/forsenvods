#!/bin/bash
# Final Modal VOD Processor Script
# Usage: ./final_modal_vod.sh VOD_ID

rm chat_with_video.mp4

# Check if VOD ID is provided
if [ -z "$1" ]; then
  echo "Note: No VOD ID provided"
  echo "Usage: ./final_modal_vod.sh VOD_ID"
  echo "Getting latest VOD from forsen channel..."
  VOD_ID=$(twitch-dl videos forsen --limit 1 | grep "Video" | head -1 | awk '{print $2}')
  echo "Using latest VOD ID: $VOD_ID"
else
  VOD_ID=$1
fi

echo "=========================================="
echo "  Modal Twitch VOD Processor - VOD ID: $VOD_ID"
echo "=========================================="

# First verify VOD exists and is accessible
echo "Verifying VOD ID with twitch-dl..."
if ! twitch-dl videos forsen --limit 10 | grep -q "Video $VOD_ID"; then
  echo "Warning: VOD $VOD_ID not found in latest 10 VODs"
  echo "Trying direct VOD check..."
  if ! twitch-dl info $VOD_ID; then
    echo "Error: VOD $VOD_ID could not be verified"
    echo "Proceeding anyway, Modal will attempt to download it"
  else
    echo "VOD $VOD_ID found and accessible"
  fi
else
  echo "VOD $VOD_ID found in recent VODs"
fi

# Clean up old files
echo "Cleaning up old files..."
rm -f chat_with_video.mp4 chat.json vod_*.mp4
rm -rf frames segments post_processed titles post_processed_titles ocr_cache.json

# Create directory for output
mkdir -p output

# Deploy the Modal processor with better output
echo "======================"
echo "Deploying Modal processor..."
echo "======================"
python -m modal deploy modal_processor.py

# Run the client with timing
echo "======================"
echo "Starting Modal GPU processing for VOD $VOD_ID..."
echo "Processing may take 30-60 minutes depending on VOD length"
echo "======================"
start_time=$(date +%s)
echo "Started at: $(date)"

# Run with progress output
python modal_client.py $VOD_ID

# Check if processing failed but we can try downloading directly
if [ $? -ne 0 ]; then
    echo "======================"
    echo "Modal processing failed or returned error code."
    echo "Attempting direct download from Modal volume..."
    echo "======================"
    
    # Try direct download
    python modal_client.py --download-only $VOD_ID
    
    # Check if that worked
    if [ $? -ne 0 ]; then
        echo "Direct download also failed!"
    fi
fi

# Print timing information
end_time=$(date +%s)
duration=$((end_time - start_time))
duration_min=$((duration / 60))
duration_sec=$((duration % 60))
echo "======================"
echo "Processing completed in ${duration_min}m ${duration_sec}s"
echo "Finished at: $(date)"
echo "======================"

# Check if the processing was successful
if [ $? -eq 0 ]; then
  # Get filesize and verify it exists
  if [ -f chat_with_video.mp4 ]; then
    filesize=$(du -h chat_with_video.mp4 | cut -f1)
    echo "=========================================="
    echo "Success! Output file: chat_with_video.mp4 (Size: $filesize)"
    echo "Processing of VOD $VOD_ID is complete"
    echo "=========================================="

    # Continue with segment extraction and upload
    echo "Running segment extraction..."
    python main.py
    echo "Uploading segments to YouTube..."
    python uploader.py
  else
    echo "=========================================="
    echo "ERROR: Processing seemed successful but output file not found!"
    echo "=========================================="
    exit 1
  fi
else
  echo "Error: Modal processing failed"
  
  echo "Attempting local fallback processing..."
  echo "Downloading VOD with twitch-dl..."
  
  # Retry function for twitch-dl to handle GraphQL errors with progress monitoring
  function retry_download {
    local MAX_ATTEMPTS=100
    local DELAY=1
    local TIMEOUT=7200  # 2 hours max for download
    local quality=$1
    
    for ((attempt=1; attempt<=MAX_ATTEMPTS; attempt++)); do
      echo "Trying to download with quality: $quality (Attempt $attempt/$MAX_ATTEMPTS)"
      
      # Start download in background with progress redirection
      twitch-dl download -q $quality $VOD_ID -o forsen2.mp4 --chapter 1 --overwrite > download.log 2>&1 &
      download_pid=$!
      
      # Initialize timestamps
      start_time=$(date +%s)
      last_update_time=$start_time
      last_log_check=$start_time
      
      # Monitor the download process
      while kill -0 $download_pid 2>/dev/null; do
        current_time=$(date +%s)
        elapsed=$((current_time - start_time))
        
        # Check if we've exceeded the timeout
        if [ $elapsed -gt $TIMEOUT ]; then
          echo "Download timed out after ${TIMEOUT}s, killing process..."
          kill -9 $download_pid 2>/dev/null
          break
        fi
        
        # Print progress update every 30 seconds
        if [ $((current_time - last_update_time)) -gt 30 ]; then
          echo "Download in progress... (running for ${elapsed}s)"
          last_update_time=$current_time
          
          # If file exists, show its size
          if [ -f forsen2.mp4 ]; then
            filesize=$(du -h forsen2.mp4 | cut -f1)
            echo "Current file size: $filesize"
          fi
        fi
        
        # Check log file for updates every 5 seconds
        if [ $((current_time - last_log_check)) -gt 5 ]; then
          # Show the last few lines of the log if it has changed
          if [ -f download.log ]; then
            tail -5 download.log
          fi
          last_log_check=$current_time
        fi
        
        # Brief sleep to avoid CPU spinning
        sleep 1
      done
      
      # Check exit status of download
      wait $download_pid
      exit_status=$?
      
      if [ $exit_status -eq 0 ]; then
        echo "VOD downloaded successfully with quality $quality"
        return 0
      fi
      
      # Check if GraphQL error
      if grep -q "GraphQL query failed" download.log; then
        echo "GraphQL service error detected, retrying in ${DELAY}s..."
        sleep $DELAY
        continue
      fi
      
      # Check if quality not available
      if grep -q "doesn't have quality option" download.log; then
        echo "Quality $quality not available for this VOD"
        return 1
      fi
      
      echo "Download failed with quality $quality (Attempt $attempt, exit code: $exit_status)"
      cat download.log
      echo "Retrying in ${DELAY}s..."
      sleep $DELAY
    done
    
    return 1
  }
  
  # Try different qualities
  for quality in "1080p60" "1080p" "720p60" "720p" "best"; do
    echo "Attempting download with quality: $quality"
    if retry_download $quality; then
      break
    fi
    echo "Moving to next quality option..."
  done
  
  echo "Downloading chat..."
  # Remove existing chat file to avoid prompts
  rm -f chat.json
  ./TwitchDownloaderCLI chatdownload --id $VOD_ID -o chat.json -E
  
  echo "Rendering chat..."
  # Remove existing chat video to avoid prompts
  rm -f chat.mp4
  ./TwitchDownloaderCLI chatrender -i chat.json -h 1080 -w 422 --framerate 30 --font-size 18 -o chat.mp4
  
  echo "Combining video and chat..."
  ffmpeg -i forsen2.mp4 -i chat.mp4 \
    -filter_complex "[0:v]scale=-2:1080:flags=lanczos[v0];[1:v]scale=-2:1080:flags=lanczos[v1];[v0][v1]hstack=inputs=2[out]" \
    -map "[out]" -map "0:a?" -c:v h264 -c:a aac -r 30 -shortest chat_with_video.mp4
  
  if [ $? -eq 0 ]; then
    echo "Fallback processing successful."
    
    # Continue with segment extraction and upload
    echo "Running segment extraction..."
    python main.py
    
    echo "Uploading segments to YouTube..."
    python uploader.py
    
    # Get filesize and verify it exists
    if [ -f chat_with_video.mp4 ]; then
      filesize=$(du -h chat_with_video.mp4 | cut -f1)
      echo "=========================================="
      echo "Success! Output file: chat_with_video.mp4 (Size: $filesize)"
      echo "Fallback processing of VOD $VOD_ID is complete"
      echo "=========================================="
    else
      echo "=========================================="
      echo "ERROR: Fallback processing seemed successful but output file not found!"
      echo "=========================================="
      exit 1
    fi
  else
    echo "Fallback processing also failed."
    exit 1
  fi
fi
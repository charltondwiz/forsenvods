#!/bin/bash
# Modal-based Twitch VOD Processor Wrapper
# Usage: ./modal_vod_grabber.sh VOD_ID

# Check if VOD ID is provided
if [ -z "$1" ]; then
  echo "Error: VOD ID is required"
  echo "Usage: ./modal_vod_grabber.sh VOD_ID"
  exit 1
fi

VOD_ID=$1

echo "=========================================="
echo "  Modal Twitch VOD Processor - VOD ID: $VOD_ID"
echo "=========================================="

# First ensure the Modal app is running
MODAL_APP_STATUS=$(ps aux | grep "modal serve modal_app.py" | grep -v grep)

if [ -z "$MODAL_APP_STATUS" ]; then
  echo "Starting Modal app in the background..."
  python -m modal serve modal_app.py &> modal_app.log &
  MODAL_APP_PID=$!
  echo "Modal app started with PID: $MODAL_APP_PID"
  
  # Give it time to start
  echo "Waiting for Modal app to start..."
  sleep 10
fi

# Clean up old files
echo "Cleaning up old files..."
rm -f chat_with_video.mp4 chat.json
rm -rf frames segments post_processed titles post_processed_titles ocr_cache.json

# Run the client
echo "Starting Modal-based VOD processing..."
python modal_client.py $VOD_ID

# Check if the processing was successful
if [ $? -eq 0 ]; then
  echo "=========================================="
  echo "All done! Output file: chat_with_video.mp4"
  echo "=========================================="
else
  echo "Error: Modal VOD processing failed"
  exit 1
fi
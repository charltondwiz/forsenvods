#!/bin/bash
# Improved Modal VOD Processor
# Usage: ./run_modal_vod.sh VOD_ID

# Check if VOD ID is provided
if [ -z "$1" ]; then
  echo "Error: VOD ID is required"
  echo "Usage: ./run_modal_vod.sh VOD_ID"
  exit 1
fi

VOD_ID=$1

echo "=========================================="
echo "  Modal Twitch VOD Processor - VOD ID: $VOD_ID"
echo "=========================================="

# Clean up old files
echo "Cleaning up old files..."
rm -f chat_with_video.mp4 chat.json
rm -rf frames segments post_processed titles post_processed_titles ocr_cache.json

# Run the Modal processor with VOD_ID environment variable
echo "Starting Modal GPU processing..."
VOD_ID=$VOD_ID python modal_vod.py

# Check if the processing was successful
if [ $? -eq 0 ]; then
  echo "=========================================="
  echo "All done! Output file: chat_with_video.mp4"
  echo "=========================================="
else
  echo "Error: Modal processing failed"
  exit 1
fi
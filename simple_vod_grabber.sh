#!/bin/bash
# Simple Local Twitch VOD Processor
# Usage: ./simple_vod_grabber.sh VOD_ID

# Check if VOD ID is provided
if [ -z "$1" ]; then
  echo "Error: VOD ID is required"
  echo "Usage: ./simple_vod_grabber.sh VOD_ID"
  exit 1
fi

VOD_ID=$1

# Make script executable
chmod +x simple_vod_processor.py

# Run the processor
python simple_vod_processor.py $VOD_ID
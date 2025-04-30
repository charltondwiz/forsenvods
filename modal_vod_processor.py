#!/usr/bin/env python3
"""
Modal-based Twitch VOD Processor

This script uses Modal.com's cloud platform to accelerate the rendering
process for Twitch VODs and chat.

Usage:
    python modal_vod_processor.py <vod_id>
"""

import os
import sys
import subprocess
import time
import modal
import shutil
from pathlib import Path

# Constants
VIDEO_FILE = "forsen2.mp4"
CHAT_FILE = "chat.mp4"
CHAT_JSON = "chat.json"
OUTPUT_FILE = "chat_with_video.mp4"

# Create Modal app
app = modal.App("twitch-vod-processor")

# Create a volume to store temporary files
volume = modal.Volume.from_name("forsen-data-vol", create_if_missing=True)

# Create base image with FFmpeg and Python tools
base_image = modal.Image.debian_slim().apt_install(
    "ffmpeg",
    "python3-pip",
    "wget",
    "unzip",
    "git",
    "curl",
)

# Add TwitchDownloaderCLI to the image
gpu_image = base_image.pip_install(
    "twitch-dl",
    "tqdm",
    "google-api-python-client", 
    "oauth2client",
    "pillow",
    "pytesseract"
).run_commands(
    # Download and set up TwitchDownloaderCLI
    "wget https://github.com/lay295/TwitchDownloader/releases/download/1.53.0/TwitchDownloaderCLI-Linux-x64.zip",
    "unzip TwitchDownloaderCLI-Linux-x64.zip -d /usr/local/bin",
    "chmod +x /usr/local/bin/TwitchDownloaderCLI"
)

@app.function(image=gpu_image, volumes={"/data": volume}, timeout=3600)
def download_vod(vod_id, output_file=VIDEO_FILE):
    """Download the Twitch VOD"""
    print(f"\n[+] Downloading VOD (1080p60): {vod_id}")
    
    # Make sure we're writing to the volume
    output_path = f"/data/{output_file}"
    
    # Use twitch-dl to download the VOD
    cmd = f'twitch-dl download -q 1080p60 {vod_id} -o "{output_path}" --chapter 1'
    subprocess.run(cmd, shell=True, check=True)
    
    print(f"[✓] VOD downloaded to {output_path}")
    return output_path

@app.function(image=gpu_image, volumes={"/data": volume}, timeout=1800)
def download_chat(vod_id, output_json=CHAT_JSON):
    """Download the chat data"""
    print(f"\n[+] Downloading chat data for VOD: {vod_id}")
    
    # Make sure we're writing to the volume
    output_path = f"/data/{output_json}"
    
    # Use TwitchDownloaderCLI to download chat
    cmd = f'/usr/local/bin/TwitchDownloaderCLI chatdownload --id {vod_id} -o "{output_path}" -E'
    subprocess.run(cmd, shell=True, check=True)
    
    print(f"[✓] Chat data downloaded to {output_path}")
    return output_path

@app.function(image=gpu_image, gpu="T4", volumes={"/data": volume}, timeout=1800)
def render_chat(chat_json_path, output_file=CHAT_FILE):
    """Render chat JSON to video using GPU acceleration"""
    print(f"\n[+] Rendering chat to video with GPU acceleration")
    
    # Make sure we're writing to the volume
    output_path = f"/data/{output_file}"
    
    # Use TwitchDownloaderCLI to render chat with hardware acceleration
    cmd = f'/usr/local/bin/TwitchDownloaderCLI chatrender -i "{chat_json_path}" -h 1080 -w 422 --framerate 30 --font-size 18 -o "{output_path}"'
    subprocess.run(cmd, shell=True, check=True)
    
    print(f"[✓] Chat rendered to {output_path}")
    return output_path

@app.function(image=gpu_image, gpu="T4", volumes={"/data": volume}, timeout=3600)
def combine_video_and_chat(video_path, chat_path, output_file=OUTPUT_FILE):
    """Combine video and chat into a single video using GPU acceleration"""
    print(f"\n[+] Combining video and chat with GPU acceleration")
    
    # Make sure we're writing to the volume
    output_path = f"/data/{output_file}"
    
    # Use FFmpeg with hardware acceleration to combine the files
    cmd = (
        f'ffmpeg -hwaccel cuda -i "{video_path}" -i "{chat_path}" '
        f'-filter_complex "[0:v]scale=-2:1080:flags=lanczos[v0];[1:v]scale=-2:1080:flags=lanczos[v1];[v0][v1]hstack=inputs=2[out]" '
        f'-map "[out]" -map "0:a?" -c:v h264_nvenc -c:a aac -r 30 -shortest "{output_path}"'
    )
    subprocess.run(cmd, shell=True, check=True)
    
    print(f"[✓] Video and chat combined to {output_path}")
    return output_path

@app.function(image=base_image, volumes={"/data": volume})
def cleanup_and_download_results(remote_output_path, local_output_path=OUTPUT_FILE):
    """Download the final output file to local machine"""
    print(f"\n[+] Downloading final video to local machine")
    
    # Copy the file from volume to function container
    shutil.copy(remote_output_path, local_output_path)
    
    # Return the path, which Modal will automatically download
    return local_output_path

@app.local_entrypoint()
def main(vod_id=None):
    """Main entry point for Modal pipeline"""
    start_time = time.time()
    
    # Get VOD ID from command line argument if not provided
    if vod_id is None:
        if len(sys.argv) < 2:
            print("Error: VOD ID is required")
            print("Usage: python modal_vod_processor.py <vod_id>")
            sys.exit(1)
        vod_id = sys.argv[1]
    
    print(f"\n[+] Processing VOD {vod_id} using Modal with GPU acceleration")
    
    try:
        # Step 1: Download the VOD and chat in parallel
        vod_future = download_vod.spawn(vod_id)
        chat_json_future = download_chat.spawn(vod_id)
        
        # Wait for downloads to complete
        vod_path = vod_future.get()
        chat_json_path = chat_json_future.get()
        
        # Step 2: Render chat to video
        chat_video_path = render_chat.call(chat_json_path)
        
        # Step 3: Combine video and chat
        combined_path = combine_video_and_chat.call(vod_path, chat_video_path)
        
        # Step 4: Download result to local machine
        local_output_path = cleanup_and_download_results.call(combined_path)
        
        # Calculate and display elapsed time
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(int(elapsed_time), 60)
        hours, minutes = divmod(minutes, 60)
        
        print(f"\n[✓] Modal processing completed in {hours:02d}:{minutes:02d}:{seconds:02d}")
        print(f"[✓] Output saved to: {local_output_path}")
        
        # Step 5: Run the segment extraction and upload scripts
        print("\n[+] Extracting segments from the processed video")
        subprocess.run(["python", "main.py"], check=True)
        
        print("\n[+] Uploading segments to YouTube")
        subprocess.run(["python", "uploader.py"], check=True)
        
        print("\n[✓] Pipeline completed successfully!")
        return 0
        
    except Exception as e:
        print(f"\n[✗] Error: {str(e)}")
        return 1

if __name__ == "__main__":
    main()
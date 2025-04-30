#!/usr/bin/env python3
"""
Modal VOD Processor App

This script defines the Modal app and functions for processing Twitch VODs.
Run with: python -m modal serve modal_app.py
Then use the client script to call the functions.
"""

import modal
import os
import subprocess
import time

# Define the app
app = modal.App("twitch-vod-processor")

# Create a volume to store files between functions
volume = modal.Volume.from_name("twitch-vod-vol", create_if_missing=True)

# Define image with dependencies
gpu_image = modal.Image.debian_slim().apt_install(
    "ffmpeg",
    "python3-pip",
    "wget",
    "unzip",
    "git",
    "curl",
).pip_install(
    "twitch-dl",
).run_commands(
    # Download and setup TwitchDownloaderCLI
    "wget https://github.com/lay295/TwitchDownloader/releases/download/1.53.0/TwitchDownloaderCLI-Linux-x64.zip",
    "unzip TwitchDownloaderCLI-Linux-x64.zip -d /usr/local/bin",
    "chmod +x /usr/local/bin/TwitchDownloaderCLI"
)

@app.function(image=gpu_image, volumes={"/data": volume})
def download_vod(vod_id):
    """Download Twitch VOD"""
    print(f"Downloading VOD: {vod_id}")
    
    # Make sure we're writing to the volume
    output_path = "/data/forsen2.mp4"
    
    cmd = f'twitch-dl download -q 1080p60 {vod_id} -o "{output_path}" --chapter 1'
    subprocess.run(cmd, shell=True, check=True)
    
    print(f"VOD downloaded to {output_path}")
    return output_path

@app.function(image=gpu_image, volumes={"/data": volume})
def download_chat(vod_id):
    """Download Twitch chat"""
    print(f"Downloading chat for VOD: {vod_id}")
    
    # Make sure we're writing to the volume
    output_path = "/data/chat.json"
    
    cmd = f'/usr/local/bin/TwitchDownloaderCLI chatdownload --id {vod_id} -o "{output_path}" -E'
    subprocess.run(cmd, shell=True, check=True)
    
    print(f"Chat downloaded to {output_path}")
    return output_path

@app.function(image=gpu_image, gpu="T4", volumes={"/data": volume})
def render_chat(chat_json_path):
    """Render chat JSON to MP4"""
    print(f"Rendering chat from {chat_json_path}")
    
    # Output to the volume
    output_path = "/data/chat.mp4"
    
    cmd = f'/usr/local/bin/TwitchDownloaderCLI chatrender -i "{chat_json_path}" -h 1080 -w 422 --framerate 30 --font-size 18 -o "{output_path}"'
    subprocess.run(cmd, shell=True, check=True)
    
    print(f"Chat rendered to {output_path}")
    return output_path

@app.function(image=gpu_image, gpu="T4", volumes={"/data": volume})
def combine_videos(video_path, chat_path):
    """Combine video and chat"""
    print(f"Combining {video_path} and {chat_path}")
    
    # Output to the volume
    output_path = "/data/chat_with_video.mp4"
    
    # Use FFmpeg with GPU acceleration
    cmd = (
        f'ffmpeg -hwaccel cuda -i "{video_path}" -i "{chat_path}" '
        f'-filter_complex "[0:v]scale=-2:1080:flags=lanczos[v0];[1:v]scale=-2:1080:flags=lanczos[v1];[v0][v1]hstack=inputs=2[out]" '
        f'-map "[out]" -map "0:a?" -c:v h264_nvenc -c:a aac -r 30 -shortest "{output_path}"'
    )
    subprocess.run(cmd, shell=True, check=True)
    
    print(f"Videos combined to {output_path}")
    return output_path

@app.function(image=gpu_image, volumes={"/data": volume})
def get_output_file(file_path="/data/chat_with_video.mp4"):
    """Get the output file from the volume"""
    import shutil
    
    # Create a local copy in the function container
    local_path = "output.mp4"
    shutil.copy(file_path, local_path)
    
    print(f"Copied {file_path} to {local_path}")
    return local_path

@app.function()
def process_vod(vod_id):
    """Process a VOD end-to-end"""
    print(f"Processing VOD {vod_id}")
    
    # Download VOD and chat in parallel
    vod_path_future = download_vod.spawn(vod_id)
    chat_json_future = download_chat.spawn(vod_id)
    
    # Wait for downloads to complete
    vod_path = vod_path_future.get()
    chat_json_path = chat_json_future.get()
    
    # Render chat to video
    chat_mp4_path = render_chat.remote(chat_json_path)
    
    # Combine video and chat
    combined_path = combine_videos.remote(vod_path, chat_mp4_path)
    
    # Get the output file
    output_path = get_output_file.remote()
    
    return output_path
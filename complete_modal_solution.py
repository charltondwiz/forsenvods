#!/usr/bin/env python3
"""
Complete Modal VOD Processing Solution

This script handles the entire Twitch VOD processing workflow using Modal's
cloud platform and GPU acceleration. 

Usage:
    VOD_ID=1234567890 python -m modal run complete_modal_solution.py
"""

import modal
import os
import sys
import subprocess
import time

# Get VOD ID from environment variable locally
VOD_ID = os.environ.get("VOD_ID")
if not VOD_ID:
    print("Error: VOD_ID environment variable is required")
    print("Usage: VOD_ID=1234567890 python -m modal run complete_modal_solution.py")
    sys.exit(1)

# Define Modal app
app = modal.App("twitch-vod-processor")

# Create a volume for data
volume = modal.Volume.from_name("twitch-vod-vol", create_if_missing=True)

# Use a pre-built FFmpeg image that already has GPU support
base_image = (
    modal.Image.debian_slim()
    .apt_install(
        "ffmpeg",
        "python3-pip",
        "unzip",
        "wget",
        "curl",
        "ca-certificates",
    )
    .pip_install("twitch-dl==2.1.0")
)

# For downloading TwitchDownloaderCLI
@app.function(image=base_image, volumes={"/data": volume})
def setup_downloader():
    """Download and setup TwitchDownloaderCLI"""
    import os
    import subprocess
    
    # Create directory if it doesn't exist
    os.makedirs("/data/bin", exist_ok=True)
    
    # Latest release URL
    url = "https://github.com/lay295/TwitchDownloader/releases/download/1.55.5/TwitchDownloaderCLI-1.55.5-Linux-x64.zip"
    
    # Download and extract
    print(f"Downloading TwitchDownloaderCLI from {url}")
    
    try:
        # Download with curl to avoid wget issues
        subprocess.run(
            ["curl", "-L", "-o", "/data/twitch-dl.zip", url],
            check=True
        )
        
        # Unzip to bin directory
        subprocess.run(
            ["unzip", "-o", "/data/twitch-dl.zip", "-d", "/data/bin"],
            check=True
        )
        
        # Make executable
        subprocess.run(
            ["chmod", "+x", "/data/bin/TwitchDownloaderCLI"],
            check=True
        )
        
        print("TwitchDownloaderCLI setup completed")
        return "/data/bin/TwitchDownloaderCLI"
    except Exception as e:
        print(f"Error setting up TwitchDownloaderCLI: {e}")
        raise

@app.function(image=base_image, volumes={"/data": volume})
def download_vod(vod_id):
    """Download Twitch VOD"""
    print(f"Downloading VOD: {vod_id}")
    output_path = "/data/forsen2.mp4"
    
    subprocess.run([
        "twitch-dl", "download", 
        "-q", "1080p60", 
        vod_id, 
        "-o", output_path,
        "--chapter", "1"
    ], check=True)
    
    print(f"VOD downloaded to {output_path}")
    return output_path

@app.function(image=base_image, volumes={"/data": volume})
def download_chat(vod_id, downloader_path="/data/bin/TwitchDownloaderCLI"):
    """Download Twitch chat"""
    print(f"Downloading chat for VOD: {vod_id}")
    output_path = "/data/chat.json"
    
    # First make sure TwitchDownloaderCLI is available
    if not os.path.exists(downloader_path):
        print(f"TwitchDownloaderCLI not found at {downloader_path}, setting up...")
        downloader_path = setup_downloader.remote()
    
    # Download chat
    subprocess.run([
        downloader_path, "chatdownload",
        "--id", vod_id,
        "-o", output_path,
        "-E"
    ], check=True)
    
    print(f"Chat downloaded to {output_path}")
    return output_path

@app.function(image=base_image, gpu="T4", volumes={"/data": volume})
def render_chat(downloader_path="/data/bin/TwitchDownloaderCLI"):
    """Render chat JSON to MP4"""
    print("Rendering chat to video with GPU acceleration")
    chat_json_path = "/data/chat.json"
    output_path = "/data/chat.mp4"
    
    # First make sure TwitchDownloaderCLI is available
    if not os.path.exists(downloader_path):
        print(f"TwitchDownloaderCLI not found at {downloader_path}, setting up...")
        downloader_path = setup_downloader.remote()
    
    # Render chat to video
    subprocess.run([
        downloader_path, "chatrender",
        "-i", chat_json_path,
        "-h", "1080",
        "-w", "422",
        "--framerate", "30",
        "--font-size", "18",
        "-o", output_path
    ], check=True)
    
    print(f"Chat rendered to {output_path}")
    return output_path

@app.function(image=base_image, gpu="T4", volumes={"/data": volume})
def combine_videos():
    """Combine video and chat using GPU acceleration"""
    print("Combining video and chat with GPU acceleration")
    video_path = "/data/forsen2.mp4"
    chat_path = "/data/chat.mp4"
    output_path = "/data/chat_with_video.mp4"
    
    # Try CPU-based processing first
    cmd = (
        f'ffmpeg -i "{video_path}" -i "{chat_path}" '
        f'-filter_complex "[0:v]scale=-2:1080:flags=lanczos[v0];[1:v]scale=-2:1080:flags=lanczos[v1];[v0][v1]hstack=inputs=2[out]" '
        f'-map "[out]" -map "0:a?" -c:v h264 -c:a aac -r 30 -shortest "{output_path}"'
    )
    
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError:
        # If CPU approach fails, try with GPU
        print("CPU-based processing failed, trying with GPU acceleration...")
        cmd = (
            f'ffmpeg -hwaccel cuda -i "{video_path}" -i "{chat_path}" '
            f'-filter_complex "[0:v]scale=-2:1080:flags=lanczos[v0];[1:v]scale=-2:1080:flags=lanczos[v1];[v0][v1]hstack=inputs=2[out]" '
            f'-map "[out]" -map "0:a?" -c:v h264_nvenc -c:a aac -r 30 -shortest "{output_path}"'
        )
        subprocess.run(cmd, shell=True, check=True)
    
    print(f"Videos combined to {output_path}")
    return output_path

@app.function(image=base_image, volumes={"/data": volume})
def get_result():
    """Return the combined video file"""
    import shutil
    
    src_path = "/data/chat_with_video.mp4"
    dest_path = "result.mp4"
    
    # Copy the file from volume to container
    shutil.copy(src_path, dest_path)
    
    # Modal will automatically download this file
    return dest_path

@app.local_entrypoint()
def main():
    """Main entry point for the Modal application"""
    print(f"Processing VOD {VOD_ID} with Modal GPU acceleration")
    start_time = time.time()
    
    try:
        # Step 0: Setup TwitchDownloaderCLI
        print("Step 0: Setting up TwitchDownloaderCLI...")
        downloader_path = setup_downloader.remote()
        
        # Step 1: Download VOD and chat in parallel
        print("Step 1: Downloading VOD and chat...")
        vod_future = download_vod.spawn(VOD_ID)
        chat_future = download_chat.spawn(VOD_ID, downloader_path) 
        
        # Wait for downloads to complete
        vod_path = vod_future.get()
        chat_path = chat_future.get()
        print(f"Downloads complete: {vod_path}, {chat_path}")
        
        # Step 2: Render chat with GPU
        print("Step 2: Rendering chat with GPU...")
        render_chat.remote(downloader_path)
        
        # Step 3: Combine videos with GPU
        print("Step 3: Combining videos with GPU...")
        combine_videos.remote()
        
        # Step 4: Get the result
        print("Step 4: Downloading result...")
        result_path = get_result.remote()
        
        # Copy to expected output location
        import shutil
        shutil.copy(result_path, "chat_with_video.mp4")
        
        # Calculate elapsed time
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(int(elapsed_time), 60)
        hours, minutes = divmod(minutes, 60)
        
        print(f"Modal processing completed in {hours:02d}:{minutes:02d}:{seconds:02d}")
        print(f"Output saved to: chat_with_video.mp4")
        
        # Continue with segment extraction and upload
        print("Running segment extraction...")
        subprocess.run(["python", "main.py"], check=True)
        
        print("Uploading segments to YouTube...")
        subprocess.run(["python", "uploader.py"], check=True)
        
        print("Pipeline completed successfully!")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return 1
        
    return 0
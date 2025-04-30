#!/usr/bin/env python3
"""
Modal VOD Processor 

This script processes Twitch VODs using Modal for GPU acceleration.

Usage:
    VOD_ID=1234567890 python modal_vod.py  # Run locally
    python -m modal run modal_vod.py  # Deploy to Modal cloud
"""
import modal
import os
import sys
import subprocess
import time
import json

# Define app
app = modal.App("twitch-vod-processor")

# Create volume for data
volume = modal.Volume.from_name("twitch-volume", create_if_missing=True)

# Define image with all dependencies
image = (
    modal.Image.debian_slim()
    .apt_install(
        "ffmpeg",
        "python3-pip",
        "unzip", 
        "curl",
        "ca-certificates",
    )
    .pip_install("twitch-dl")
)

# For persisting configuration between functions
@app.function(image=image, volumes={"/data": volume})
def save_config(config):
    """Save configuration to volume"""
    print(f"Saving configuration: {config}")
    with open("/data/config.json", "w") as f:
        json.dump(config, f)
    return "/data/config.json"

@app.function(image=image, volumes={"/data": volume})
def get_config():
    """Get configuration from volume"""
    try:
        with open("/data/config.json", "r") as f:
            config = json.load(f)
        print(f"Loaded configuration: {config}")
        return config
    except FileNotFoundError:
        print("No configuration found")
        return {}

@app.function(image=image, volumes={"/data": volume})
def download_downloader():
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

@app.function(image=image, volumes={"/data": volume})
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

@app.function(image=image, volumes={"/data": volume})
def download_chat(vod_id, downloader_path="/data/bin/TwitchDownloaderCLI"):
    """Download Twitch chat"""
    print(f"Downloading chat for VOD: {vod_id}")
    output_path = "/data/chat.json"
    
    # First make sure TwitchDownloaderCLI is available
    if not os.path.exists(downloader_path):
        print(f"TwitchDownloaderCLI not found at {downloader_path}, setting up...")
        downloader_path = download_downloader.remote()
    
    # Download chat
    subprocess.run([
        downloader_path, "chatdownload",
        "--id", vod_id,
        "-o", output_path,
        "-E"
    ], check=True)
    
    print(f"Chat downloaded to {output_path}")
    return output_path

@app.function(image=image, gpu="T4", volumes={"/data": volume})
def render_chat(downloader_path="/data/bin/TwitchDownloaderCLI"):
    """Render chat JSON to MP4"""
    print("Rendering chat to video with GPU acceleration")
    chat_json_path = "/data/chat.json"
    output_path = "/data/chat.mp4"
    
    # First make sure TwitchDownloaderCLI is available
    if not os.path.exists(downloader_path):
        print(f"TwitchDownloaderCLI not found at {downloader_path}, setting up...")
        downloader_path = download_downloader.remote()
    
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

@app.function(image=image, gpu="T4", volumes={"/data": volume})
def combine_videos():
    """Combine video and chat with GPU acceleration"""
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

@app.function(image=image, volumes={"/data": volume})
def get_result():
    """Return the combined video file"""
    import shutil
    
    src_path = "/data/chat_with_video.mp4"
    dest_path = "result.mp4"
    
    # Copy the file from volume to container
    shutil.copy(src_path, dest_path)
    
    # Modal will automatically download this file
    return dest_path

@app.function()
def process_complete_job():
    """Process a complete VOD job"""
    # Get configuration with VOD ID
    config = get_config.remote()
    
    if "vod_id" not in config:
        raise ValueError("No VOD ID found in configuration. Run setup_job first.")
    
    vod_id = config["vod_id"]
    print(f"Processing VOD {vod_id}")
    
    # Step 1: Setup downloader
    downloader_path = download_downloader.remote()
    
    # Step 2: Download VOD and chat in parallel
    vod_future = download_vod.spawn(vod_id)
    chat_future = download_chat.spawn(vod_id, downloader_path)
    
    vod_path = vod_future.get()
    chat_path = chat_future.get()
    
    # Step 3: Render chat
    render_chat.remote(downloader_path)
    
    # Step 4: Combine videos
    combine_videos.remote()
    
    # Step 5: Get result
    result_path = get_result.remote()
    
    return result_path

# For handling command-line arguments
def run_locally():
    """Run the pipeline locally"""
    # Check for VOD ID in environment variable
    vod_id = os.environ.get("VOD_ID")
    if not vod_id:
        print("Error: VOD_ID environment variable is required")
        print("Usage: VOD_ID=1234567890 python modal_vod.py")
        return 1
    
    print(f"Processing VOD {vod_id}")
    start_time = time.time()
    
    try:
        # Save VOD ID to configuration
        save_config.remote({"vod_id": vod_id})
        
        # Process the job
        result_path = process_complete_job.remote()
        
        # Save locally
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

@app.local_entrypoint()
def main():
    """Entry point for Modal run"""
    return run_locally()

if __name__ == "__main__":
    sys.exit(run_locally())
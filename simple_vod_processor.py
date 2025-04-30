#!/usr/bin/env python3
"""
Simple Twitch VOD Processor

This script downloads a Twitch VOD, processes it, and uploads segments to YouTube.
All processing is done locally without Modal dependencies.
"""

import os
import sys
import subprocess
import time
import shutil
from pathlib import Path

# Constants
VIDEO_FILE = "forsen2.mp4"
CHAT_FILE = "chat.mp4"
CHAT_JSON = "chat.json"
OUTPUT_FILE = "chat_with_video.mp4"

def setup_downloader():
    """Download and setup TwitchDownloaderCLI if needed"""
    bin_dir = Path("./bin")
    bin_dir.mkdir(exist_ok=True)
    downloader_path = bin_dir / "TwitchDownloaderCLI"
    
    # If already exists, return it
    if downloader_path.exists():
        print(f"Using existing TwitchDownloaderCLI at {downloader_path}")
        return str(downloader_path)
    
    # Download the latest version
    print("Downloading TwitchDownloaderCLI...")
    zip_path = bin_dir / "twitch-dl.zip"
    url = "https://github.com/lay295/TwitchDownloader/releases/download/1.55.5/TwitchDownloaderCLI-1.55.5-Linux-x64.zip"
    
    # Use curl to download
    subprocess.run(["curl", "-L", "-o", str(zip_path), url], check=True)
    
    # Unzip
    subprocess.run(["unzip", "-o", str(zip_path), "-d", str(bin_dir)], check=True)
    
    # Make executable
    subprocess.run(["chmod", "+x", str(downloader_path)], check=True)
    
    print(f"TwitchDownloaderCLI setup at {downloader_path}")
    return str(downloader_path)

def download_vod(vod_id):
    """Download Twitch VOD"""
    print(f"\n[+] Downloading VOD (1080p60): {vod_id}")
    
    cmd = [
        "twitch-dl", "download", 
        "-q", "1080p60", 
        vod_id, 
        "-o", VIDEO_FILE,
        "--chapter", "1"
    ]
    
    # Run with progress updates
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )
    
    # Print output in real-time
    for line in process.stdout:
        print(f"  {line.strip()}")
    
    # Wait for process to complete
    process.wait()
    
    if process.returncode != 0:
        print(f"[✗] Failed to download VOD")
        return False
    
    print(f"[✓] VOD downloaded to {VIDEO_FILE}")
    return True

def download_chat(vod_id, downloader_path):
    """Download Twitch chat"""
    print(f"\n[+] Downloading chat for VOD: {vod_id}")
    
    cmd = [
        downloader_path, "chatdownload",
        "--id", vod_id,
        "-o", CHAT_JSON,
        "-E"
    ]
    
    # Run with progress updates
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )
    
    # Print output in real-time
    for line in process.stdout:
        print(f"  {line.strip()}")
    
    # Wait for process to complete
    process.wait()
    
    if process.returncode != 0:
        print(f"[✗] Failed to download chat")
        return False
    
    print(f"[✓] Chat downloaded to {CHAT_JSON}")
    return True

def render_chat(downloader_path):
    """Render chat JSON to MP4"""
    print(f"\n[+] Rendering chat to video")
    
    cmd = [
        downloader_path, "chatrender",
        "-i", CHAT_JSON,
        "-h", "1080",
        "-w", "422",
        "--framerate", "30",
        "--font-size", "18",
        "-o", CHAT_FILE
    ]
    
    # Run with progress updates
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )
    
    # Print output in real-time
    for line in process.stdout:
        print(f"  {line.strip()}")
    
    # Wait for process to complete
    process.wait()
    
    if process.returncode != 0:
        print(f"[✗] Failed to render chat")
        return False
    
    print(f"[✓] Chat rendered to {CHAT_FILE}")
    return True

def combine_videos():
    """Combine video and chat"""
    print(f"\n[+] Combining video and chat")
    
    # Try using hardware acceleration if available
    hw_accel_options = [
        # NVIDIA GPU acceleration
        ["-hwaccel", "cuda", "-c:v", "h264_nvenc"],
        # Apple Silicon acceleration
        ["-hwaccel", "videotoolbox", "-c:v", "h264_videotoolbox"],
        # AMD GPU acceleration
        ["-hwaccel", "amf", "-c:v", "h264_amf"],
        # Intel GPU acceleration
        ["-hwaccel", "qsv", "-c:v", "h264_qsv"],
        # Fallback to CPU
        [""]
    ]
    
    success = False
    
    for accel in hw_accel_options:
        try:
            print(f"  Trying {accel[0] if len(accel) > 0 else 'CPU'} acceleration...")
            
            # Base command
            cmd = ["ffmpeg"]
            
            # Add acceleration if not empty
            if accel and accel[0]:
                cmd.extend(accel[:2])
            
            # Input files and processing options
            cmd.extend([
                "-i", VIDEO_FILE,
                "-i", CHAT_FILE,
                "-filter_complex", "[0:v]scale=-2:1080:flags=lanczos[v0];[1:v]scale=-2:1080:flags=lanczos[v1];[v0][v1]hstack=inputs=2[out]",
                "-map", "[out]", 
                "-map", "0:a?"
            ])
            
            # Add encoder if specified
            if accel and len(accel) > 2:
                cmd.extend(accel[2:])
            else:
                cmd.extend(["-c:v", "h264"])
            
            # Output options
            cmd.extend([
                "-c:a", "aac",
                "-r", "30",
                "-shortest",
                OUTPUT_FILE
            ])
            
            # Run the command
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True
            )
            
            # Monitor for progress (looking for "frame=" output)
            frame_count = 0
            for line in process.stdout:
                if line.startswith("frame="):
                    current_frame = int(line.split("=")[1].split()[0])
                    if current_frame > frame_count + 100:  # Update every 100 frames
                        frame_count = current_frame
                        print(f"  Progress: {current_frame} frames")
            
            # Wait for process to complete
            process.wait()
            
            if process.returncode == 0:
                print(f"[✓] Videos combined successfully using {accel[0] if len(accel) > 0 else 'CPU'}")
                success = True
                break
            
        except Exception as e:
            print(f"  Error with {accel[0] if accel else 'CPU'} acceleration: {e}")
    
    if not success:
        print(f"[✗] Failed to combine videos with any available method")
        return False
    
    return True

def extract_segments():
    """Extract segments from the combined video"""
    print(f"\n[+] Extracting segments from combined video")
    
    try:
        subprocess.run(["python", "main.py"], check=True)
        print(f"[✓] Segments extracted successfully")
        return True
    except subprocess.CalledProcessError:
        print(f"[✗] Failed to extract segments")
        return False

def upload_segments():
    """Upload segments to YouTube"""
    print(f"\n[+] Uploading segments to YouTube")
    
    try:
        subprocess.run(["python", "uploader.py"], check=True)
        print(f"[✓] Segments uploaded successfully")
        return True
    except subprocess.CalledProcessError:
        print(f"[✗] Failed to upload segments")
        return False

def cleanup_temp_files():
    """Clean up temporary files"""
    files_to_remove = [CHAT_JSON]
    
    for file in files_to_remove:
        if os.path.exists(file):
            os.remove(file)
            print(f"Removed temporary file: {file}")

def process_vod(vod_id):
    """Process a Twitch VOD"""
    start_time = time.time()
    
    print(f"\n{'='*50}")
    print(f"  Twitch VOD Processor - VOD ID: {vod_id}")
    print(f"{'='*50}\n")
    
    # Set up downloader
    downloader_path = setup_downloader()
    
    # Clean up old files
    print(f"\n[+] Cleaning up old files")
    cleanup_dirs = ["frames", "post_processed", "titles", "post_processed_titles"]
    cleanup_files = ["ocr_cache.json"]
    
    for dir_name in cleanup_dirs:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"  Removed directory: {dir_name}")
    
    for file_name in cleanup_files:
        if os.path.exists(file_name):
            os.remove(file_name)
            print(f"  Removed file: {file_name}")
    
    # Download VOD and chat
    if not download_vod(vod_id):
        return False
    
    if not download_chat(vod_id, downloader_path):
        return False
    
    # Render chat
    if not render_chat(downloader_path):
        return False
    
    # Combine videos
    if not combine_videos():
        return False
    
    # Extract segments
    if not extract_segments():
        return False
    
    # Upload segments
    if not upload_segments():
        return False
    
    # Calculate elapsed time
    elapsed_time = time.time() - start_time
    minutes, seconds = divmod(int(elapsed_time), 60)
    hours, minutes = divmod(minutes, 60)
    
    print(f"\n{'='*50}")
    print(f"  Processing completed in {hours:02d}:{minutes:02d}:{seconds:02d}")
    print(f"  Output file: {OUTPUT_FILE}")
    print(f"{'='*50}\n")
    
    # Clean up temporary files
    cleanup_temp_files()
    
    return True

if __name__ == "__main__":
    # Check arguments
    if len(sys.argv) < 2:
        print("Error: VOD ID is required")
        print("Usage: python simple_vod_processor.py <vod_id>")
        sys.exit(1)
    
    vod_id = sys.argv[1]
    success = process_vod(vod_id)
    
    sys.exit(0 if success else 1)
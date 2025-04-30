#!/usr/bin/env python3
"""
Twitch VOD Downloader and Processor

This script takes a Twitch VOD ID, downloads the video and chat,
then combines them side by side using ffmpeg. Shows progress in real-time.

Usage:
    python twitch_vod_processor.py <vod_id>

Requirements:
    - twitch-dl (pip install twitch-dl)
    - ffmpeg (must be installed and available in PATH)
    - tqdm (pip install tqdm)
"""

import os
import sys
import subprocess
import time
import argparse
import re
from pathlib import Path
from tqdm import tqdm  # For progress bars


def run_command(command, description):
    """Run a shell command with live output and handle errors"""
    print(f"[+] {description}...")
    try:
        # Use Popen to get live output
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )

        # Variables to track progress
        last_segment = None
        total_segments = None
        downloading_line_count = 0

        # Print output in real-time, with special handling for twitch-dl progress
        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            if not line:
                continue

            # Handle twitch-dl download progress
            if line.startswith("Downloading ") and "VODs using" in line:
                # This is the "Downloading X VODs using Y workers" line
                print(f"  {line}")
                total_segments = int(line.split()[1])
                print(f"  Progress: 0/{total_segments} segments (0%)")
            elif line.startswith("[download]"):
                # This is a twitch-dl download progress line
                if "Downloading segment" in line:
                    segment_parts = line.split()
                    current_segment = int(segment_parts[2].split('/')[0])
                    total_segments = int(segment_parts[2].split('/')[1])

                    # Only update the display for every 5th segment or when we reach a new percentage
                    if last_segment is None or current_segment % 5 == 0 or current_segment == total_segments:
                        percent = int((current_segment / total_segments) * 100)
                        # Clear the previous progress line if it exists
                        if last_segment is not None:
                            sys.stdout.write("\033[F\033[K")  # Move cursor up and clear line
                        print(f"  Progress: {current_segment}/{total_segments} segments ({percent}%)")
                        last_segment = current_segment
                else:
                    # Other download messages
                    print(f"  {line}")
            # For ffmpeg progress
            elif line.startswith("frame="):
                # Only print every 10th ffmpeg progress line to avoid overwhelming output
                if downloading_line_count % 10 == 0:
                    print(f"  {line}")
                downloading_line_count += 1
            # For chat rendering progress
            elif "Rendering chat" in line or "Fetching chat" in line:
                print(f"  {line}")
            else:
                # All other output
                print(f"  {line}")

        # Wait for process to complete and get return code
        return_code = process.wait()

        if return_code != 0:
            print(f"[✗] {description} failed with return code {return_code}")
            return False

        print(f"[✓] {description} completed successfully")
        return True
    except Exception as e:
        print(f"[✗] Error during {description}: {str(e)}")
        return False


def download_vod(vod_id, output_file="forsen2.mp4"):
    """Download the Twitch VOD with progress bar"""
    # First get information about the VOD to estimate total size
    print("[+] Getting VOD information...")
    info_command = f'twitch-dl info {vod_id}'

    try:
        info = subprocess.check_output(info_command, shell=True, universal_newlines=True)

        # Try to extract duration for progress estimation
        duration_match = re.search(r'Duration:\s+(\d+):(\d+):(\d+)', info)
        if duration_match:
            h, m, s = map(int, duration_match.groups())
            total_seconds = h * 3600 + m * 60 + s
            print(f"[i] VOD duration: {h:02d}:{m:02d}:{s:02d} ({total_seconds} seconds)")
        else:
            total_seconds = None
            print("[i] Could not determine VOD duration")

        # Extract title if available
        title_match = re.search(r'Title:\s+(.+)', info)
        if title_match:
            title = title_match.group(1).strip()
            print(f"[i] VOD title: {title}")

    except subprocess.CalledProcessError:
        print("[!] Could not get VOD information")
        total_seconds = None

    # Now download the VOD
    print(f"[+] Downloading VOD (1080p60) to {output_file}...")

    command = f'twitch-dl download -q 1080p60 {vod_id} -o "{output_file}" --chapter 1'
    return run_command(command, "Downloading VOD")


def download_chat(vod_id, output_file="chat.mp4"):
    """Download and render the chat with progress updates"""
    print("[+] Preparing to download and render chat...")

    # First, get information about the chat (this will show if it's available)
    try:
        info_cmd = f'twitch-dl chat --stats {vod_id}'
        chat_info = subprocess.check_output(info_cmd, shell=True, universal_newlines=True)
        print(f"[i] Chat info: {chat_info.strip()}")
    except:
        print("[!] Could not get chat statistics, but will try to download anyway")

    # Now download and render the chat
    command = f'twitch-dl chat --dark --width 300 --height 1080 {vod_id} -o "{output_file}"'
    return run_command(command, "Downloading and rendering chat")


def combine_video_and_chat(video_file="forsen2.mp4", chat_file="chat.mp4", output_file="chat_with_video.mp4"):
    """Combine the video and chat side by side with progress bar"""
    # Get video duration for progress estimation
    try:
        ffprobe_cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_file}"'
        duration_str = subprocess.check_output(ffprobe_cmd, shell=True, universal_newlines=True).strip()
        duration = float(duration_str)
        print(f"[i] Video duration: {int(duration // 60):02d}:{int(duration % 60):02d} ({duration:.2f} seconds)")
    except:
        duration = None
        print("[!] Could not determine video duration")

    # Add progress output to ffmpeg
    command = (
        f'ffmpeg -i "{video_file}" -i "{chat_file}" '
        '-filter_complex "[0:v]scale=-2:720[v0];[1:v]scale=-2:720[v1];'
        '[v0][v1]hstack=inputs=2, pad=ceil(iw/2)*2:ih[out]" '
        f'-map "[out]" -map "0:a?" -c:v libx264 -c:a aac -shortest '
        f'-progress - -stats "{output_file}"'
    )
    return run_command(command, "Combining video and chat")


def cleanup(files_to_remove):
    """Clean up temporary files"""
    for file in files_to_remove:
        if os.path.exists(file):
            try:
                os.remove(file)
                print(f"[✓] Removed temporary file: {file}")
            except Exception as e:
                print(f"[!] Failed to remove {file}: {e}")


def main():
    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Download and process Twitch VODs with chat")
    parser.add_argument("vod_id", help="Twitch VOD ID")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary files after processing")
    parser.add_argument("--output", "-o", default="chat_with_video.mp4", help="Output filename")
    parser.add_argument("--video-file", default="forsen2.mp4", help="Temporary video filename")
    parser.add_argument("--chat-file", default="chat.mp4", help="Temporary chat filename")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed progress information")

    args = parser.parse_args()

    # Set up progress formatting
    start_time = time.time()

    # Print welcome banner
    print("\n" + "=" * 60)
    print(f"  Twitch VOD Processor - VOD ID: {args.vod_id}")
    print("=" * 60 + "\n")

    # Step 1: Download the VOD
    print("\n" + "-" * 30 + " STAGE 1: VOD Download " + "-" * 30)
    if not download_vod(args.vod_id, args.video_file):
        print("\n[!] Failed to download VOD. Exiting.")
        return 1

    # Step 2: Download the chat
    print("\n" + "-" * 30 + " STAGE 2: Chat Download " + "-" * 30)
    if not download_chat(args.vod_id, args.chat_file):
        print("\n[!] Failed to download chat. Exiting.")
        return 1

    # Step 3: Combine video and chat
    print("\n" + "-" * 30 + " STAGE 3: Video Processing " + "-" * 30)
    if not combine_video_and_chat(args.video_file, args.chat_file, args.output):
        print("\n[!] Failed to combine video and chat. Exiting.")
        return 1

    # Clean up temporary files if not keeping them
    if not args.keep_temp:
        print("\n" + "-" * 30 + " STAGE 4: Cleanup " + "-" * 30)
        cleanup([args.video_file, args.chat_file])

    # Calculate and display elapsed time
    elapsed_time = time.time() - start_time
    minutes, seconds = divmod(int(elapsed_time), 60)
    hours, minutes = divmod(minutes, 60)

    # Display completion message with file size
    try:
        file_size = os.path.getsize(args.output) / (1024 * 1024)  # Size in MB
        print("\n" + "=" * 60)
        print(f"[✓] Process completed in {hours:02d}:{minutes:02d}:{seconds:02d}")
        print(f"[✓] Output file: {os.path.abspath(args.output)} ({file_size:.1f} MB)")
        print("=" * 60 + "\n")
    except:
        print("\n" + "=" * 60)
        print(f"[✓] Process completed in {hours:02d}:{minutes:02d}:{seconds:02d}")
        print(f"[✓] Output file: {os.path.abspath(args.output)}")
        print("=" * 60 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
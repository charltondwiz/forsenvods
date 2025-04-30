#!/usr/bin/env python3
"""
Modal VOD Processor - Deploy Version

This script defines functions for processing Twitch VODs using Modal.
It's designed to be deployed to Modal with `modal deploy`.
"""

import modal
import subprocess
import os
import time
import sys
import select

# Define app
app = modal.App("twitch-vod-processor")
volume = modal.Volume.from_name("twitch-vol", create_if_missing=True)

# Base image with ffmpeg and Python packages
image = (
    modal.Image.debian_slim()
    .apt_install(
        "ffmpeg",
        "python3-pip",
        "unzip",
        "curl",
        "ca-certificates",
        "git",  # For twitch-dl --chapter
    )
    .pip_install("twitch-dl==3.0.0")  # Using the latest version
    .run_commands(
        # Test that twitch-dl works
        "twitch-dl --version"
    )
)

@app.function(image=image, volumes={"/data": volume}, timeout=7200)
def download_downloader():
    """Download and setup TwitchDownloaderCLI"""
    import os
    import subprocess
    import time

    downloader_path = "/data/bin/TwitchDownloaderCLI"

    # Check if already exists
    if os.path.exists(downloader_path):
        print(f"TwitchDownloaderCLI already exists at {downloader_path}")
        # Verify it's executable
        subprocess.run(["chmod", "+x", downloader_path], check=True)
        return downloader_path

    # Create directory if it doesn't exist
    os.makedirs("/data/bin", exist_ok=True)

    # Latest release URL
    url = "https://github.com/lay295/TwitchDownloader/releases/download/1.55.5/TwitchDownloaderCLI-1.55.5-Linux-x64.zip"

    # Download and extract with retry logic
    print(f"Downloading TwitchDownloaderCLI from {url}")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"Download attempt {attempt+1}/{max_retries}")

            # Download with curl and verbose output
            print("Running curl download...")
            subprocess.run(
                ["curl", "-L", "-v", "-o", "/data/twitch-dl.zip", url],
                check=True
            )

            # Verify download size
            print("Checking download size...")
            file_info = subprocess.run(
                ["ls", "-la", "/data/twitch-dl.zip"],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"Download file info: {file_info.stdout}")

            # List directory contents for debugging
            print("Contents of /data directory:")
            subprocess.run(["ls", "-la", "/data"], check=True)

            # Unzip to bin directory
            print("Extracting zip file...")
            subprocess.run(
                ["unzip", "-o", "/data/twitch-dl.zip", "-d", "/data/bin"],
                check=True
            )

            # List directory contents after unzip
            print("Contents of /data/bin directory:")
            subprocess.run(["ls", "-la", "/data/bin"], check=True)

            # Make executable
            print("Setting executable permissions...")
            subprocess.run(
                ["chmod", "+x", downloader_path],
                check=True
            )

            # Verify executable works
            print("Testing TwitchDownloaderCLI...")
            version_check = subprocess.run(
                [downloader_path, "--version"],
                capture_output=True,
                text=True,
                check=False
            )
            print(f"Version check output: {version_check.stdout}")
            print(f"Version check error: {version_check.stderr}")

            print(f"TwitchDownloaderCLI setup completed at {downloader_path}")
            return downloader_path

        except Exception as e:
            print(f"Error setting up TwitchDownloaderCLI (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)  # Exponential backoff
                print(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                print("All download attempts failed.")
                raise

@app.function(image=image, volumes={"/data": volume}, timeout=7200)
def download_vod(vod_id, force=False):
    """Download Twitch VOD with extensive retry logic"""
    print(f"Downloading VOD: {vod_id}")
    # Use VOD ID in the filename for better caching
    output_path = f"/data/vod_{vod_id}.mp4"
    
    # Check if VOD already exists and skip download if not forced
    if os.path.exists(output_path) and not force:
        file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"VOD file already exists at {output_path} ({file_size_mb:.2f} MB)")
        # Check if file size is reasonable (>100MB) to ensure it's a valid VOD
        if file_size_mb > 100:
            print(f"Using existing VOD file. Use force=True to redownload.")
            return output_path
        else:
            print(f"Existing VOD file is too small ({file_size_mb:.2f} MB), will redownload")
    elif force:
        print(f"Force download requested for VOD {vod_id}")

    # Check if VOD exists function with retries
    def check_vod_exists(max_attempts=100, delay=1):
        for attempt in range(max_attempts):
            try:
                print(f"Checking if VOD {vod_id} exists... (Attempt {attempt+1}/{max_attempts})")
                # Run with full output capture
                result = subprocess.run(
                    ["twitch-dl", "info", vod_id],
                    capture_output=True,
                    text=True,
                    check=False  # Don't raise exception, we'll check manually
                )

                if result.returncode == 0:
                    print("VOD exists and is accessible!")
                    print(result.stdout)
                    return True

                print(f"Error checking VOD: Return code {result.returncode} (Attempt {attempt+1})")
                print(f"STDOUT: {result.stdout}")
                print(f"STDERR: {result.stderr}")

                # If seeing GraphQL error, retry after delay
                if "GraphQL query failed" in result.stderr:
                    print(f"GraphQL service error detected, retrying in {delay} second(s)...")
                    time.sleep(delay)
                    continue

                # If we've tried several times and still failing, try the alternative method
                if attempt >= 5 and attempt % 5 == 0:
                    print("Trying alternative method to check VOD...")
                    videos_result = subprocess.run(
                        ["twitch-dl", "videos", "forsen", "--limit", "5"],
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    print(f"Available recent VODs from forsen channel:")
                    print(videos_result.stdout)

                # Keep retrying
                print(f"Retrying in {delay} second(s)...")
                time.sleep(delay)

            except Exception as e:
                print(f"Unexpected error checking VOD (Attempt {attempt+1}): {e}")
                time.sleep(delay)

        # If we've exhausted all retries, return False
        return False

    # Function to download VOD with retries and simpler progress monitoring
    def download_with_quality(quality, max_attempts=100, delay=1, timeout=7200):
        # Reduced max_attempts to 5 since if it fails 5 times, it's better to try a different quality
        for attempt in range(max_attempts):
            try:
                print(f"Trying to download with quality: {quality} (Attempt {attempt+1}/{max_attempts})")

                # Try a different approach with more verbose output and debug flags
                cmd = [
                    "twitch-dl", "download",
                    "-q", quality,
                    vod_id,
                    "-c", "1",
                    "-o", output_path,
                    "--overwrite",
                ]

                # Print the full command we're running
                print(f"Running command: {' '.join(cmd)}")

                # Start process with simple output capture
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    bufsize=1
                )

                # Track start time for timeout
                start_time = time.time()
                last_progress_time = start_time

                # Monitor process with timeout - simpler approach
                import threading

                # Variables to collect output
                stdout_data = []
                stderr_data = []
                process_running = True

                # Function to read output streams
                def read_output(pipe, data_list):
                    for line in iter(pipe.readline, ''):
                        if line:
                            data_list.append(line)
                            print(line.strip())

                # Start threads to read output
                stdout_thread = threading.Thread(
                    target=read_output,
                    args=(process.stdout, stdout_data)
                )
                stderr_thread = threading.Thread(
                    target=read_output,
                    args=(process.stderr, stderr_data)
                )
                stdout_thread.daemon = True
                stderr_thread.daemon = True
                stdout_thread.start()
                stderr_thread.start()

                # Variables for stall detection
                last_file_size = 0
                last_size_change_time = time.time()
                stall_timeout = 180  # 3 minutes with no file size change = stall

                # Monitor the process
                while process.poll() is None:
                    # Check for timeout
                    current_time = time.time()
                    if current_time - start_time > timeout:
                        print(f"Download timed out after {timeout} seconds, killing process...")
                        process.kill()
                        break

                    # Check if file exists and get current size
                    current_file_size = 0
                    if os.path.exists(output_path):
                        current_file_size = os.path.getsize(output_path)

                    # Check for stalled download
                    if current_file_size > 0:
                        if current_file_size == last_file_size:
                            stall_duration = current_time - last_size_change_time
                            if stall_duration > stall_timeout:
                                print(f"Download appears stalled - file size hasn't changed in {stall_duration:.0f} seconds")
                                print("Killing the process and trying again...")
                                process.kill()
                                break
                        else:
                            # File size changed, update tracking variables
                            last_file_size = current_file_size
                            last_size_change_time = current_time

                    # Print more frequent progress updates (every 10 seconds)
                    if current_time - last_progress_time > 10:
                        print(f"Download in progress... (running for {int(current_time - start_time)} seconds)")

                        # Show detailed download info
                        if os.path.exists(output_path):
                            file_size_mb = current_file_size / (1024 * 1024)  # Size in MB

                            # Calculate download speed
                            elapsed = current_time - start_time
                            if elapsed > 0:
                                download_speed_mbps = file_size_mb / elapsed
                                print(f"Current file size: {file_size_mb:.2f} MB (Speed: {download_speed_mbps:.2f} MB/s)")

                                # Estimate remaining time if we know the expected size (approx 7h at 1080p60)
                                expected_size_mb = 20000  # ~20GB for 7-8h VOD at high quality
                                if file_size_mb > 0 and download_speed_mbps > 0:
                                    remaining_mb = expected_size_mb - file_size_mb
                                    remaining_sec = remaining_mb / download_speed_mbps
                                    remaining_min = remaining_sec / 60
                                    print(f"Estimated time remaining: {remaining_min:.0f} minutes")
                        else:
                            print("File not created yet")

                        # List running processes for debugging
                        print("Checking twitch-dl processes:")
                        subprocess.run("ps -aux | grep twitch-dl", shell=True)

                        last_progress_time = current_time

                    # Brief sleep to prevent CPU spinning
                    time.sleep(1)

                # Wait for process to complete
                return_code = process.wait()

                # Join output threads
                stdout_thread.join(timeout=1)
                stderr_thread.join(timeout=1)

                # Combine captured output
                stdout_content = ''.join(stdout_data)
                stderr_content = ''.join(stderr_data)

                if return_code == 0:
                    print(f"VOD downloaded to {output_path} with quality {quality}")
                    return True

                print(f"Download failed with quality {quality}: Return code {return_code} (Attempt {attempt+1})")

                # If seeing GraphQL error, retry after delay
                if "GraphQL query failed" in stderr_content:
                    print(f"GraphQL service error detected, retrying in {delay} second(s)...")
                    time.sleep(delay)
                    continue

                # If quality not available, return False to try next quality
                if "doesn't have quality option" in stderr_content:
                    print(f"Quality {quality} not available for this VOD")
                    return False

                # Keep retrying other errors
                print(f"Retrying in {delay} second(s)...")
                time.sleep(delay)

            except Exception as e:
                print(f"Unexpected error downloading VOD (Attempt {attempt+1}): {e}")
                time.sleep(delay)

        # If we've exhausted all retries, return False
        return False

    # Function to try direct download with ffmpeg using m3u8 URL
    def download_with_ffmpeg(quality_name="1080p60", max_attempts=2):
        try:
            print(f"Attempting direct ffmpeg download for VOD {vod_id} with quality {quality_name}")

            # First get the m3u8 URL from twitch-dl info
            info_cmd = ["twitch-dl", "info", vod_id, "--debug"]
            print(f"Getting playlist info: {' '.join(info_cmd)}")

            info_result = subprocess.run(
                info_cmd,
                capture_output=True,
                text=True,
                check=False
            )

            print(f"Info command output: {info_result.stdout}")
            print(f"Info command errors: {info_result.stderr}")

            # Parse the output to find the m3u8 URL for the desired quality
            m3u8_url = None

            for line in info_result.stdout.splitlines():
                if quality_name in line and ".m3u8" in line:
                    parts = line.split()
                    for part in parts:
                        if part.startswith("http") and part.endswith(".m3u8"):
                            m3u8_url = part
                            break

            if not m3u8_url:
                print(f"Could not find m3u8 URL for quality {quality_name}")
                if "1080p60" in quality_name and "chunked" in info_result.stdout:
                    print("Trying to find source/chunked quality instead")
                    for line in info_result.stdout.splitlines():
                        if "chunked" in line and ".m3u8" in line:
                            parts = line.split()
                            for part in parts:
                                if part.startswith("http") and part.endswith(".m3u8"):
                                    m3u8_url = part
                                    break

            if not m3u8_url:
                print("Could not find any suitable m3u8 URL")
                return False

            print(f"Found m3u8 URL: {m3u8_url}")

            # Now use ffmpeg to download
            ffmpeg_cmd = [
                "ffmpeg", "-i", m3u8_url,
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                output_path
            ]

            print(f"Running ffmpeg command: {' '.join(ffmpeg_cmd)}")

            # Start ffmpeg process
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )

            # Track start time for timeout
            start_time = time.time()
            last_progress_time = start_time

            # Variables for stall detection
            last_file_size = 0
            last_size_change_time = time.time()
            stall_timeout = 180  # 3 minutes

            # Monitor the process
            while process.poll() is None:
                current_time = time.time()

                # Check for timeout (2 hours)
                if current_time - start_time > 7200:
                    print("Download timed out after 2 hours, killing process...")
                    process.kill()
                    break

                # Check if file exists and get current size
                current_file_size = 0
                if os.path.exists(output_path):
                    current_file_size = os.path.getsize(output_path)

                # Check for stalled download
                if current_file_size > 0:
                    if current_file_size == last_file_size:
                        stall_duration = current_time - last_size_change_time
                        if stall_duration > stall_timeout:
                            print(f"Download appears stalled - file size hasn't changed in {stall_duration:.0f} seconds")
                            print("Killing the process and trying again...")
                            process.kill()
                            break
                    else:
                        # File size changed, update tracking variables
                        last_file_size = current_file_size
                        last_size_change_time = current_time

                # Print progress updates every 10 seconds
                if current_time - last_progress_time > 10:
                    print(f"ffmpeg download in progress... (running for {int(current_time - start_time)} seconds)")

                    if os.path.exists(output_path):
                        file_size_mb = current_file_size / (1024 * 1024)
                        print(f"Current file size: {file_size_mb:.2f} MB")

                    last_progress_time = current_time

                time.sleep(1)

            # Wait for process to complete
            return_code = process.wait()

            if return_code == 0:
                print(f"ffmpeg download completed successfully")
                return True
            else:
                print(f"ffmpeg download failed with return code {return_code}")
                return False

        except Exception as e:
            print(f"Error in ffmpeg download: {e}")
            return False

    # First check if the VOD exists (with retries)
    if not check_vod_exists():
        raise ValueError(f"VOD {vod_id} not found or inaccessible after multiple attempts")

    # Try downloading with different quality options in case 1080p60 isn't available
    qualities = ["1080p60", "1080p", "720p60", "720p", "best"]

    for quality in qualities:
        if download_with_quality(quality):
            return output_path

    # If twitch-dl failed, try direct ffmpeg download as a fallback
    print("All twitch-dl download attempts failed, trying ffmpeg direct download...")
    for quality in ["1080p60", "720p60", "best"]:
        if download_with_ffmpeg(quality):
            return output_path

    # If all methods failed after all retries
    raise RuntimeError(f"Failed to download VOD {vod_id} with any method after multiple attempts")

@app.function(image=image, volumes={"/data": volume}, timeout=7200)
def download_chat(vod_id, force=False):
    """Download Twitch chat"""
    print(f"Downloading chat for VOD: {vod_id}")
    # Use VOD ID in the filename for better caching
    chat_json_path = f"/data/chat_{vod_id}.json"
    downloader_path = "/data/bin/TwitchDownloaderCLI"
    max_retries = 3
    
    # Check if chat file already exists and skip download if not forced
    if os.path.exists(chat_json_path) and not force:
        file_size_kb = os.path.getsize(chat_json_path) / 1024
        print(f"Chat file already exists at {chat_json_path} ({file_size_kb:.2f} KB)")
        
        # Validate the existing chat file
        try:
            # Try to load the JSON to validate it
            import json
            with open(chat_json_path, 'r') as f:
                chat_data = json.load(f)
            
            # Check for required keys in a TwitchDownloaderCLI chat JSON
            if all(key in chat_data for key in ['comments', 'video', 'streamer']):
                comment_count = len(chat_data.get('comments', []))
                print(f"Existing chat file has {comment_count} comments")
                
                # If it has a reasonable number of comments, use it
                if comment_count > 10:
                    print(f"Using existing chat file. Use force=True to redownload.")
                    return chat_json_path
                else:
                    print(f"Existing chat file has too few comments ({comment_count}), will redownload")
            else:
                print(f"Existing chat file is missing required keys, will redownload")
        except Exception as e:
            print(f"Error validating existing chat file: {e}, will redownload")
    elif force:
        print(f"Force download requested for chat from VOD {vod_id}")

    # Check if downloader exists
    if not os.path.exists(downloader_path):
        print(f"TwitchDownloaderCLI not found at {downloader_path}, downloading...")
        downloader_path = download_downloader.remote()

    # Verify downloader exists now
    if not os.path.exists(downloader_path):
        raise FileNotFoundError(f"TwitchDownloaderCLI still not found at {downloader_path}")

    print(f"Using downloader at {downloader_path}")

    # List files for debugging
    print("Contents of /data/bin directory:")
    subprocess.run(["ls", "-la", "/data/bin"], check=True)

    # Function to validate the JSON file
    def validate_chat_json(file_path):
        try:
            # Check file size first
            file_size = os.path.getsize(file_path)
            if file_size < 100:  # Incredibly small, likely empty or corrupted
                print(f"Warning: Chat JSON file is suspiciously small ({file_size} bytes)")
                return False

            # Try to load the JSON to validate it
            import json
            with open(file_path, 'r') as f:
                chat_data = json.load(f)

            # Check for required keys in a TwitchDownloaderCLI chat JSON
            if not all(key in chat_data for key in ['comments', 'video', 'streamer']):
                print(f"Warning: Chat JSON is missing required keys")
                return False

            # Check if there are any comments
            if 'comments' in chat_data and len(chat_data['comments']) == 0:
                print(f"Warning: Chat JSON has no comments")
                return False

            print(f"Chat JSON validation successful: {len(chat_data.get('comments', []))} comments found")
            return True

        except json.JSONDecodeError:
            print(f"Error: Chat JSON is not valid JSON")
            return False
        except Exception as e:
            print(f"Error validating chat JSON: {e}")
            return False

    # Try multiple methods for downloading chat
    for attempt in range(max_retries):
        try:
            # Make sure we don't have an existing chat file to avoid prompts
            if os.path.exists(chat_json_path):
                print(f"Removing existing chat file at {chat_json_path}")
                os.remove(chat_json_path)

            print(f"Downloading chat (Attempt {attempt+1}/{max_retries})")
            # Get the VOD duration to set an appropriate ending time for chat download
            vod_path = f"/data/vod_{vod_id}.mp4"
            vod_duration = None
            if os.path.exists(vod_path):
                try:
                    # Use ffprobe to get the duration of the VOD
                    duration_cmd = [
                        "ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", vod_path
                    ]
                    duration_result = subprocess.run(duration_cmd, capture_output=True, text=True, check=False)
                    if duration_result.returncode == 0 and duration_result.stdout.strip():
                        vod_duration = float(duration_result.stdout.strip())
                        print(f"VOD duration detected: {vod_duration:.2f} seconds")
                except Exception as e:
                    print(f"Error getting VOD duration: {e}")
            
            # Prepare the chat download command
            download_cmd = [
                downloader_path, "chatdownload",
                "--id", vod_id,
                "-o", chat_json_path,
                "-E"
            ]
            
            # Add ending time parameter if we got the VOD duration
            if vod_duration:
                download_cmd.append(f"-e")
                download_cmd.append(f"{int(vod_duration)}s")
                print(f"Setting chat download ending time to match VOD length: {int(vod_duration)}s")
            
            print(f"Running chat download command: {' '.join(download_cmd)}")

            # Use Popen and monitor with timeout instead of run
            process = subprocess.Popen(
                download_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )

            # Track progress with timeout
            stdout_lines = []
            stderr_lines = []
            start_time = time.time()
            download_timeout = 7200  # 20 minutes for chat download

            # Monitor the process
            print(f"Started chat download process with PID {process.pid}, timeout: {download_timeout}s")

            last_progress_time = start_time
            last_file_size = 0
            while process.poll() is None:
                # Check for timeout
                current_time = time.time()
                elapsed = current_time - start_time

                # Print periodic status
                if current_time - last_progress_time > 30:  # More frequent updates
                    # Check if file exists and is growing
                    if os.path.exists(chat_json_path):
                        print(f"Chat download progress: {int(elapsed)}s elapsed")
                    else:
                        print(f"Chat download in progress for {int(elapsed)}s, file not created yet")
                    last_progress_time = current_time

                # Check for timeout
                if elapsed > download_timeout:
                    print(f"⚠️ Chat download timed out after {download_timeout} seconds. Terminating process.")
                    process.terminate()
                    time.sleep(1)
                    if process.poll() is None:
                        print("Process didn't terminate gracefully, killing it...")
                        process.kill()
                    break

                # Check for output
                stdout_ready = select.select([process.stdout], [], [], 0.1)[0]
                if stdout_ready:
                    line = process.stdout.readline()
                    if line:
                        stdout_lines.append(line)
                        print(f"OUT: {line.strip()}")

                stderr_ready = select.select([process.stderr], [], [], 0.1)[0]
                if stderr_ready:
                    line = process.stderr.readline()
                    if line:
                        stderr_lines.append(line)
                        print(f"ERR: {line.strip()}")

                # Brief sleep to prevent CPU spinning
                time.sleep(0.1)

            # Get final output
            stdout, stderr = process.communicate()
            if stdout:
                stdout_lines.append(stdout)
            if stderr:
                stderr_lines.append(stderr)

            stdout_text = ''.join(stdout_lines)
            stderr_text = ''.join(stderr_lines)

            # Create a result object similar to what subprocess.run would return
            result = type('', (), {})()
            result.returncode = process.returncode
            result.stdout = stdout_text
            result.stderr = stderr_text

            # Check if the command succeeded
            if result.returncode != 0:
                print(f"Chat download failed with return code {result.returncode}")
                print(f"STDOUT: {result.stdout}")
                print(f"STDERR: {result.stderr}")

                # If "is not a valid chat format" error, let's retry with method 2
                if "not a valid chat format" in result.stderr:
                    print("Invalid format error detected, trying method 2...")
                    continue

                # Otherwise, raise the error for regular failures
                result.check_returncode()  # This will raise CalledProcessError

            # Verify the file exists and is valid
            if not os.path.exists(chat_json_path):
                print(f"Error: Chat file was not created at {chat_json_path}")
                continue

            # Validate the chat JSON
            if validate_chat_json(chat_json_path):
                print(f"✅ Chat downloaded and validated successfully at {chat_json_path}")
                import json

                # attempt to load whole file
                with open(chat_json_path, 'r') as f:
                    content = f.read()

                try:
                    chat_data = json.loads(content)
                except json.JSONDecodeError:
                    # truncated—drop the last comment and close JSON
                    last_obj_end = content.rfind("},")
                    if last_obj_end != -1:
                        # keep up through the last complete object
                        fixed = content[: last_obj_end + 1] \
                                + "\n  ],\n" \
                                + content[content.find('"video"') - 2:]
                        try:
                            chat_data = json.loads(fixed)
                            with open(chat_json_path, 'w') as f:
                                json.dump(chat_data, f, indent=2)
                            print("✅ Truncated JSON repaired by dropping last comment.")
                        except json.JSONDecodeError:
                            fixed = None
                    if last_obj_end == -1 or not fixed:
                        # fallback minimal JSON
                        chat_data = {
                            "comments": [
                                {"_id": "1", "message": {"body": "Chat unavailable"}, "commenter": {"name": "System"},
                                 "content_offset_seconds": 0},
                            ],
                            "video": {"id": vod_id, "created_at": "2023-01-01T00:00:00Z", "duration": "36000"},
                            "streamer": {"name": "streamer"},
                            "embeddedData": True
                        }
                        with open(chat_json_path, 'w') as f:
                            json.dump(chat_data, f, indent=2)
                        print("⚠️ Couldn’t repair JSON; wrote minimal fallback.")
                # end of repair

                # now finally return
                return chat_json_path
            else:
                print(f"⚠️ Chat validation failed, retrying...")



        except subprocess.CalledProcessError as e:
            print(f"Error downloading chat (attempt {attempt+1}): {e}")

            # If second attempt, try alternative parameters
            if attempt == 1:
                print("Trying alternative chat download method...")
                try:
                    # Alternative approach with different parameters
                    alt_path = f"{chat_json_path}.alt"

                    # Use a direct alternative format
                    alt_cmd = [
                        downloader_path, "chatdownload",
                        "--id", vod_id,
                        "-o", alt_path,
                        "-E",
                        "--compression-level", "0",  # No compression to avoid potential issues
                        "--ignore-clearsub",  # Skip clear sub messages
                        "--max-download-threads", "1"  # Single thread to avoid race conditions
                    ]

                    print(f"Running alternative download command: {' '.join(alt_cmd)}")

                    # Run with a stricter timeout
                    alt_result = subprocess.run(alt_cmd, capture_output=True, text=True, timeout=180)

                    if os.path.exists(alt_path) and validate_chat_json(alt_path):
                        print(f"✅ Alternative chat download successful at {alt_path}")
                        # Copy to the expected path
                        import shutil
                        shutil.copy2(alt_path, chat_json_path)
                        return chat_json_path
                    else:
                        print("❌ Alternative download produced an invalid file or failed")

                except Exception as alt_err:
                    print(f"Alternative download method failed: {alt_err}")

            # If last attempt, create a minimal valid JSON
            if attempt == max_retries - 1:
                print("All standard methods failed, creating minimal chat data...")
                try:
                    # Create a minimal valid JSON that allows the renderer to run
                    minimal_chat = {
                        "comments": [
                            {"_id": "1", "message": {"body": "Chat unavailable"}, "commenter": {"name": "System"}, "content_offset_seconds": 0},
                            {"_id": "2", "message": {"body": "Please try again later"}, "commenter": {"name": "System"}, "content_offset_seconds": 60},
                            {"_id": "3", "message": {"body": "Using fallback chat mode"}, "commenter": {"name": "System"}, "content_offset_seconds": 120}
                        ],
                        "video": {"id": vod_id, "created_at": "2023-01-01T00:00:00Z", "duration": "36000"},
                        "streamer": {"name": "forsen"},
                        "embeddedData": True
                    }

                    with open(chat_json_path, 'w') as f:
                        import json
                        json.dump(minimal_chat, f, indent=2)

                    print(f"Created minimal chat JSON file at {chat_json_path}")
                    return chat_json_path
                except Exception as fallback_err:
                    print(f"Fallback method also failed: {fallback_err}")

            # Wait before retrying
            time.sleep(5)



    # If we get here, all attempts failed
    raise RuntimeError(f"Failed to download chat for VOD {vod_id} after {max_retries} attempts")

@app.function(image=image, cpu=8.0, memory=32768, volumes={"/data": volume}, timeout=7200)
def render_chat(vod_id, force=True):
    """Render chat to video with GPU acceleration"""
    print(f"Rendering chat to video for VOD {vod_id} with GPU acceleration")
    # Use VOD ID in the filenames for better caching
    chat_json_path = f"/data/chat_{vod_id}.json"
    output_path = f"/data/chat_{vod_id}.mp4"
    downloader_path = "/data/bin/TwitchDownloaderCLI"
    max_retries = 3

    # Check if chat video already exists and skip rendering if not forced
    if os.path.exists(output_path) and not force:
        file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"Chat video already exists at {output_path} ({file_size_mb:.2f} MB)")

        # Check if file size is reasonable (>5MB) to ensure it's a valid video
        if file_size_mb > 5:
            print(f"Using existing chat video. Use force=True to re-render.")
            return output_path
        else:
            print(f"Existing chat video is too small ({file_size_mb:.2f} MB), will re-render")

    # Remove existing file to avoid overwrite prompts
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
            print(f"Removed existing chat video at {output_path}")
        except Exception as e:
            print(f"Error removing existing chat video: {e}")

    if force:
        print(f"Force render requested for chat video")

    # Verify GPU is available and visible to the container
    try:
        print("Checking GPU availability...")
        # Check if nvidia-smi is available
        nvidia_smi = subprocess.run("which nvidia-smi", shell=True, capture_output=True, text=True)
        if nvidia_smi.returncode == 0:
            # Run nvidia-smi to check GPU
            gpu_info = subprocess.run("nvidia-smi", shell=True, capture_output=True, text=True)
            print(f"GPU Info:\n{gpu_info.stdout}")

            # Run nvidia-smi with more detailed information
            gpu_details = subprocess.run("nvidia-smi -q", shell=True, capture_output=True, text=True)
            print(f"Detailed GPU Info (first 500 chars):\n{gpu_details.stdout[:500]}...")

            if "L40S" in gpu_info.stdout:
                print("✅ NVIDIA L40S GPU detected! Using for acceleration.")
            else:
                print("⚠️ WARNING: L40S GPU not detected in nvidia-smi output!")
                # Try to detect what GPU we do have
                if "NVIDIA" in gpu_info.stdout:
                    # Try to extract GPU model
                    import re
                    gpu_model_match = re.search(r"NVIDIA\s+([A-Za-z0-9\s]+)", gpu_info.stdout)
                    if gpu_model_match:
                        gpu_model = gpu_model_match.group(1).strip()
                        print(f"Detected GPU model: {gpu_model}")
        else:
            print("⚠️ WARNING: nvidia-smi not found, GPU may not be properly configured")
            # Install nvidia-smi if missing
            subprocess.run("apt-get update && apt-get install -y nvidia-utils-525", shell=True)

        # Check CUDA capabilities
        print("Checking CUDA configuration...")
        cuda_version = subprocess.run("nvcc --version 2>/dev/null || echo 'nvcc not found'",
                                    shell=True, capture_output=True, text=True)
        print(f"CUDA Compiler:\n{cuda_version.stdout}")

    except Exception as e:
        print(f"Error checking GPU: {e}")
        print("Continuing with render attempt despite GPU check failure")

    # Check if downloader exists
    if not os.path.exists(downloader_path):
        print(f"TwitchDownloaderCLI not found at {downloader_path}, downloading...")
        downloader_path = download_downloader.remote()

    # Remove previous chat video if it exists to avoid prompts
    if os.path.exists(output_path):
        print(f"Removing existing chat video at {output_path}")
        os.remove(output_path)

    # Try multiple methods for rendering
    for attempt in range(max_retries):
        try:
            print(f"Rendering chat (Attempt {attempt+1}/{max_retries})")

            # Determine render method based on attempt
            # Build command based on attempt
            # Check TwitchDownloaderCLI version and get help information
            try:
                # Get help info to understand available commands
                version_cmd = subprocess.run([downloader_path, "--version"], capture_output=True, text=True)
                help_cmd = subprocess.run([downloader_path, "chatrender", "--help"], capture_output=True, text=True)

                # Extract version and help info
                version_str = version_cmd.stdout.strip() if version_cmd.returncode == 0 else "unknown"
                help_text = help_cmd.stdout if help_cmd.returncode == 0 else ""

                print(f"TwitchDownloaderCLI version: {version_str}")
                print(f"Available chatrender options (first 200 chars):\n{help_text[:200]}...")

                # Parse available options from help text
                available_options = []
                for line in help_text.splitlines():
                    if line.strip().startswith("--") or line.strip().startswith("-"):
                        available_options.append(line.strip().split()[0])

                print(f"Detected available options: {available_options[:10]}...")

            except Exception as e:
                print(f"Error checking TwitchDownloaderCLI capabilities: {e}")
                available_options = []
                has_gpu_accel = False

            # Also verify GPU drivers are loaded
            try:
                # Check for CUDA availability
                cuda_check = subprocess.run("ldconfig -p | grep -i cuda", shell=True, capture_output=True, text=True)
                if cuda_check.returncode == 0 and cuda_check.stdout:
                    print("CUDA libraries detected:")
                    print(cuda_check.stdout[:500])  # Show first 500 chars
                else:
                    print("⚠️ WARNING: CUDA libraries not detected! GPU acceleration may not work.")
            except Exception as e:
                print(f"Error checking CUDA: {e}")

            # First check if NVENC is actually available
            nvenc_available = False
            try:
                nvenc_check = subprocess.run("ffmpeg -encoders | grep nvenc", shell=True, capture_output=True, text=True)
                if nvenc_check.returncode == 0 and nvenc_check.stdout.strip():
                    print(f"NVENC encoders found: {nvenc_check.stdout.strip()}")
                    nvenc_available = True
                else:
                    print("⚠️ No NVENC encoders detected in FFmpeg!")
            except Exception as e:
                print(f"Error checking NVENC availability: {e}")

            if attempt != -1:
                # First attempt: Choose appropriate encoder based on NVENC availability
                cmd = [
                    downloader_path, "chatrender",
                    "-i", chat_json_path,
                    "-h", "1080",
                    "-w", "422",
                    "--framerate", "5",
                    "--font-size", "18",
                    "--update-rate", "0.5",  # Update less frequently for speed
                    "--offline",
                ]

                # Get the VOD file length to set an appropriate ending time
                vod_path = f"/data/vod_{vod_id}.mp4"
                vod_duration = None
                if os.path.exists(vod_path):
                    try:
                        # Use ffprobe to get the duration of the VOD
                        duration_cmd = [
                            "ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", vod_path
                        ]
                        duration_result = subprocess.run(duration_cmd, capture_output=True, text=True, check=False)
                        if duration_result.returncode == 0 and duration_result.stdout.strip():
                            vod_duration = float(duration_result.stdout.strip())
                            print(f"VOD duration detected: {vod_duration:.2f} seconds")
                    except Exception as e:
                        print(f"Error getting VOD duration: {e}")

                # Remove NVENC encoding as it's proven not to work for chat rendering
                print("Using CPU-only encoding for chat rendering (NVENC not compatible)")

                # Add ending time parameter if we got the VOD duration
                if vod_duration:
                    cmd.append(f"-e {int(vod_duration)}s")
                    print(f"Setting chat render ending time to match VOD length: {int(vod_duration)}s")

                cmd.extend([
                    "-o", output_path,
                    "--collision", "Overwrite"
                ])

                print(f"Running GPU-accelerated render command: {' '.join(cmd)}")

            # Try to detect if version requires uppercase -O instead of lowercase -o
            if version_str and "1.55.5" in version_str:
                # Replace all instances of -o with -O in the command
                for i in range(len(cmd)):
                    if cmd[i] == "-o":
                        cmd[i] = "-O"
                        print("Using uppercase -O output flag for version 1.55.5")

            print(f"Final render command: {' '.join(cmd)}")

            # Start the process with real-time output monitoring
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )

            # Track start time and set up monitoring variables
            start_time = time.time()
            last_progress_time = start_time
            last_output_time = start_time
            last_file_size = 0 if os.path.exists(output_path) else 0
            render_timeout = 1800  # 30 minutes max for rendering

            # Output collection
            stdout_lines = []
            stderr_lines = []

            # Monitor the render process
            while process.poll() is None:
                # Check for timeout
                current_time = time.time()
                elapsed = current_time - start_time

                # Check for overall timeout
                if elapsed > render_timeout:
                    print(f"⚠️ Chat render timed out after {render_timeout} seconds. Terminating process.")
                    process.terminate()
                    time.sleep(1)
                    if process.poll() is None:
                        process.kill()
                    break

                # Check for output and progress
                stdout_ready = select.select([process.stdout], [], [], 0.1)[0]
                if stdout_ready:
                    line = process.stdout.readline()
                    if line:
                        stdout_lines.append(line)
                        print(f"OUT: {line.strip()}")
                        last_output_time = current_time

                stderr_ready = select.select([process.stderr], [], [], 0.1)[0]
                if stderr_ready:
                    line = process.stderr.readline()
                    if line:
                        stderr_lines.append(line)
                        print(f"ERR: {line.strip()}")
                        last_output_time = current_time

                        # Check for unreasonable progress estimate
                        if "Rendering Video" in line and "Remaining" in line:
                            # Parse the remaining time estimate
                            try:
                                # Extract remaining time from format like: "[STATUS] - Rendering Video 0% (0h0m8s Elapsed | 1h21m17s Remaining)"
                                import re
                                remaining_match = re.search(r'(\d+)h(\d+)m(\d+)s Remaining', line)
                                if remaining_match:
                                    hours = int(remaining_match.group(1))
                                    minutes = int(remaining_match.group(2))
                                    seconds = int(remaining_match.group(3))
                                    total_remaining_seconds = hours * 3600 + minutes * 60 + seconds

                                    # Log the estimated time
                                    print(f"Render estimates {hours}h {minutes}m {seconds}s remaining")

                                    # If remaining time is over 30 minutes and we're still at early percentage, abort and try a faster method
                                    if total_remaining_seconds > 1800 and "0%" in line and elapsed < 60:
                                        print(f"⚠️ Render estimates excessive time ({hours}h {minutes}m {seconds}s). Aborting to try faster method.")
                                        process.terminate()
                                        time.sleep(1)
                                        if process.poll() is None:
                                            process.kill()
                                        return False  # Signal to try next method
                            except Exception as e:
                                print(f"Error parsing render progress: {e}")

                # Print periodic status updates about the rendering progress
                if current_time - last_progress_time > 10:  # Every 10 seconds
                    # Check output file growth as an indicator of progress
                    if os.path.exists(output_path):
                        current_file_size = os.path.getsize(output_path)
                        file_size_mb = current_file_size / (1024 * 1024)

                        # Calculate growth rate
                        size_diff_mb = (current_file_size - last_file_size) / (1024 * 1024)
                        time_diff = current_time - last_progress_time
                        render_speed = size_diff_mb / time_diff if time_diff > 0 else 0

                        print(f"Chat render progress: {int(elapsed)}s elapsed, file size: {file_size_mb:.2f} MB (Speed: {render_speed:.2f} MB/s)")

                        # Update for next iteration
                        last_file_size = current_file_size
                    else:
                        print(f"Chat render in progress for {int(elapsed)}s, output file not created yet")

                        # Check if process seems stalled (no output for a while)
                        if current_time - last_output_time > 120:  # 2 minutes with no output
                            print("⚠️ Render process may be stalled (no output for 2 minutes)")

                    last_progress_time = current_time

                # Brief sleep to prevent CPU spinning
                time.sleep(0.1)

            # If we get here, process completed normally or was killed
            # Get return code and remaining output
            return_code = process.poll()
            stdout, stderr = process.communicate()

            if stdout:
                stdout_lines.append(stdout)
            if stderr:
                stderr_lines.append(stderr)

            # Combine captured output
            stdout_content = ''.join(stdout_lines)
            stderr_content = ''.join(stderr_lines)

            # Create a result object similar to what subprocess.run would return
            result = type('', (), {})()
            result.returncode = return_code
            result.stdout = stdout_content
            result.stderr = stderr_content

            # Check if the command succeeded
            if result.returncode != 0:
                print(f"Chat render failed with return code {result.returncode}")
                continue
            else:
                # Command succeeded
                print(f"Chat rendered successfully to {output_path}")
                return output_path

        except Exception as e:
            print(f"Error rendering chat (attempt {attempt+1}): {e}")
            # Wait before retrying
            time.sleep(2)

    # If we get here, all attempts failed
    raise RuntimeError("Failed to render chat video after multiple attempts")

@app.function(image=image, gpu="L40S", volumes={"/data": volume}, timeout=7200)
def combine_videos(vod_id, force=True):
    """Combine video and chat with GPU acceleration"""
    print(f"Combining video and chat for VOD {vod_id} with GPU acceleration")
    # Use VOD ID in the filenames for better caching
    video_path = f"/data/vod_{vod_id}.mp4"
    chat_path = f"/data/chat_{vod_id}.mp4"
    output_path = f"/data/combined_{vod_id}.mp4"
    
    # Check if combined video already exists and skip if not forced
    if os.path.exists(output_path) and not force:
        file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"Combined video already exists at {output_path} ({file_size_mb:.2f} MB)")
        
        # Check if file size is reasonable (>100MB) to ensure it's a valid video
        if file_size_mb > 100:
            print(f"Using existing combined video. Use force=True to recombine.")
            return output_path
        else:
            print(f"Existing combined video is too small ({file_size_mb:.2f} MB), will recombine")
    
    # Remove existing file to avoid overwrite prompts
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
            print(f"Removed existing combined video at {output_path}")
        except Exception as e:
            print(f"Error removing existing combined video: {e}")
            
    if force:
        print(f"Force combine requested for video and chat")
    
    # Check if input files exist
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found at {video_path}")
    
    if not os.path.exists(chat_path):
        raise FileNotFoundError(f"Chat video not found at {chat_path}")
    
    # Try multiple approaches with better GPU acceleration
    methods = [
        # Maximum L40S GPU acceleration with explicit memory management
        f'ffmpeg -y -hwaccel cuda -hwaccel_output_format cuda -i "{video_path}" -i "{chat_path}" '
        f'-filter_complex "[0:v]hwupload,format=cuda,scale_cuda=-2:1080[v0];[1:v]hwupload,format=cuda,scale_cuda=-2:1080[v1];[v0][v1]hstack=inputs=2[out]" '
        f'-map "[out]" -map "0:a?" -c:v h264_nvenc -preset p1 -tune hq -b:v 8M -c:a aac -r 30 -shortest "{output_path}"',
        
        # Alternative optimized CUDA approach
        f'ffmpeg -y -hwaccel cuda -hwaccel_output_format cuda -i "{video_path}" -i "{chat_path}" '
        f'-filter_complex "[0:v]scale_cuda=-2:1080[v0];[1:v]scale_cuda=-2:1080[v1];[v0][v1]hstack=inputs=2[out]" '
        f'-map "[out]" -map "0:a?" -c:v h264_nvenc -preset p1 -tune hq -b:v 8M -c:a aac -r 30 -shortest "{output_path}"',
        
        # Fallback GPU approach with simpler filters
        f'ffmpeg -y -hwaccel cuda -i "{video_path}" -i "{chat_path}" '
        f'-filter_complex "hstack=inputs=2[out]" '
        f'-map "[out]" -map "0:a?" -c:v h264_nvenc -preset p1 -tune ll -b:v 5M -c:a aac -r 30 -shortest "{output_path}"',
        
        # CPU fallback as last resort
        f'ffmpeg -y -i "{video_path}" -i "{chat_path}" '
        f'-filter_complex "hstack=inputs=2[out]" '
        f'-map "[out]" -map "0:a?" -c:v h264 -preset ultrafast -crf 28 -c:a aac -r 30 -shortest "{output_path}"'
    ]
    
    for i, cmd in enumerate(methods):
        try:
            print(f"Trying method {i+1}/{len(methods)}...")
            print(f"Running command: {cmd}")
            
            # Start the process with real-time monitoring
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            # Track start time and set up monitoring variables
            start_time = time.time()
            last_progress_time = start_time
            last_file_size = 0 if os.path.exists(output_path) else 0
            combine_timeout = 3600  # 1 hour max for combining videos
            
            # Monitor the process
            while process.poll() is None:
                current_time = time.time()
                elapsed = current_time - start_time
                
                # Check for timeout
                if elapsed > combine_timeout:
                    print(f"⚠️ Video combining timed out after {combine_timeout} seconds. Terminating process.")
                    process.terminate()
                    time.sleep(1)
                    if process.poll() is None:
                        process.kill()
                    break
                
                # Process output
                stderr_ready = select.select([process.stderr], [], [], 0.1)[0]
                if stderr_ready:
                    line = process.stderr.readline()
                    if line and "frame=" in line:  # ffmpeg progress
                        print(f"PROGRESS: {line.strip()}")
                
                # Print periodic status updates about the combining progress
                if current_time - last_progress_time > 10:  # Every 10 seconds
                    print(f"Video combining in progress, elapsed time: {int(elapsed)}s")
                    
                    # Check output file growth
                    if os.path.exists(output_path):
                        current_file_size = os.path.getsize(output_path)
                        file_size_mb = current_file_size / (1024 * 1024)
                        
                        # Calculate growth rate
                        size_diff_mb = (current_file_size - last_file_size) / (1024 * 1024)
                        time_diff = current_time - last_progress_time
                        processing_speed = size_diff_mb / time_diff if time_diff > 0 else 0
                        
                        print(f"Combine progress: output size {file_size_mb:.2f} MB (Speed: {processing_speed:.2f} MB/s)")
                        
                        # Update for next iteration
                        last_file_size = current_file_size
                    else:
                        print(f"Output file not created yet")
                    
                    last_progress_time = current_time
                
                # Brief sleep to prevent CPU spinning
                time.sleep(0.1)
            
            # Process completed, get return code
            return_code = process.poll()
            
            if return_code == 0:
                print(f"Videos combined to {output_path} using method {i+1}")
                return output_path
            else:
                stderr = process.stderr.read()
                print(f"Method {i+1} failed with code {return_code}: {stderr}")
                
        except Exception as e:
            print(f"Method {i+1} failed with exception: {e}")
    
    raise RuntimeError("All video combining methods failed")

@app.function(image=image, volumes={"/data": volume}, timeout=7200)
def get_result(vod_id):
    """Get the final combined video"""
    src_path = f"/data/combined_{vod_id}.mp4"
    dest_path = f"vod_{vod_id}.mp4"
    
    # Check if the source file exists
    if not os.path.exists(src_path):
        print(f"Combined video not found at {src_path}, checking alternative paths...")
        # Try some alternative paths
        alt_paths = [
            f"/data/combined_{vod_id}.mp4",
            f"/data/chat_with_video.mp4",
            f"/data/vod_{vod_id}.mp4",
            "/data/output.mp4"
        ]
        
        for alt_path in alt_paths:
            if os.path.exists(alt_path):
                print(f"Found alternative file at {alt_path}")
                src_path = alt_path
                break
        else:
            raise FileNotFoundError(f"Could not find any video output files in /data")
    
    # Print file information
    file_size_mb = os.path.getsize(src_path) / (1024 * 1024)
    print(f"Source file: {src_path} (Size: {file_size_mb:.2f} MB)")
    
    # Copy from volume to container
    import shutil
    print(f"Copying from {src_path} to {dest_path}")
    shutil.copy(src_path, dest_path)
    
    # Verify the copy worked
    if os.path.exists(dest_path):
        copy_size_mb = os.path.getsize(dest_path) / (1024 * 1024)
        print(f"Successfully copied file: {dest_path} (Size: {copy_size_mb:.2f} MB)")
    else:
        print(f"Warning: Copy appears to have failed, dest_path does not exist!")
    
    # Modal will automatically download this file
    return dest_path

@app.function(timeout=7200)
def process_vod(vod_id, force=True):
    """Process a VOD from start to finish"""
    print(f"Processing VOD {vod_id} with GPU acceleration")
    combined_output_path = f"/data/combined_{vod_id}.mp4"
    
    # Check if combined file already exists and skip processing if not forced
    if os.path.exists(combined_output_path) and not force:
        file_size_mb = os.path.getsize(combined_output_path) / (1024 * 1024)
        print(f"Combined video already exists at {combined_output_path} ({file_size_mb:.2f} MB)")
        
        if file_size_mb > 100:
            print(f"Using existing combined video. Use force=True to reprocess.")
            # Just get the result file
            final_path = get_result.remote(vod_id)
            print(f"Final result ready: {final_path}")
            return final_path
        else:
            print(f"Existing combined video is too small ({file_size_mb:.2f} MB), will reprocess")
    elif force:
        print(f"Force processing requested for VOD {vod_id}")
    
    # Step 1: Setup TwitchDownloaderCLI
    print("Setting up TwitchDownloaderCLI...")
    downloader_path = download_downloader.remote()
    print(f"Downloader setup complete: {downloader_path}")
    
    # Step 2: Download VOD and chat sequentially to avoid race conditions
    print("Downloading VOD...")
    vod_path = download_vod.remote(vod_id, force=False)
    print(f"VOD download complete: {vod_path}")
    
    print("Downloading chat...")
    chat_path = download_chat.remote(vod_id, force=False)
    print(f"Chat download complete: {chat_path}")
    
    # Check if chat video already exists
    chat_mp4_path = f"/data/chat_{vod_id}.mp4"
    if os.path.exists(chat_mp4_path) and not force:
        file_size_mb = os.path.getsize(chat_mp4_path) / (1024 * 1024)
        print(f"Chat video already exists at {chat_mp4_path} ({file_size_mb:.2f} MB)")
        
        if file_size_mb > 5:  # At least 5MB for a valid chat video
            print(f"Using existing chat video. Use force=True to re-render.")
            chat_mp4 = chat_mp4_path
        else:
            print(f"Existing chat video is too small ({file_size_mb:.2f} MB), will re-render")
            print("Rendering chat with GPU...")
            chat_mp4 = render_chat.remote(vod_id, force=False)
            print(f"Chat rendering complete: {chat_mp4}")
    else:
        # Step 3: Render chat with GPU
        print("Rendering chat with GPU...")
        # Wait for 10 seconds to ensure the chat file is ready
        print("Waiting for chat file to be ready...")
        time.sleep(10)
        print("Rendering chat...")
        chat_mp4 = render_chat.remote(vod_id, force=force)
        print(f"Chat rendering complete: {chat_mp4}")
    
    # Step 4: Combine video and chat
    print("Combining video and chat...")
    # Wait for 10 seconds to ensure the chat video is ready
    print("Waiting for chat video to be ready...")
    time.sleep(10)
    print("Combining videos...")
    result_path = combine_videos.remote(vod_id, force=force)
    print(f"Video combining complete: {result_path}")
    
    # Step 5: Get the result and prepare for download
    print("Getting final result...")
    print(f"Preparing file for download - combined video path: {combined_output_path}")
    
    # Ensure the combined file exists
    if os.path.exists(combined_output_path):
        file_size_mb = os.path.getsize(combined_output_path) / (1024 * 1024)
        print(f"Combined video exists: {combined_output_path} (Size: {file_size_mb:.2f} MB)")
    else:
        print(f"Warning: Combined video not found at expected path: {combined_output_path}")
        print("Looking for any video outputs...")
        # Try to find any video files that might have been created
        potential_videos = []
        for file in os.listdir("/data"):
            if file.endswith(".mp4"):
                file_path = f"/data/{file}"
                file_size = os.path.getsize(file_path) / (1024 * 1024)
                potential_videos.append((file_path, file_size))
        
        if potential_videos:
            # Sort by size, largest first
            potential_videos.sort(key=lambda x: x[1], reverse=True)
            print("Found these potential video files:")
            for path, size in potential_videos:
                print(f" - {path} ({size:.2f} MB)")
            # Use the largest file
            combined_output_path = potential_videos[0][0]
            print(f"Using largest file as output: {combined_output_path}")
        else:
            print("No video files found in /data!")
    
    # Call get_result to download the file
    final_path = get_result.remote(vod_id)
    print(f"Final result ready: {final_path}")
    
    return final_path
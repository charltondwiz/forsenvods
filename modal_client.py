#!/usr/bin/env python3
"""
Modal VOD Processor Client

This script is a client for the Modal VOD processor.
It calls the deployed Modal app to process a Twitch VOD and then
downloads the result file directly from the Modal volume.
"""

import os
import sys
import subprocess
import time
import modal
import glob
import shutil

# Define and access the volume that stores our results
volume = modal.Volume.from_name("twitch-vol")
app = modal.App("twitch-vod-processor")

# Function to list files in the Modal volume using the Modal CLI
def list_volume_files():
    """List files in the Modal volume using the CLI."""
    print("Listing files in Modal volume 'twitch-vol'...")
    try:
        # Use modal CLI to list files in the volume
        command = "modal volume ls twitch-vol"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"Error listing volume files: {result.stderr}")
            return []
        
        # Parse the output to find MP4 files
        lines = result.stdout.splitlines()
        mp4_files = []
        
        for line in lines:
            if line.endswith(".mp4"):
                # Extract just the filename
                filename = line.strip()
                mp4_files.append(filename)
        
        print(f"Found {len(mp4_files)} MP4 files in volume:")
        for filename in mp4_files:
            print(f" - {filename}")
        
        return mp4_files
    except Exception as e:
        print(f"Error listing volume files: {e}")
        return []

# Function to download file from Modal volume using CLI
def cli_download_from_volume(vod_id=None):
    """Download the processed video from the Modal volume using modal CLI.
    Returns the path to the downloaded file if successful."""
    print(f"Preparing to download VOD {vod_id} from Modal volume using CLI...")
    
    # First, list files in the volume
    mp4_files = list_volume_files()
    if not mp4_files:
        print("No MP4 files found in the volume!")
        return None
    
    # Look for file matching VOD ID
    target_file = None
    output_name = "chat_with_video.mp4"
    
    if vod_id:
        # Look for files matching the VOD ID
        vod_matches = [f for f in mp4_files if f"_{vod_id}" in f]
        if vod_matches:
            print(f"Found files matching VOD ID {vod_id}:")
            for filename in vod_matches:
                print(f" - {filename}")
            # Use the first match, preferring "combined_" files
            combined_matches = [f for f in vod_matches if f.startswith("combined_")]
            if combined_matches:
                target_file = combined_matches[0]
            else:
                target_file = vod_matches[0]
        else:
            print(f"No files found matching VOD ID {vod_id}")
    
    # If no VOD-specific file found, look for any "combined_" files
    if not target_file:
        combined_files = [f for f in mp4_files if f.startswith("combined_")]
        if combined_files:
            print("Found combined files:")
            for filename in combined_files:
                print(f" - {filename}")
            target_file = combined_files[0]
        elif mp4_files:
            print("Using first available MP4 file as target")
            target_file = mp4_files[0]
    
    # Download the target file
    if target_file:
        try:
            print(f"Downloading {target_file} from volume to {output_name}...")
            # Use modal CLI to download the file
            command = f"modal volume get twitch-vol {target_file} ./{output_name}"
            print(f"Running command: {command}")
            
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                print(f"Error downloading file: {result.stderr}")
                return None
            
            # Verify the file was downloaded
            if os.path.exists(output_name):
                file_size = os.path.getsize(output_name) / (1024 * 1024)
                print(f"Successfully downloaded {target_file} to {output_name} ({file_size:.2f} MB)")
                return output_name
            else:
                print(f"Error: File {output_name} not found after download!")
                return None
        except Exception as e:
            print(f"Error downloading file: {e}")
            return None
    else:
        print("No suitable files found to download!")
        return None

# Function to directly download file from Modal volume
@app.local_entrypoint()
def download_from_volume(vod_id=None):
    """Download the processed video directly from the Modal volume.
    This runs locally and downloads the file to the current directory."""
    print(f"Connecting to Modal volume to download VOD {vod_id}...")
    
    # Mount the volume locally
    with volume.from_name("/vol") as local_dir:
        print(f"Volume mounted to {local_dir}")
        print("Listing files in Modal volume:")
        
        # List all MP4 files in the volume
        mp4_files = glob.glob(f"{local_dir}/*.mp4")
        print(f"Found {len(mp4_files)} MP4 files in volume:")
        
        # Sort files by size (largest first)
        mp4_files_with_size = [(f, os.path.getsize(f)) for f in mp4_files]
        mp4_files_with_size.sort(key=lambda x: x[1], reverse=True)
        
        for filepath, size in mp4_files_with_size:
            filename = os.path.basename(filepath)
            size_mb = size / (1024 * 1024)
            print(f" - {filename} ({size_mb:.2f} MB)")
        
        # Look for files matching VOD ID if provided
        target_file = None
        output_name = "chat_with_video.mp4"
        
        if vod_id:
            # Look for files matching the VOD ID
            vod_matches = [f for f, _ in mp4_files_with_size if f"_{vod_id}" in f]
            if vod_matches:
                print(f"Found files matching VOD ID {vod_id}:")
                for filepath in vod_matches:
                    print(f" - {os.path.basename(filepath)}")
                target_file = vod_matches[0]  # Use the first match
            else:
                print(f"No files found matching VOD ID {vod_id}")
        
        # If no VOD-specific file found, use the largest file
        if not target_file and mp4_files_with_size:
            print("Using largest MP4 file as target")
            target_file = mp4_files_with_size[0][0]
        
        # Copy the file locally
        if target_file:
            filename = os.path.basename(target_file)
            file_size = os.path.getsize(target_file) / (1024 * 1024)
            print(f"Copying {filename} ({file_size:.2f} MB) to {output_name}...")
            shutil.copy(target_file, output_name)
            print(f"Successfully downloaded to {output_name}")
            return output_name
        else:
            print("No suitable files found to download!")
            return None

def run_modal_processor(vod_id):
    """Run the Modal processor on the given VOD ID"""
    print(f"Processing VOD {vod_id} using Modal")
    start_time = time.time()

    try:
        # Look up the deployed function by (app_name, function_name)
        process_vod_fn = modal.Function.from_name(
            "twitch-vod-processor",  # your deployed app name
            "process_vod"            # the @app.function name
        )

        print("Running Modal processing...")
        # This invokes the function remotely
        print("Starting Modal function and waiting for result...")
        result_path = process_vod_fn.remote(vod_id)
        print(f"Modal function returned: {result_path}")
        print("Function completed, now attempting to download result file...")
        
        # Call the CLI download function to get the file
        output_file = cli_download_from_volume(vod_id)
        
        # Check if the output file was downloaded successfully
        if output_file and os.path.exists(output_file):
            file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
            print(f"Successfully downloaded output file: {output_file} ({file_size_mb:.2f} MB)")
        else:
            print("ERROR: Failed to download the output file from Modal volume!")
            print("Processing may have failed or file was not generated correctly.")
            return False

        # Timing
        elapsed = int(time.time() - start_time)
        hrs, rem = divmod(elapsed, 3600)
        mins, secs = divmod(rem, 60)
        print(f"Modal processing completed in {hrs:02d}:{mins:02d}:{secs:02d}")
        print(f"Output saved to: {output_file}")

        # Continue with your pipeline
        print("Running segment extraction...")
        subprocess.run(["python", "main.py"], check=True)

        print("Uploading segments to YouTube...")
        subprocess.run(["python", "uploader.py"], check=True)

        print("Pipeline completed successfully!")
        return True

    except Exception as e:
        print(f"Error with Modal processing: {e}")
        print("Attempting to download result file directly...")
        
        # Try to download the file directly even if processing had an error
        try:
            output_file = cli_download_from_volume(vod_id)
            if output_file and os.path.exists(output_file):
                file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
                print(f"Successfully downloaded output file despite errors: {output_file} ({file_size_mb:.2f} MB)")
                return True
            else:
                print("Could not recover the output file.")
                return False
        except Exception as download_error:
            print(f"Recovery download also failed: {download_error}")
            return False


@app.local_entrypoint()
def just_download_latest_file():
    """Just download the latest file from the volume without processing anything."""
    print("Downloading the latest file from Modal volume using CLI...")
    result = cli_download_from_volume()
    if result:
        print(f"Successfully downloaded file to {result}")
        return 0
    else:
        print("Failed to download any files")
        return 1

if __name__ == "__main__":
    # Check if download-only mode was requested
    if len(sys.argv) > 1 and sys.argv[1] == "--download-only":
        print("Download-only mode requested")
        result = cli_download_from_volume(sys.argv[2] if len(sys.argv) > 2 else None)
        sys.exit(0 if result else 1)
        
    # Check for VOD ID
    if len(sys.argv) < 2:
        print("Error: VOD ID is required")
        print("Usage: python modal_client.py <vod_id>")
        print("       python modal_client.py --download-only [vod_id]")
        # Use a default VOD ID for testing
        print("Using default VOD ID 2429943090 for testing")
        vod_id = "2429943090"
    else:
        vod_id = sys.argv[1]
    
    # Run the processor
    success = run_modal_processor(vod_id)
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)
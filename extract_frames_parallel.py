#!/usr/bin/env python3
"""
Frame extraction script for YouTube title detection
This script efficiently extracts frames from a video file using parallel processing
"""

import os
import multiprocessing
import subprocess
import time
import argparse
from functools import partial

# Default configuration
DEFAULT_VIDEO_FILE = "forsen2.mp4"
DEFAULT_FRAME_DIR = "frames"
DEFAULT_TITLE_DIR = "titles"
DEFAULT_INTERVAL = 3

def process_region(region_params, video_file, title_dir, interval_seconds):
    """Process a single title region using ffmpeg"""
    region_num, vf_params, region_desc = region_params
    region_dir = f"{title_dir}/region{region_num}"
    
    # Create directory
    os.makedirs(region_dir, exist_ok=True)
    
    print(f"⏳ Processing Region {region_num}: {region_desc}...")
    start_time = time.time()
    
    try:
        # Run ffmpeg command for this region
        result = subprocess.run([
            "ffmpeg", "-i", video_file,
            "-vf", f"fps=1/{interval_seconds}, {vf_params}",
            f"{region_dir}/frame_%04d.jpg",
            "-hide_banner", "-loglevel", "error"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            file_count = len(os.listdir(region_dir))
            elapsed = time.time() - start_time
            print(f"✅ Region {region_num}: {file_count} files extracted to {region_dir} in {elapsed:.2f}s")
            return True
        else:
            print(f"❌ Error processing region {region_num}: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Exception processing region {region_num}: {e}")
        return False

def extract_frames_parallel(video_file, frame_dir, title_dir, interval_seconds):
    """Extract frames from video with parallel processing for title regions"""
    
    # Ensure required directories exist
    os.makedirs(frame_dir, exist_ok=True)
    os.makedirs(title_dir, exist_ok=True)
    
    print(f"🎬 Parallel frame extraction from {video_file}")
    print(f"   Interval: {interval_seconds} seconds")
    print(f"   Output directories: {frame_dir}, {title_dir}")
    
    # Start timer
    start_time = time.time()
    
    # Extract main frames first
    print(f"⏳ Extracting main frames...")
    subprocess.run([
        "ffmpeg", "-i", video_file,
        "-vf", f"fps=1/{interval_seconds}, crop=in_w*0.4:in_h*0.06:in_w*0.055:in_h*0.03",
        f"{frame_dir}/frame_%04d.jpg",
        "-hide_banner", "-loglevel", "error"
    ])
    
    main_frame_count = len(os.listdir(frame_dir))
    main_elapsed = time.time() - start_time
    print(f"✅ Extracted {main_frame_count} main frames to {frame_dir} in {main_elapsed:.2f}s")
    
    # Define the crop parameters and descriptions for each region
    region_params = [
        (1, "crop=in_w*0.65:in_h*0.06:in_w*0.03:in_h*0.07", "Top region (7% from top)"),
        (2, "crop=in_w*0.65:in_h*0.06:in_w*0.03:in_h*0.875", "Upper region (87.5% from top)"),
        (3, "crop=in_w*0.65:in_h*0.06:in_w*0.03:in_h*0.85", "Middle region (85% from top)"),
        (4, "crop=in_w*0.75:in_h*0.06:in_w*0.03:in_h*0.875", "Wider region (75% width)"),
        (5, "crop=in_w*0.65:in_h*0.06:in_w*0.03:in_h*0.9", "Lower region (90% from top)")
    ]
    
    # Determine optimal CPU count: use n-1 cores to avoid overloading the system
    cpu_count = max(1, multiprocessing.cpu_count() - 1)
    print(f"🧠 Using {cpu_count} CPU cores for parallel processing")
    
    # Process title regions in parallel
    region_start = time.time()
    
    # Create a pool and map the work
    with multiprocessing.Pool(processes=cpu_count) as pool:
        # Create a partial function with fixed arguments
        process_func = partial(
            process_region, 
            video_file=video_file,
            title_dir=title_dir,
            interval_seconds=interval_seconds
        )
        
        # Process all regions in parallel
        results = pool.map(process_func, region_params)
    
    # Check results
    success_count = sum(1 for r in results if r)
    region_elapsed = time.time() - region_start
    total_elapsed = time.time() - start_time
    
    # Summary
    print("\n=== Frame Extraction Summary ===")
    print(f"✅ {success_count}/{len(region_params)} regions processed successfully")
    print(f"⏱️ Region extraction time: {region_elapsed:.2f}s")
    print(f"⏱️ Total processing time: {total_elapsed:.2f}s")
    
    # Count files in each directory
    main_frames = len(os.listdir(frame_dir))
    print(f"\n--- File Counts ---")
    print(f"Main frames: {main_frames}")
    
    total_title_frames = 0
    for region_num, _, _ in region_params:
        region_dir = os.path.join(title_dir, f"region{region_num}")
        if os.path.exists(region_dir):
            file_count = len(os.listdir(region_dir))
            total_title_frames += file_count
            print(f"Region {region_num}: {file_count} files")
    
    print(f"Total title frames: {total_title_frames}")
    print(f"Total frames extracted: {main_frames + total_title_frames}")
    
def main():
    """Main function to parse arguments and run extraction"""
    parser = argparse.ArgumentParser(description="Extract video frames for YouTube title detection")
    
    parser.add_argument("--video", "-v", default=DEFAULT_VIDEO_FILE,
                        help=f"Input video file (default: {DEFAULT_VIDEO_FILE})")
    parser.add_argument("--frames", "-f", default=DEFAULT_FRAME_DIR,
                        help=f"Output directory for main frames (default: {DEFAULT_FRAME_DIR})")
    parser.add_argument("--titles", "-t", default=DEFAULT_TITLE_DIR,
                        help=f"Output directory for title frames (default: {DEFAULT_TITLE_DIR})")
    parser.add_argument("--interval", "-i", type=int, default=DEFAULT_INTERVAL,
                        help=f"Seconds between frames (default: {DEFAULT_INTERVAL})")
    
    args = parser.parse_args()
    
    # Run extraction
    extract_frames_parallel(
        args.video,
        args.frames,
        args.titles,
        args.interval
    )

if __name__ == "__main__":
    main()
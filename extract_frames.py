import os
import subprocess

# === CONFIG ===
VIDEO_FILE = "forsen2.mp4"  # Use the video file we know exists
FRAME_DIR = "frames"
TITLE_DIR = "titles"
INTERVAL_SECONDS = 3

# Ensure required directories exist
os.makedirs(FRAME_DIR, exist_ok=True)
os.makedirs(TITLE_DIR, exist_ok=True)

# Create title region directories
for region in range(1, 6):
    os.makedirs(os.path.join(TITLE_DIR, f"region{region}"), exist_ok=True)

def extract_frames_from_video():
    """Extract frames from the video for main frames and all title regions"""
    
    # Extract main frames
    print(f"Extracting frames from {VIDEO_FILE} at {INTERVAL_SECONDS} second intervals...")
    subprocess.run([
        "ffmpeg", "-i", VIDEO_FILE,
        "-vf", f"fps=1/{INTERVAL_SECONDS}, crop=in_w*0.4:in_h*0.06:in_w*0.055:in_h*0.03",
        f"{FRAME_DIR}/frame_%04d.jpg",
        "-hide_banner", "-loglevel", "error"
    ])
    print(f"Frames extracted to {FRAME_DIR}/")

    print("Extracting titles from frames with adaptive multi-region approach...")
    
    # Region 1: Top region - for titles at the top of the frame
    print("Processing Region 1: Top region")
    subprocess.run([
        "ffmpeg", "-i", VIDEO_FILE,
        "-vf", f"fps=1/{INTERVAL_SECONDS}, crop=in_w*0.65:in_h*0.06:in_w*0.03:in_h*0.07",
        f"{TITLE_DIR}/region1/frame_%04d.jpg",
        "-hide_banner", "-loglevel", "error"
    ])
    
    # Region 2: Upper title region - most common position
    print("Processing Region 2: Upper title region")
    subprocess.run([
        "ffmpeg", "-i", VIDEO_FILE,
        "-vf", f"fps=1/{INTERVAL_SECONDS}, crop=in_w*0.65:in_h*0.06:in_w*0.03:in_h*0.875",
        f"{TITLE_DIR}/region2/frame_%04d.jpg", 
        "-hide_banner", "-loglevel", "error"
    ])
    
    # Region 3: Middle title region - for centered titles
    print("Processing Region 3: Middle title region")
    subprocess.run([
        "ffmpeg", "-i", VIDEO_FILE,
        "-vf", f"fps=1/{INTERVAL_SECONDS}, crop=in_w*0.65:in_h*0.06:in_w*0.03:in_h*0.85",
        f"{TITLE_DIR}/region3/frame_%04d.jpg",
        "-hide_banner", "-loglevel", "error"
    ])
    
    # Region 4: Wider crop for longer titles
    print("Processing Region 4: Wider crop region")
    subprocess.run([
        "ffmpeg", "-i", VIDEO_FILE,
        "-vf", f"fps=1/{INTERVAL_SECONDS}, crop=in_w*0.75:in_h*0.06:in_w*0.03:in_h*0.875",
        f"{TITLE_DIR}/region4/frame_%04d.jpg",
        "-hide_banner", "-loglevel", "error"
    ])
    
    # Region 5: Lower position - for cases when title is lower in frame
    print("Processing Region 5: Lower position region")
    subprocess.run([
        "ffmpeg", "-i", VIDEO_FILE,
        "-vf", f"fps=1/{INTERVAL_SECONDS}, crop=in_w*0.65:in_h*0.06:in_w*0.03:in_h*0.9",
        f"{TITLE_DIR}/region5/frame_%04d.jpg",
        "-hide_banner", "-loglevel", "error"
    ])
    
    print(f"Multi-region title crops extracted to {TITLE_DIR}/")

# Run frame extraction
extract_frames_from_video()

# Count files in each directory to verify extraction worked
print("\n--- File Counts ---")
print(f"Main frames: {len(os.listdir(FRAME_DIR))}")
for region in range(1, 6):
    region_dir = os.path.join(TITLE_DIR, f"region{region}")
    file_count = len(os.listdir(region_dir))
    print(f"Region {region}: {file_count} files")
import os
import subprocess

# Setup basic configuration
VIDEO_FILE = "forsen2.mp4"
TITLE_DIR = "titles"
INTERVAL_SECONDS = 3

# Ensure directory exists
os.makedirs(os.path.join(TITLE_DIR, "region2"), exist_ok=True)

# Try to extract frames for region2
try:
    print(f"Testing extraction for region2 from {VIDEO_FILE}...")
    
    # Debug: Print directory contents to verify the video file exists
    print("Files in current directory:")
    print(os.listdir("."))
    
    # Run the ffmpeg command
    cmd = [
        "ffmpeg", "-i", VIDEO_FILE,
        "-vf", f"fps=1/{INTERVAL_SECONDS}, crop=in_w*0.65:in_h*0.06:in_w*0.03:in_h*0.875",
        f"{TITLE_DIR}/region2/frame_%04d.jpg", 
        "-hide_banner", "-loglevel", "error"
    ]
    
    # Print the command for debugging
    print("Running command:", " ".join(cmd))
    
    # Execute the command
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # Check results
    if result.returncode == 0:
        print("Command successful!")
        print(f"Created files in {TITLE_DIR}/region2/:")
        files = os.listdir(f"{TITLE_DIR}/region2/")
        print(f"Found {len(files)} files")
        if files:
            print("First few files:", files[:5])
    else:
        print("Command failed with return code:", result.returncode)
        print("Error output:", result.stderr)
        
except Exception as e:
    print(f"Error during test: {e}")
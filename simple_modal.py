#!/usr/bin/env python3
"""
Simple Modal GPU Test

This script uses Modal.com's cloud platform to test GPU access.
"""

import modal

# Define the Modal app
app = modal.App("gpu-test-app")

# Define the image with all required packages
image = modal.Image.debian_slim().apt_install(
    "ffmpeg", 
    "curl",
    "wget"
)

# Define a function that runs on Modal with GPU
@app.function(gpu="T4", image=image)
def test_gpu():
    import subprocess
    import os
    
    # Print available GPUs
    print("Testing GPU availability...")
    
    # Run nvidia-smi to check GPU
    try:
        output = subprocess.check_output(["nvidia-smi"], text=True)
        print("NVIDIA GPU detected:")
        print(output)
    except Exception as e:
        print(f"Error running nvidia-smi: {e}")
    
    # Test FFmpeg with GPU
    try:
        print("Testing FFmpeg with GPU...")
        subprocess.run(["ffmpeg", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-f", "lavfi", 
                         "-i", "testsrc=duration=5:size=1280x720:rate=30", "-c:v", "h264_nvenc", "-y", "/tmp/test.mp4"])
        
        # Check if the output file was created
        if os.path.exists("/tmp/test.mp4"):
            file_size = os.path.getsize("/tmp/test.mp4")
            print(f"Successfully created test video with GPU acceleration (size: {file_size} bytes)")
        else:
            print("Failed to create test video")
    except Exception as e:
        print(f"Error testing FFmpeg: {e}")
    
    # Return success
    return "GPU test completed"

# Main entry point
@app.local_entrypoint()
def main():
    print("Starting GPU test with Modal...")
    result = test_gpu.remote()
    print(f"Result: {result}")

if __name__ == "__main__":
    main()
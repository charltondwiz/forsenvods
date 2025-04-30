# Multi-Region Title Detection System

This document explains the enhanced title detection system implemented in the forsenVods project. The system uses a multi-region approach to improve the accuracy of YouTube title detection in stream videos.

## Implementation Overview

The title extraction process has been upgraded in several ways:

1. **Multi-Region Scanning**: Instead of a fixed single region, we now extract 5 different regions from each frame:
   - Region 1: Top region (7% from top)
   - Region 2: Upper title region (87.5% from top) - most common position
   - Region 3: Middle title region (85% from top)
   - Region 4: Wider crop for longer titles (75% of frame width)
   - Region 5: Lower position (90% from top)

2. **Adaptive Region Selection**: The system tries each region in a priority order when detecting titles, making it more robust to different video layouts.

3. **Improved Directory Structure**: Each region has its own subdirectory in the `titles/` folder, making organization clearer.

## How It Works

1. The system extracts frames from the input video at regular intervals
2. For each frame, it creates 5 different cropped versions focusing on different regions where titles might appear
3. When searching for YouTube titles, it checks each region in order of likelihood
4. The first valid title found is used, with fallback to previous title if no valid title is found

## Code Structure

The main changes were made to:

- `get_title_path()`: Updated to return paths to the new multi-region directory structure
- `extract_frames_from_video()`: Modified to extract 5 different regions for each frame
- Directory initialization: Added code to create all region subdirectories at startup

## Performance Considerations

The multi-region approach significantly increases processing time since it generates 5x more cropped images. To address this:

1. **Parallel Processing**: The system now uses parallel processing via Python's multiprocessing module to extract and process frames more efficiently, utilizing all available CPU cores.
   - Title region extraction happens in parallel across all 5 regions
   - Frame analysis is performed in batches with multiple cores

2. **Optimization Options**:
   - Increase the frame interval (INTERVAL_SECONDS) for faster but less precise detection
   - Use the standalone extraction script `extract_frames_parallel.py` as a preprocessing step
   - Enable/disable parallel processing with the PARALLEL_PROCESSING flag

3. **Batch Processing**: The frame analysis phase processes frames in batches for better performance

## Advanced Features

1. **Parallel Region Extraction**: Each title region is processed in a separate process, enabling much faster extraction on multi-core systems

2. **Batch Frame Analysis**: Frames are analyzed in parallel batches, dramatically speeding up YouTube ID detection

3. **Multithreaded Segment Detection**: The system uses all available CPU cores to maximize performance

4. **Adaptive Core Utilization**: Automatically determines the optimal number of CPU cores to use (typically N-1 cores)

5. **Intelligent Title Caching**: Prevents title conflicts between different YouTube segments
   - Uses a `prevent_title_caching` flag to avoid overwriting titles during boundary detection
   - Maintains the correct title for each segment even when searching for boundaries
   - Ensures title integrity when multiple YouTube videos appear in sequence

## Future Improvements

Potential future enhancements:

1. **Smarter Region Selection**: Adapt region selection based on initial scans of the video
2. **Caching Improvements**: Cache processed frames to avoid reprocessing
3. **Region Auto-Detection**: Automatically detect the most promising regions in the first few minutes of video
4. **GPU Acceleration**: Utilize GPU for faster image processing
5. **Distributed Processing**: Split work across multiple machines for extremely large videos

## Usage

### Standard Usage

To use the multi-region title detection:

1. Set the correct input video in the CONFIG section: `VIDEO_FILE = "your_video.mp4"`
2. Run the script: `python main.py`
3. The system will extract all regions and process them to find YouTube segments

### Performance Optimized Approach

For very large videos, use the two-step approach with parallel processing:

1. **Step 1: Extract Frames** (can be done ahead of time)
   ```bash
   python extract_frames_parallel.py --video your_video.mp4 --interval 3
   ```
   
   Options:
   - `--video` or `-v`: Specify the input video file
   - `--frames` or `-f`: Output directory for main frames
   - `--titles` or `-t`: Output directory for title frames
   - `--interval` or `-i`: Seconds between frames

2. **Step 2: Process the pre-extracted frames**
   ```bash
   python main.py
   ```

### Configuration Options

In `main.py`, you can adjust the following settings:

```python
# Performance settings
INTERVAL_SECONDS = 3         # Time between frames (higher = faster but less precise)
PARALLEL_PROCESSING = True   # Enable/disable parallel processing
FRAME_JUMP = 10              # Frames to skip during scanning
DEBUG_MODE = False           # Set to False to reduce logging for faster execution
```

For maximum performance on a multi-core system, ensure `PARALLEL_PROCESSING` is set to `True`.
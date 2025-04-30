# Modal-based Twitch VOD Processor

This implementation uses [Modal](https://modal.com) to process Twitch VODs in the cloud with GPU acceleration, replacing the local rendering steps in the forsenVods pipeline.

## Benefits

- Uses T4 GPUs for faster video processing
- Offloads CPU-intensive tasks to cloud infrastructure
- Parallel processing for improved performance
- Compatible with the existing pipeline

## Requirements

- Python 3.6+
- Modal account and CLI setup (`pip install modal`)
- OAuth 2.0 credentials for YouTube uploading (client_secret.json)

## Setup

1. Install Modal:
   ```
   pip install modal
   ```

2. Log in to Modal:
   ```
   modal token new
   ```

3. Make sure you have client_secret.json in the project directory for YouTube uploads

4. Make the script executable:
   ```
   chmod +x modal_vod_grabber.sh
   ```

## Usage

### Basic Usage

```
./modal_vod_grabber.sh <VOD_ID>
```

### Advanced Options

```
./modal_vod_grabber.sh <VOD_ID> [--keep-temp] [--no-upload]
```

Options:
- `--keep-temp`: Keep temporary files after processing
- `--no-upload`: Skip uploading segments to YouTube

### Direct Python Usage

You can also use the Python script directly:

```
python modal_vod_processor.py <VOD_ID> [--keep-temp] [--no-upload]
```

## How It Works

1. **VOD Download**: Downloads the Twitch VOD using Modal
2. **Chat Processing**: Downloads and renders the chat alongside the video
3. **Video Combining**: Uses GPU-accelerated FFmpeg to combine video and chat
4. **Segment Extraction**: Processes the combined video to extract YouTube reaction segments
5. **YouTube Upload**: Uploads the extracted segments to YouTube

## Pipeline Components

- `modal_vod_processor.py`: Main Python implementation for Modal
- `modal_vod_grabber.sh`: Bash wrapper script to match existing workflow
- Modal volume: Persists data between steps to avoid unnecessary transfers

## Migrating from the Existing Pipeline

The Modal implementation is designed as a drop-in replacement for the existing pipeline. Simply use `modal_vod_grabber.sh` instead of `vod_grabber.sh` to process VODs using Modal.

If you need to customize the processing parameters, you can modify `modal_vod_processor.py` to suit your requirements.
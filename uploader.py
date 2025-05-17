#!/usr/bin/env python3
"""
YouTube Video Uploader

This script uploads all video files from a folder called 'segments' to YouTube.
Each video's title on YouTube will be the same as its filename (without extension).

Prerequisites:
1. Python 3.6+
2. Install required packages: pip install google-api-python-client oauth2client
3. Create a project in Google Developer Console and enable YouTube Data API v3
4. Create OAuth 2.0 Client ID credentials and download the client_secret.json file
5. Place client_secret.json in the same directory as this script

Usage:
python youtube_uploader.py

Note: On first run, the script will open a browser window for authentication.
"""

import os
import sys
import time
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from googleapiclient.http import MediaFileUpload

# Constants
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
CLIENT_SECRETS_FILE = 'client_secret.json'
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'
SEGMENTS_FOLDER = 'segments'  # Folder containing the video files
VALID_EXTENSIONS = ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv']


def get_authenticated_service():
    """Get an authenticated YouTube service instance."""
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, SCOPES)
    credentials = flow.run_local_server(port=8080)

    return googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials=credentials)


def initialize_upload(youtube, file_path, title):
    """Initialize a YouTube video upload."""
    body = {
        'snippet': {
            'title': title,
            'description': f'{title}. \n\n#forsen #forsenreacts #forsenclips #forsenlive',
            'tags': ['auto-upload'],
            'categoryId': '20'  # Streamer category
        },
        'status': {
            'privacyStatus': 'public'  # Set to 'private', 'unlisted', or 'public'
        }
    }

    # Create MediaFileUpload instance
    media = MediaFileUpload(file_path, chunksize=1024 * 1024, resumable=True)

    # Call the API's videos.insert method to create and upload the video
    request = youtube.videos().insert(
        part=','.join(body.keys()),
        body=body,
        media_body=media
    )

    # Upload the video
    print(f"Uploading {title}...")
    response = None
    error = None
    retry = 0

    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"Uploaded {int(status.progress() * 100)}%")
        except googleapiclient.errors.HttpError as e:
            error = f"An HTTP error {e.resp.status} occurred:\n{e.content}"
            if retry < 10:
                retry += 1
                print(f"Retrying... (attempt {retry})")
                time.sleep(retry * 2)  # Exponential backoff
            else:
                break

    if error:
        print(error)
        return None

    print(f"Upload Complete! Video ID: {response['id']}")
    return response['id']


def main():
    """Upload all videos from the segments folder."""
    # Check if the segments folder exists
    if not os.path.exists(SEGMENTS_FOLDER):
        print(f"Error: Folder '{SEGMENTS_FOLDER}' not found. Please create it and add your videos.")
        return

    # Get a list of video files in the segments folder
    video_files = []
    for filename in os.listdir(SEGMENTS_FOLDER):
        file_path = os.path.join(SEGMENTS_FOLDER, filename)
        if os.path.isfile(file_path):
            _, ext = os.path.splitext(filename)
            if ext.lower() in VALID_EXTENSIONS:
                video_files.append(file_path)

    if not video_files:
        print(f"No video files found in the '{SEGMENTS_FOLDER}' folder.")
        return

    # Authenticate and get YouTube service
    try:
        youtube = get_authenticated_service()
        print("Authentication successful!")
    except Exception as e:
        print(f"Authentication failed: {e}")
        return

    # Upload each video
    for video_path in video_files:
        # Get the filename without extension as the title
        filename = os.path.basename(video_path)
        title, _ = os.path.splitext(filename)

        try:
            video_id = initialize_upload(youtube, video_path, title)
            if video_id:
                print(f"Uploaded: {title} (Video ID: {video_id})")
                print(f"Video URL: https://www.youtube.com/watch?v={video_id}")
                print("-" * 50)

                # Add a delay between uploads to avoid rate limiting
                if video_path != video_files[-1]:  # If not the last video
                    print("Waiting before next upload...")
                    time.sleep(1)  # Wait 10 seconds between uploads

        except Exception as e:
            print(f"Error uploading {title}: {e}")

    print("All uploads completed!")


if __name__ == '__main__':
    main()
#!/usr/bin/env python3
"""
Modal argument passing test
"""
import modal
import os
import sys

app = modal.App("arg-test")

@app.function()
def test_arg_passing(vod_id):
    """Test function that receives an argument"""
    print(f"Received vod_id: {vod_id}")
    return f"Processed VOD {vod_id}"

@app.local_entrypoint()
def main():
    if len(sys.argv) > 1:
        vod_id = sys.argv[1]
    else:
        vod_id = "test_id_12345"
    
    print(f"Local VOD ID: {vod_id}")
    
    print("\nCalling remote function with argument...")
    result = test_arg_passing.remote(vod_id)
    print(f"Result: {result}")
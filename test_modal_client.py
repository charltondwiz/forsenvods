#!/usr/bin/env python3
"""
Test Modal Client

This script tests connections to a running Modal application.
"""

import modal

if __name__ == "__main__":
    # Connect to the running app
    print("Testing Modal GPU function...")
    
    with modal.Session() as session:
        # Get the function from the running app
        test_gpu = session.lookup("gpu-test-app", "test_gpu")
        
        # Call the function
        result = test_gpu.remote()
        print(f"Result: {result}")
        
    print("Done!")
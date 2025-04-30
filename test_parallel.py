#!/usr/bin/env python3
"""
Simple test script to verify parallel processing is working
"""

import os
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor

def worker_function(n):
    """Sample worker function that just sleeps and returns a value"""
    print(f"Worker {n} starting...")
    time.sleep(1)  # Simulate some work
    print(f"Worker {n} done")
    return n * n

def main():
    """Test if parallel processing is working properly"""
    print(f"System has {multiprocessing.cpu_count()} CPU cores")
    
    # Create a list of numbers to process
    numbers = list(range(1, 11))
    
    print("Testing parallel processing with ProcessPoolExecutor...")
    start_time = time.time()
    
    with ProcessPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
        results = list(executor.map(worker_function, numbers))
    
    end_time = time.time()
    elapsed = end_time - start_time
    
    print(f"Results: {results}")
    print(f"Parallel execution took {elapsed:.2f} seconds")
    
    print("\nTesting sequential processing for comparison...")
    start_time = time.time()
    
    sequential_results = [worker_function(n) for n in numbers]
    
    end_time = time.time()
    sequential_elapsed = end_time - start_time
    
    print(f"Results: {sequential_results}")
    print(f"Sequential execution took {sequential_elapsed:.2f} seconds")
    
    speedup = sequential_elapsed / elapsed if elapsed > 0 else 0
    print(f"\nSpeedup factor: {speedup:.2f}x")
    
    if speedup > 1.5:
        print("✅ Parallel processing is working correctly!")
    else:
        print("⚠️ Parallel processing may not be functioning optimally")

if __name__ == "__main__":
    main()
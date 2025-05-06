#!/bin/bash


mkdir -p results
echo "Starting benchmark runs..."

for size in $(seq 2 2 32); do
    echo "Running simulation with array size: ${size}KB"
    mkdir -p "results/${size}kb"
    
    python3 config.py --binary="tests/test-progs/my-tests/lax" --args="${size}" \
        --outdir="results/${size}kb"
    
    echo "Completed run for size ${size}KB"
    echo "----------------------------------------"
done

echo "All benchmark runs completed."
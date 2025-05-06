#!/bin/bash


GEM5_PATH="../../build/RISCV/gem5.opt"
SIM_SCRIPT="./config.py"

mkdir -p results

echo "Starting benchmark runs..."

for size in $(seq 2 2 32); do
    echo "Running simulation with array size: ${size}KB"
    mkdir -p "results/${size}kb"
    
    ${GEM5_PATH} -d "results/${size}kb" ${SIM_SCRIPT} --binary="../../tests/test-progs/my-tests/lax" --args="${size}"
    
    echo "Completed run for size ${size}KB"
    echo "----------------------------------------"
done

echo "All benchmark runs completed."
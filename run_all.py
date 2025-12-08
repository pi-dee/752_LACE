import multiprocessing
import os
import subprocess

# List of benchmarks you want to run
benchmarks = [
    "ferret",
    "fluidanimate",
    "raytrace",
    "dedup",
    "blackscholes",
    "bodytrack",
]


def run_simulation(bench_name):
    # Ensure the output directory exists (optional, gem5 usually creates it)
    outdir = f"{bench_name}_k0.75"

    cmd = [
        "./build/X86/gem5.opt",
        "--debug-flag=LACE",
        f"--outdir={outdir}",  # Unique output directory for stats
        "configs/example/gem5_library/x86-parsec-benchmarks.py",
        f"--benchmark={bench_name}",
        "--size=simsmall",
    ]

    # Redirect stdout/stderr to a log file
    with open(f"{bench_name}.log", "w") as log_file:
        print(f"Launching {bench_name}...")
        subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT)
        print(f"Finished {bench_name}")


if __name__ == "__main__":
    # Create a pool of workers equal to the number of benchmarks
    # Note: Ensure your host machine has enough cores/RAM!
    with multiprocessing.Pool(processes=len(benchmarks)) as pool:
        pool.map(run_simulation, benchmarks)

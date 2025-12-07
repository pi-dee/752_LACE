import subprocess
import os
import re

# --- Configuration ---
GEM5_BIN = "./build/X86/gem5.opt"

# Get the absolute path to the directory containing this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_SCRIPT = os.path.join(SCRIPT_DIR, "fs_parsec_mesh.py")

# Checkpoint path (Use the "booted" checkpoint created earlier)
CHECKPOINT_PATH = "m5out/cpt.booted" 

# CORRECTED PATH based on your 'find' output
GUEST_BASE_DIR = "/home/gem5/parsec-benchmark/pkgs" 

# Define the location of the PARSEC hooks library
HOOKS_LIB_DIR = f"{GUEST_BASE_DIR}/libs/hooks/inst/amd64-linux.gcc-hooks/lib"

benchmarks = {
    "blackscholes": {
        "cmd": (
            f"cd /tmp; "
            f"ls -l {GUEST_BASE_DIR}/apps/blackscholes/inputs/; "
            f"tar xf {GUEST_BASE_DIR}/apps/blackscholes/inputs/input_simsmall.tar; "
            f"if [ -d inputs ]; then mv inputs/* .; fi; "
            f"ls -l; "
            f"export LD_LIBRARY_PATH={HOOKS_LIB_DIR}:$LD_LIBRARY_PATH; "
            f"{GUEST_BASE_DIR}/apps/blackscholes/inst/amd64-linux.gcc-hooks/bin/blackscholes 8 in_4K.txt prices.txt"
        ),
        "args": "" 
    },
    "canneal": {
        "cmd": (
            f"cd /tmp; "
            f"ls -l {GUEST_BASE_DIR}/kernels/canneal/inputs/; "
            f"tar xf {GUEST_BASE_DIR}/kernels/canneal/inputs/input_simsmall.tar; "
            f"if [ -d inputs ]; then mv inputs/* .; fi; "
            f"ls -l; "
            f"export LD_LIBRARY_PATH={HOOKS_LIB_DIR}:$LD_LIBRARY_PATH; "
            f"{GUEST_BASE_DIR}/kernels/canneal/inst/amd64-linux.gcc-hooks/bin/canneal 8 10000 2000 100000.nets 32"
        ),
        "args": ""
    },
    "bodytrack": {
        "cmd": (
            f"cd /tmp; "
            f"tar xf {GUEST_BASE_DIR}/apps/bodytrack/inputs/input_simsmall.tar; "
            f"if [ -d inputs ]; then mv inputs/* .; fi; "
            f"export LD_LIBRARY_PATH={HOOKS_LIB_DIR}:$LD_LIBRARY_PATH; "
            # Args: input_dir num_points num_frames num_particles num_annealing_layers num_threads
            f"{GUEST_BASE_DIR}/apps/bodytrack/inst/amd64-linux.gcc-hooks/bin/bodytrack sequenceB_1 4 1 1000 5 0 8"
        ),
        "args": ""
    },
    "fluidanimate": {
        "cmd": (
            f"cd /tmp; "
            f"tar xf {GUEST_BASE_DIR}/apps/fluidanimate/inputs/input_simsmall.tar; "
            f"if [ -d inputs ]; then mv inputs/* .; fi; "
            f"export LD_LIBRARY_PATH={HOOKS_LIB_DIR}:$LD_LIBRARY_PATH; "
            # Args: num_threads num_frames input_file output_file
            f"{GUEST_BASE_DIR}/apps/fluidanimate/inst/amd64-linux.gcc-hooks/bin/fluidanimate 8 5 in_35K.fluid out.fluid"
        ),
        "args": ""
    },
    "streamcluster": {
        "cmd": (
            f"cd /tmp; "
            f"tar xf {GUEST_BASE_DIR}/kernels/streamcluster/inputs/input_simsmall.tar; "
            f"if [ -d inputs ]; then mv inputs/* .; fi; "
            f"export LD_LIBRARY_PATH={HOOKS_LIB_DIR}:$LD_LIBRARY_PATH; "
            # Args: k1 k2 d n chunksize clustersize infile outfile nthreads
            f"{GUEST_BASE_DIR}/kernels/streamcluster/inst/amd64-linux.gcc-hooks/bin/streamcluster 10 20 32 4096 4096 1000 none output.txt 8"
        ),
        "args": ""
    }
}

def parse_remote_percentage(stats_file):
    """Parses stats.txt for Ruby Network Remote Accesses."""
    total_packets = 0
    remote_packets = 0
    
    # Matches 'board' OR 'system' to be safe
    pattern = re.compile(r"(?:system|board)\.ruby\.network\.data_traffic_distribution\.n(\d+)\.n(\d+)\s+(\d+)")

    if not os.path.exists(stats_file):
        print(f"Stats file not found: {stats_file}")
        return 0.0

    print(f"Parsing {stats_file}...")
    with open(stats_file, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                src = int(match.group(1))
                dst = int(match.group(2))
                count = int(match.group(3))
                total_packets += count
                if src != dst:
                    remote_packets += count

    print(f"  -> Found {total_packets} total packets.")
    return (remote_packets / total_packets * 100.0) if total_packets > 0 else 0.0

def run_simulation(bench_name, config):
    out_dir = f"m5out_{bench_name}"
    
    # Combined command string
    guest_script = (
        f"{config['cmd']};\n" 
        "m5 exit;"                             
    )
    
    print(f"\n--- Running {bench_name} ---")
    
    cmd = [
        GEM5_BIN,
        f"--outdir={out_dir}",
        CONFIG_SCRIPT,
        f"--command={guest_script}",
        f"--checkpoint-path={CHECKPOINT_PATH}"
    ]

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Simulation failed: {e}")
        return None

    return os.path.join(out_dir, "stats.txt")

def main():
    results = {}
    
    for name, config in benchmarks.items():
        stats_path = run_simulation(name, config)
        if stats_path:
            results[name] = parse_remote_percentage(stats_path)
    
    print(f"\n{'Benchmark':<20} | {'Remote Access %':<15}")
    print("-" * 40)
    for name, pct in results.items():
        print(f"{name:<20} | {pct:.2f}%")

    if results:
        csv_filename = "results_summary.csv"
        with open(csv_filename, "w") as f:
            f.write("Benchmark,Remote_Access_Percent\n")
            for name, pct in results.items():
                f.write(f"{name},{pct:.2f}\n")
        print(f"\nResults saved to {csv_filename}")

if __name__ == "__main__":
    main()
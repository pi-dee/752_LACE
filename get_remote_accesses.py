import subprocess
import os
import re
import matplotlib.pyplot as plt

# --- Configuration ---

# Path to gem5 binary
GEM5_BIN = "./build/X86/gem5.opt"

# Path to the configuration script
CONFIG_SCRIPT = "configs/ece752/run_parsec_test.py"

# Base directory for benchmarks (inferred from your prompt)
BASE_BENCH_DIR = "/home/paridhi/class/parsec-benchmark/pkgs"

# Fixed parameters for all runs
COMMON_PARAMS = [
    "--num-cpus=8",
    "--num-dirs=8",
    "--num-l2caches=8",
    "--cpu-type=TimingSimpleCPU",
    "--network=garnet",
    "--topology=Mesh_XY",
    "--mesh-rows=2",
    "--mem-size=16GB"
]

# Define Benchmarks: Name -> {executable path, input arguments}
# NOTE: You must verify the paths and input arguments for bodytrack/canneal/etc.
benchmarks = {
    "blackscholes": {
        "cmd": f"{BASE_BENCH_DIR}/apps/blackscholes/inst/amd64-linux.gcc/bin/blackscholes",
        "options": f"8 {BASE_BENCH_DIR}/apps/blackscholes/inputs/in_4.txt prices.txt"
    },
    # Placeholder for Bodytrack - Update path/options if needed
    "bodytrack": {
        "cmd": f"{BASE_BENCH_DIR}/apps/bodytrack/inst/amd64-linux.gcc/bin/bodytrack",
        "options": f"{BASE_BENCH_DIR}/apps/bodytrack/inputs/sequenceB_1 4 1 1000 5 0 8"
    },
    # Placeholder for Canneal - Update path/options if needed
    "canneal": {
        "cmd": f"{BASE_BENCH_DIR}/kernels/canneal/inst/amd64-linux.gcc/bin/canneal",
        "options": f"8 10000 2000 {BASE_BENCH_DIR}/kernels/canneal/inputs/100000.nets 32"
    }
}

def parse_remote_percentage(stats_file):
    """
    Parses stats.txt to calculate the percentage of remote data packets.
    Remote = Source Node ID != Destination Node ID
    """
    total_packets = 0
    remote_packets = 0
    
    # Regex to find lines like: system.ruby.network.data_traffic_distribution.n0.n1   161
    pattern = re.compile(r"system\.ruby\.network\.data_traffic_distribution\.n(\d+)\.n(\d+)\s+(\d+)")

    if not os.path.exists(stats_file):
        print(f"Error: Stats file {stats_file} not found.")
        return 0.0

    with open(stats_file, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                src_node = int(match.group(1))
                dst_node = int(match.group(2))
                count = int(match.group(3))

                total_packets += count
                if src_node != dst_node:
                    remote_packets += count

    if total_packets == 0:
        return 0.0
    
    return (remote_packets / total_packets) * 100.0

def run_simulation(bench_name, config):
    """Runs gem5 for a specific benchmark."""
    out_dir = f"m5out_{bench_name}"
    
    print(f"--- Running {bench_name} ---")
    
    cmd = [
        GEM5_BIN,
        "--outdir=" + out_dir, # Save output to specific directory so we don't overwrite
        CONFIG_SCRIPT
    ] + COMMON_PARAMS + [
        f"--cmd={config['cmd']}",
        f"--options={config['options']}"
    ]

    # Run the command
    # print("Executing:", " ".join(cmd)) # Uncomment to see full command
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Simulation failed for {bench_name}: {e}")
        return None

    return os.path.join(out_dir, "stats.txt")

def main():
    results = {}

    for name, config in benchmarks.items():
        stats_path = run_simulation(name, config)
        
        if stats_path:
            pct = parse_remote_percentage(stats_path)
            results[name] = pct
            print(f"Result for {name}: {pct:.2f}% remote accesses")

    # --- Plotting ---
    if results:
        names = list(results.keys())
        values = list(results.values())

        plt.figure(figsize=(10, 6))
        bars = plt.bar(names, values, color=['#1f77b4', '#ff7f0e', '#2ca02c'])
        
        plt.ylabel('Remote Data Packets (%)')
        plt.title('Percentage of Remote Data Accesses by Benchmark')
        plt.ylim(0, 100) # Percentages are 0-100

        # Add text labels on bars
        for bar in bars:
            yval = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2, yval + 1, f"{yval:.1f}%", ha='center', va='bottom')

        plt.savefig('remote_access_graph.png')
        print("Graph saved to remote_access_graph.png")
    else:
        print("No results to plot.")

if __name__ == "__main__":
    main()
import re
import os

def parse_gem5_traffic(file_path):
    # Initialize counters
    total_accesses = 0
    remote_accesses = 0
    
    # Regex pattern to match:
    # 1. The specific hierarchy path for data_traffic_distribution
    # 2. The Source Node ID (n<digits>)
    # 3. The Dest Node ID (n<digits>)
    # 4. The Value (integer count)
    # It ignores the rest of the line (comments/units)
    pattern = re.compile(r"board\.cache_hierarchy\.ruby_system\.network\.data_traffic_distribution\.n(\d+)\.n(\d+)\s+(\d+)")

    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found.")
        return

    print(f"Parsing {file_path}...")
    
    with open(file_path, 'r') as f:
        for line in f:
            # We only care about lines containing the distribution metric
            if "data_traffic_distribution" in line:
                match = pattern.search(line)
                if match:
                    src_node = int(match.group(1))
                    dst_node = int(match.group(2))
                    count = int(match.group(3))

                    # Sum up total
                    total_accesses += count

                    # Sum up remote (where source is not destination)
                    if src_node != dst_node:
                        remote_accesses += count

    # Calculate percentage
    if total_accesses > 0:
        percent_remote = (remote_accesses / total_accesses) * 100
    else:
        percent_remote = 0.0

    # Print Results
    print("-" * 30)
    print(f"Total Accesses:     {total_accesses:,}")
    print(f"Remote Accesses:    {remote_accesses:,}")
    print(f"Remote Percentage:  {percent_remote:.2f}%")
    print("-" * 30)

if __name__ == "__main__":
    # Change this if your file is named differently
    filename = "m5out/stats.txt" 
    parse_gem5_traffic(filename)
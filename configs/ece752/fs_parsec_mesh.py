import argparse
from gem5.utils.requires import requires
from gem5.components.boards.x86_board import X86Board
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.cachehierarchies.ruby.mesi_two_level_cache_hierarchy import MESITwoLevelCacheHierarchy
from gem5.components.memory.single_channel import SingleChannelDDR4_2400
from gem5.resources.resource import obtain_resource
from gem5.simulate.simulator import Simulator
from gem5.isas import ISA
from pathlib import Path

# --- Argument Parsing ---
parser = argparse.ArgumentParser(description="Run FS PARSEC from Checkpoint")
parser.add_argument("--command", type=str, required=True, help="The shell command to run inside the guest")
parser.add_argument("--checkpoint-path", type=str, required=True, help="Path to the checkpoint folder (e.g., m5out/cpt.1000)")
args = parser.parse_args()

# --- System Setup ---
requires(isa_required=ISA.X86)

# 1. Memory: Ruby MESI Two Level (Required for Mesh/Garnet simulation)
# This setup creates a cache hierarchy that supports the mesh topology.
cache_hierarchy = MESIThreeLevelCacheHierarchy(
    l1d_size="32kB",
    l1d_assoc=8,
    l1i_size="32kB",
    l1i_assoc=8,
    l2_size="256kB",
    l2_assoc=16,
    num_l2_banks=16,
    topology="Mesh"
)

# 2. Processor: 8 Cores, TimingSimple
# Using TimingSimple is faster than O3 but still provides memory timing stats.
processor = SimpleProcessor(
    cpu_type=CPUTypes.TIMING, 
    num_cores=16, 
    isa=ISA.X86
)

# 3. Memory: Instantiate the class directly (FIXED)
# The X86Board has a strict limit of 3GB due to the legacy I/O hole in the address map.
# UPDATE: Must be 2GB to match the checkpoint created by fs_hello_world.py
memory = SingleChannelDDR4_2400(size="2GB")

# 4. Board: X86
board = X86Board(
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
)

# 5. Set Workload: Restore from Checkpoint + Run Script
board.set_kernel_disk_workload(
    kernel=obtain_resource("x86-linux-kernel-5.4.0-105-generic"),
    disk_image=obtain_resource("x86-parsec"),
    readfile_contents=args.command,
    checkpoint=Path(args.checkpoint_path)
)

# 6. Run
print(f"Restoring from {args.checkpoint_path} and running command: {args.command}")
simulator = Simulator(board=board)
simulator.run()
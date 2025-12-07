from gem5.utils.requires import requires
from gem5.components.boards.x86_board import X86Board
from gem5.components.memory.single_channel import SingleChannelDDR3_1600
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.cachehierarchies.classic.private_l1_private_l2_cache_hierarchy import PrivateL1PrivateL2CacheHierarchy
from gem5.resources.resource import obtain_resource
from gem5.simulate.simulator import Simulator
from gem5.isas import ISA

# 1. Check for correct gem5 build
# We need the X86 ISA to run an X86 disk image
requires(isa_required=ISA.X86)

# 2. Setup the Memory System
# A simple 2GB DDR3 memory module
memory = SingleChannelDDR3_1600(size="2GB")

# 3. Setup the Cache Hierarchy
# Basic private L1 and L2 caches (Classic system)
cache_hierarchy = PrivateL1PrivateL2CacheHierarchy(
    l1d_size="16kB",
    l1i_size="16kB",
    l2_size="256kB"
)

# 4. Setup the Processor
# "ATOMIC" is the fastest functional simulation (good for booting).
# If you are on a Linux host, change CPUTypes.ATOMIC to CPUTypes.KVM 
# to boot in 10 seconds instead of 40 minutes.
processor = SimpleProcessor(
    cpu_type=CPUTypes.KVM, 
    num_cores=1, 
    isa=ISA.X86
)

# 5. Setup the Motherboard
# The X86Board class wires memory, processor, and cache together automatically.
board = X86Board(
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
)

# 6. Define the Workload (The "Software")
# obtain_resource will auto-download the files if you don't have them.
# "x86-ubuntu-18.04-boot" is a standard resource that boots Ubuntu and exits.
command = "m5 checkpoint; m5 exit;" # The command to run once the OS boots
board.set_kernel_disk_workload(
    kernel=obtain_resource("x86-linux-kernel-5.4.0-105-generic"),
    disk_image=obtain_resource("x86-ubuntu-18.04-img"),
    readfile_contents=command,
    kernel_args=["console=ttyS0", "root=/dev/sda1", "rw"]
)

# 7. Run the Simulation
print("Starting simulation... (This may take time to download resources first)")
simulator = Simulator(board=board)
simulator.run()

print("Simulation Finished!")
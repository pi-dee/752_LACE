from gem5.utils.requires import requires
from gem5.components.boards.x86_board import X86Board
from gem5.components.memory.single_channel import SingleChannelDDR4_2400
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.cachehierarchies.classic.no_cache import NoCache
from gem5.resources.resource import obtain_resource
from gem5.simulate.simulator import Simulator
from gem5.isas import ISA

requires(isa_required=ISA.X86)

# 1. Use KVM for instant booting
processor = SimpleProcessor(
    cpu_type=CPUTypes.KVM,
    num_cores=8,
    isa=ISA.X86
)

# 2. Use NoCache for maximum speed (we don't need accurate timing to list files)
board = X86Board(
    clk_freq="3GHz",
    processor=processor,
    memory=SingleChannelDDR4_2400(size="2GB"),
    cache_hierarchy=NoCache(),
)

# 3. The Search Command
# This will search for 'blackscholes' and print the full path to the terminal
search_command = "find / -name blackscholes; m5 exit;"

board.set_kernel_disk_workload(
    kernel=obtain_resource("x86-linux-kernel-5.4.0-105-generic"),
    disk_image=obtain_resource("x86-parsec"), # Using the PARSEC disk
    readfile_contents=search_command,
    kernel_args=["console=ttyS0", "root=/dev/sda1", "rw"]
)

print("Booting with KVM to search for files...")
simulator = Simulator(board=board)
simulator.run()
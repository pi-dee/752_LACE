import m5
from gem5.utils.requires import requires
from gem5.components.boards.x86_board import X86Board
from gem5.components.memory.single_channel import SingleChannelDDR4_2400
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.cachehierarchies.classic.no_cache import NoCache
from gem5.resources.resource import obtain_resource
from gem5.simulate.simulator import Simulator
from gem5.isas import ISA
from pathlib import Path

requires(isa_required=ISA.X86)

# 1. Use KVM for fast booting
processor = SimpleProcessor(
    cpu_type=CPUTypes.KVM, # <--- FAST BOOT
    num_cores=16,           # Must match your PARSEC run (8 cores)
    isa=ISA.X86
)

# 2. Setup Board (Must match your PARSEC memory size: 2GB)
board = X86Board(
    clk_freq="3GHz",
    processor=processor,
    memory=SingleChannelDDR4_2400(size="2GB"),
    cache_hierarchy=NoCache(),
)

# 3. The Magic Command
# - m5 exit: Stops the simulation so Python can save a checkpoint safely.
# - echo ...: When restored, the OS continues here.
# - m5 readfile | sh: Executes the NEW command provided by your PARSEC script.
setup_command = "m5 exit; echo 'Restored! Reading new command...'; m5 readfile | sh"

board.set_kernel_disk_workload(
    kernel=obtain_resource("x86-linux-kernel-5.4.0-105-generic"),
    # UPDATE: We must use the disk that actually has PARSEC installed!
    disk_image=obtain_resource("x86-parsec"),
    readfile_contents=setup_command,
    kernel_args=["console=ttyS0", "root=/dev/sda1", "rw"]
)

print("Booting with KVM to create reusable checkpoint...")
simulator = Simulator(board=board)
simulator.run()

# 4. Save the checkpoint manually after the boot finishes
print("System booted. Saving checkpoint...")
# Create a specific folder for the checkpoint so it is easy to find
checkpoint_dir = Path(m5.options.outdir) / "cpt.booted"
m5.checkpoint(str(checkpoint_dir))
print(f"Checkpoint saved successfully to {checkpoint_dir}")
# Copyright (c) 2016 Georgia Institute of Technology
# Modified for Real Traffic/SE Mode by Gemini

import argparse
import os
import sys
import shlex  # <--- Added for safe argument splitting

import m5
from m5.defines import buildEnv
from m5.objects import *
from m5.util import addToPath

# Add the common scripts to the path
addToPath("../")

from common import Options
from ruby import Ruby

# ------------------------------------------------------------------------------
# 1. Argument Parsing
# ------------------------------------------------------------------------------

parser = argparse.ArgumentParser()

Options.addCommonOptions(parser)
Options.addSEOptions(parser)
Ruby.define_options(parser)

args = parser.parse_args()

# ------------------------------------------------------------------------------
# 2. System Construction
# ------------------------------------------------------------------------------

system = System(
    mem_ranges=[AddrRange(args.mem_size)],
    cache_line_size=args.cacheline_size,
)

system.voltage_domain = VoltageDomain(voltage=args.sys_voltage)

system.clk_domain = SrcClockDomain(
    clock=args.sys_clock, voltage_domain=system.voltage_domain
)

# ------------------------------------------------------------------------------
# 3. CPU Setup
# ------------------------------------------------------------------------------

system.workload = SEWorkload.init_compatible(args.cmd)

# [A] Primary Process (Your Coherence Test)
# This will run on CPU 0.
primary_process = Process(pid=100)
primary_process.executable = args.cmd
primary_process.maxStackSize = '64MB'
# FIX: Combine the binary path with the user's --options flags
primary_process.cmd = [args.cmd] + shlex.split(args.options)

# [B] Dummy Process (Hello World)
# This runs on CPUs 1-7, exits, and leaves the CPUs ready to be stolen.
dummy_path = 'tests/test-progs/hello/bin/x86/linux/hello'

# specific check to ensure dummy binary exists
if not os.path.exists(dummy_path):
    print(f"Error: Dummy binary not found at {dummy_path}")
    print("Please compile it or point dummy_path to a valid small executable.")
    sys.exit(1)

dummy_process = Process(pid=200)
dummy_process.cmd = [dummy_path]
dummy_process.executable = dummy_path
dummy_process.maxStackSize = '64MB'

cpus = []
# Use the CPU type specified in args
CPUClass = getattr(m5.objects, args.cpu_type)

print(f"Creating {args.num_cpus} {args.cpu_type}...")

for i in range(args.num_cpus):
    cpu = CPUClass(clk_domain=system.clk_domain, cpu_id=i)
    cpu.createInterruptController()
    
    # [Workload Assignment]
    if i == 0:
        cpu.workload = primary_process
    else:
        cpu.workload = dummy_process
    
    cpu.createThreads()
    cpus.append(cpu)

system.cpu = cpus

# ------------------------------------------------------------------------------
# 4. Ruby and Garnet Configuration
# ------------------------------------------------------------------------------

# Pass the CPU list so Ruby knows how many ports to create
Ruby.create_system(args, False, system, cpus=system.cpu)

system.ruby.clk_domain = SrcClockDomain(
    clock=args.ruby_clock, voltage_domain=system.voltage_domain
)

# ------------------------------------------------------------------------------
# 5. Connect CPUs to Ruby
# ------------------------------------------------------------------------------

# Add X86 Interrupt/IO setup
if buildEnv.get('USE_X86_ISA', False):
    system.piobus = IOXBar()

for i, cpu in enumerate(system.cpu):
    # Ruby ports are created by create_system based on num_cpus
    ruby_port = system.ruby._cpu_ports[i]

    # Connect Cache Ports
    cpu.icache_port = ruby_port.in_ports
    cpu.dcache_port = ruby_port.in_ports

    # Connect Interrupt/IO Ports (Required for X86 SE to not crash on interrupts)
    if buildEnv.get('USE_X86_ISA', False):
        ruby_port.pio_request_port = system.piobus.cpu_side_ports
        cpu.interrupts[0].pio = system.piobus.mem_side_ports
        cpu.interrupts[0].int_responder = system.piobus.mem_side_ports
        cpu.interrupts[0].int_requestor = system.piobus.cpu_side_ports

# ------------------------------------------------------------------------------
# 6. Run Simulation
# ------------------------------------------------------------------------------

root = Root(full_system=False, system=system)
root.system.mem_mode = "timing"

m5.ticks.setGlobalFrequency("1ps")
m5.instantiate()

print(f"**** Starting simulation with binary: {args.cmd} ****")
print(f"**** Arguments: {primary_process.cmd} ****")

exit_event = m5.simulate(args.abs_max_tick)

print("Exiting @ tick", m5.curTick(), "because", exit_event.getCause())
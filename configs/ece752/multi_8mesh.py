# Copyright (c) 2016 Georgia Institute of Technology
# All rights reserved.
#
# Author: Tushar Krishna
# Modified for Real Traffic/SE Mode by Gemini

import argparse
import os
import sys

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
# 3. CPU Setup (Real Traffic Source)
# ------------------------------------------------------------------------------

# Initialize the System Workload
system.workload = SEWorkload.init_compatible(args.cmd)

# [A] Primary Process (Your Coherence Test)
# This will run on CPU 0 and spawn threads.
primary_process = Process(pid=100)
primary_process.cmd = [args.cmd]
primary_process.executable = args.cmd

# [B] Dummy Process (Hello World)
# This serves a specific purpose: It runs on CPUs 1-7, finishes quickly,
# and leaves the CPU in a "Halted" state. This allows CPU 0's pthread_create
# to "steal" these Halted CPUs for the new threads.
dummy_path = 'tests/test-progs/hello/bin/x86/linux/hello'
if not os.path.exists(dummy_path):
    print(f"Error: Dummy binary not found at {dummy_path}")
    sys.exit(1)

dummy_process = Process(pid=200)
dummy_process.cmd = [dummy_path]
dummy_process.executable = dummy_path

cpus = []
CPUClass = getattr(m5.objects, args.cpu_type)

print(f"Creating {args.num_cpus} {args.cpu_type}...")

for i in range(args.num_cpus):
    cpu = CPUClass(clk_domain=system.clk_domain, cpu_id=i)
    
    cpu.createInterruptController()
    
    # --- WORKLOAD ASSIGNMENT FIX ---
    if i == 0:
        # CPU 0 runs the real test
        cpu.workload = primary_process
    else:
        # CPUs 1-7 run the dummy process (exit -> Halt -> Available for clone)
        cpu.workload = dummy_process
    # -------------------------------
    
    cpu.createThreads()
    cpus.append(cpu)

system.cpu = cpus

# ------------------------------------------------------------------------------
# 4. Ruby and Garnet Configuration
# ------------------------------------------------------------------------------

Ruby.create_system(args, False, system, cpus=system.cpu)

system.ruby.clk_domain = SrcClockDomain(
    clock=args.ruby_clock, voltage_domain=system.voltage_domain
)

# ------------------------------------------------------------------------------
# 5. Connect CPUs to Ruby
# ------------------------------------------------------------------------------

if len(system.cpu) != len(system.ruby._cpu_ports):
    print(f"Error: CPU count ({len(system.cpu)}) does not match Ruby port count ({len(system.ruby._cpu_ports)})!")
    sys.exit(1)

if buildEnv.get('USE_X86_ISA', False):
    system.piobus = IOXBar()

for i, cpu in enumerate(system.cpu):
    ruby_port = system.ruby._cpu_ports[i]

    cpu.icache_port = ruby_port.in_ports
    cpu.dcache_port = ruby_port.in_ports

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

exit_event = m5.simulate(args.abs_max_tick)

print("Exiting @ tick", m5.curTick(), "because", exit_event.getCause())
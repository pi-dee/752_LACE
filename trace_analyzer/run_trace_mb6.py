# mb6_random.py
#
# MICROBENCHMARK #6 -> Single-thread Random Access (MB-RANDOM)
#
# C-side idea:
#   random_idx[]  : small index array (conceptually remote)
#   data_array[]  : large data array  (conceptually local)
#
#   for (round = 0; round < NUM_ROUNDS; ++round)
#     for (i = 0; i < NUM_ACCESSES; ++i) {
#         idx = random_idx[i];         // REMOTE read (index)
#         x   = data_array[idx];       // RANDOM local read
#         data_array[idx] = x * 3 + 7; // RANDOM local write
#     }
#
# We model only the memory accesses:
#   R random_idx[i]
#   R data_array[idx]
#   W data_array[idx]

import random
from typing import List

from core.trace_core import (
    Access,
    MeshConfig,
    CacheConfig,
    LatencyConfig,
    SimpleCacheConfig,
    TraceAnalyzer,
)

################################################################
# Trace generators
################################################################

def generate_mb6_random_trace(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,          # kept for API symmetry (unused here)
    core_id: int = 0,
    local_region_id: int = 0,
    remote_region_id: int = None,
    num_elems: int = 1 << 18,        # scaled: 256K elems  (vs 1<<20 in C)
    num_accesses: int = 1 << 19,     # scaled: 512K accesses (vs 1<<22 in C)
    num_rounds: int = 2,             # scaled: 2 rounds     (vs 4 in C)
    rng_seed: int = 1234,
) -> List[Access]:
    """
    Generate ONE MB6 trace (single-thread random gather/scatter).

    Defaults are a *scaled-down* version of the C kernel to keep the
    trace size manageable. If you really want the full C configuration,
    you can call this with:
        num_elems    = 1 << 20
        num_accesses = 1 << 22
        num_rounds   = 4
    but the trace will be very large.

    Layout (in terms of address regions):
      - random_idx[] lives contiguously in region 'remote_region_id'
      - data_array[] lives contiguously in region 'local_region_id'

    Under low-order-bit striping, the *actual* home node for each line
    is determined by MeshConfig.home_node(addr); these regions are just
    convenient, non-overlapping chunks of the address space.
    """

    region_size = mesh_cfg.region_size_bytes
    INT_SIZE    = 4

    # Choose a "remote" region: node farthest from the given core if not specified
    if remote_region_id is None:
        num_nodes = mesh_cfg.num_nodes()
        best_d = -1
        best_n = local_region_id
        for n in range(num_nodes):
            if n == local_region_id:
                continue
            d = mesh_cfg.manhattan_distance(core_id, n)
            if d > best_d:
                best_d = d
                best_n = n
        remote_region_id = best_n

    # ---------------- Physical layout (by region) ----------------
    #
    # region remote_region_id:
    #   [ random_idx[0 .. num_accesses-1] ]
    #
    # region local_region_id:
    #   [ data_array[0 .. num_elems-1] ]
    #
    base_random_idx = remote_region_id * region_size
    idx_bytes       = num_accesses * INT_SIZE
    assert base_random_idx + idx_bytes <= (remote_region_id + 1) * region_size

    base_data       = local_region_id * region_size
    data_bytes      = num_elems * INT_SIZE
    assert base_data + data_bytes <= (local_region_id + 1) * region_size

    # ---------------- Generate random indices ----------------
    #
    # This emulates the initialization of random_idx[i] in [0, num_elems).
    rng = random.Random(rng_seed)
    random_indices = [rng.randrange(num_elems) for _ in range(num_accesses)]

    # ---------------- Build the trace ----------------
    trace: List[Access] = []

    for _r in range(num_rounds):
        for i in range(num_accesses):
            idx = random_indices[i]

            # Address of random_idx[i] (conceptually REMOTE)
            addr_idx = base_random_idx + i * INT_SIZE
            trace.append(Access(addr=addr_idx, core=core_id, op='R'))

            # Address of data_array[idx] (conceptually LOCAL but random)
            addr_data = base_data + idx * INT_SIZE
            trace.append(Access(addr=addr_data, core=core_id, op='R'))
            trace.append(Access(addr=addr_data, core=core_id, op='W'))

    # Optional: checksum loop over data_array (reads only).
    # Uncomment if you want to model that:
    #
    # for i in range(num_elems):
    #     addr_data = base_data + i * INT_SIZE
    #     trace.append(Access(addr=addr_data, core=core_id, op='R'))

    return trace


def generate_mb6_random_traces(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    num_traces: int = 5,
    core_id: int = 0,
    local_region_id: int = 0,
    remote_region_id: int = None,
    num_elems: int = 1 << 18,
    num_accesses: int = 1 << 19,
    num_rounds: int = 2,
    base_seed: int = 1234,
) -> List[List[Access]]:
    """
    Generate multiple MB6 traces. Each one uses a different RNG seed
    so the random access pattern varies.
    """
    traces: List[List[Access]] = []
    for t in range(num_traces):
        trace = generate_mb6_random_trace(
            mesh_cfg=mesh_cfg,
            cache_cfg=cache_cfg,
            core_id=core_id,
            local_region_id=local_region_id,
            remote_region_id=remote_region_id,
            num_elems=num_elems,
            num_accesses=num_accesses,
            num_rounds=num_rounds,
            rng_seed=base_seed + t,
        )
        traces.append(trace)
    return traces


################################################################
# Runner / reporting
################################################################

def avg(key, stats_list):
    return sum(s[key] for s in stats_list) / len(stats_list)


if __name__ == "__main__":
    # --- Shared configs (same as other MBs) ---
    mesh_cfg  = MeshConfig(mesh_dim=4, region_size_bytes=1 << 30)

    # L2: 1MB, 64B lines, 4096 sets, 4-way
    l2_cfg    = CacheConfig(line_size=64, num_sets=4096, assoc=4)

    # L1: 4KB, 64B lines, direct-mapped
    l1_cfg    = SimpleCacheConfig(size_bytes=4*1024, line_size=64, assoc=1)

    lat_cfg   = LatencyConfig()
    analyzer  = TraceAnalyzer(mesh_cfg, l2_cfg, lat_cfg, rng_seed=42)

    print("Generating MB6-RANDOM traces")
    mb6_traces = generate_mb6_random_traces(
        mesh_cfg,
        l2_cfg,
        num_traces=10,
        core_id=0,
        local_region_id=0,
        remote_region_id=None,   # auto-choose far region
        num_elems=1 << 18,
        num_accesses=1 << 19,
        num_rounds=2,
        base_seed=1234,
    )

    belady_stats_list = []
    latopt_stats_list = []

    for idx, trace in enumerate(mb6_traces):
        costs = analyzer.compute_costs_for_trace(trace)

        print(f"Starting MB6 trace {idx+1}/{len(mb6_traces)}", flush=True)
        belady_stats = analyzer.belady_with_latency_and_breakdown(trace, costs, l1_cfg=l1_cfg)
        print("-Finished Belady")
        latopt_stats = analyzer.latency_optimal_with_hierarchy(trace, costs, l1_cfg=l1_cfg)
        print("-Finished CSOPT")

        belady_stats_list.append(belady_stats)
        latopt_stats_list.append(latopt_stats)

    print(f"\nMB6-RANDOM over {len(mb6_traces)} traces:")
    print("Belady avg_latency      :", avg("avg_latency", belady_stats_list))
    print("Lat-OPT avg_latency     :", avg("avg_latency", latopt_stats_list))
    print("Belady avg_L2_misses    :", avg("L2_misses", belady_stats_list))
    print("Lat-OPT avg_L2_misses   :", avg("L2_misses", latopt_stats_list))
    print("Belady avg_total_cost   :", avg("total_miss_cost", belady_stats_list))
    print("Lat-OPT avg_total_cost  :", avg("total_miss_cost", latopt_stats_list))

    last = belady_stats_list[-1]
    print("compulsory:", last["L2_compulsory_misses"])
    print("conflict  :", last["L2_conflict_misses"])
    print("capacity  :", last["L2_capacity_misses"])
    print("coherence :", last["L2_coherence_misses"])

#!/usr/bin/env python3

from typing import List

from trace_core import (
    MeshConfig,
    CacheConfig,
    LatencyConfig,
    SimpleCacheConfig,
    Access,
    TraceAnalyzer,
)


################################################################
# MICROBENCHMARK #8 -> TRANSPOSE (remote A, local B)
#
# Scaled-down transpose kernel:
#
#   A: remote matrix (homed on a far NUMA node / region)
#   B: local matrix (homed on the core's local region)
#
#   for round in [0..num_rounds):
#     for i in [0..n_rows):
#       for j in [0..n_cols):
#         x = A[i,j];    // remote read
#         B[j,i] = x;    // local write
#
# Default config is reduced (256x256, 2 rounds) to keep the
# trace + Lat-OPT DP runtime manageable.
################################################################


def _build_mb8_transpose_trace(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,          # kept for symmetry, not needed here
    n_rows: int = 256,
    n_cols: int = 256,
    num_rounds: int = 2,
    core_id: int = 0,
) -> List[Access]:
    """
    Build a single MB8 transpose trace.

    To emulate the heavier kernel, you can later call with:
        n_rows = 1 << 10
        n_cols = 1 << 10
        num_rounds = 4
    but the default is intentionally scaled down.
    """
    trace: List[Access] = []

    region_size = mesh_cfg.region_size_bytes
    num_nodes   = mesh_cfg.num_nodes()
    FLOAT_SIZE  = 4  # sizeof(float)

    # ---------------- NUMA-ish placement ----------------
    local_node = 0  # assume core_id is on node 0 for this microbench

    # Pick a "far" remote node for A (max Manhattan distance from core_id)
    max_d = -1
    remote_node = local_node
    for node in range(num_nodes):
        d = mesh_cfg.manhattan_distance(core_id, node)
        if d > max_d:
            max_d = d
            remote_node = node

    total_elems = n_rows * n_cols
    total_bytes = total_elems * FLOAT_SIZE

    # Layout:
    #   Region(remote_node): A matrix
    #   Region(local_node) : B matrix
    #
    base_A = remote_node * region_size
    base_B = local_node  * region_size

    assert base_A + total_bytes <= (remote_node + 1) * region_size, \
        "MB8: A matrix does not fit in remote node region"
    assert base_B + total_bytes <= (local_node  + 1) * region_size, \
        "MB8: B matrix does not fit in local node region"

    # ---------------- ROI: transpose loops ----------------
    #
    # For each round:
    #   for i in [0..n_rows):
    #     for j in [0..n_cols):
    #       R A[i,j]
    #       W B[j,i]
    #
    # A[i,j] row-major index: idx_A = i * n_cols + j
    # B[j,i] row-major index: idx_B = j * n_rows + i
    #
    for _r in range(num_rounds):
        for i in range(n_rows):
            row_base_A = i * n_cols
            for j in range(n_cols):
                idx_A = row_base_A + j
                idx_B = j * n_rows + i

                addr_A = base_A + idx_A * FLOAT_SIZE  # READ
                addr_B = base_B + idx_B * FLOAT_SIZE  # WRITE

                trace.append(Access(addr=addr_A, core=core_id, op='R'))
                trace.append(Access(addr=addr_B, core=core_id, op='W'))

    return trace


def generate_mb8_trace(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    n_rows: int = 256,
    n_cols: int = 256,
    num_rounds: int = 2,
    core_id: int = 0,
) -> List[Access]:
    """
    Generate ONE MB8 transpose trace (scaled-down by default).
    """
    return _build_mb8_transpose_trace(
        mesh_cfg=mesh_cfg,
        cache_cfg=cache_cfg,
        n_rows=n_rows,
        n_cols=n_cols,
        num_rounds=num_rounds,
        core_id=core_id,
    )


def generate_mb8_traces(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    num_traces: int = 5,
    n_rows: int = 256,
    n_cols: int = 256,
    num_rounds: int = 2,
    core_id: int = 0,
) -> List[List[Access]]:
    """
    Generate multiple MB8 traces.
    Currently deterministic; each trace is identical.
    """
    traces: List[List[Access]] = []
    for _ in range(num_traces):
        traces.append(
            generate_mb8_trace(
                mesh_cfg=mesh_cfg,
                cache_cfg=cache_cfg,
                n_rows=n_rows,
                n_cols=n_cols,
                num_rounds=num_rounds,
                core_id=core_id,
            )
        )
    return traces


def avg(key: str, stats_list):
    return sum(s[key] for s in stats_list) / len(stats_list)


def main():
    # ----------------- Global config (match other MB scripts) -----------------
    mesh_cfg = MeshConfig(mesh_dim=4, region_size_bytes=1 << 30)

    # L2: 1MB, 64B lines, 4096 sets, 4-way
    l2_cfg   = CacheConfig(line_size=64, num_sets=4096, assoc=4)

    # L1: 4KB, 64B lines, direct-mapped
    l1_cfg   = SimpleCacheConfig(size_bytes=4 * 1024, line_size=64, assoc=1)
    lat_cfg  = LatencyConfig()

    analyzer = TraceAnalyzer(mesh_cfg, l2_cfg, lat_cfg, rng_seed=42)

    # ----------------- Generate & run MB8 -----------------
    print("Generating MB8 traces")
    mb8_traces = generate_mb8_traces(
        mesh_cfg,
        l2_cfg,
        num_traces=5,
        n_rows=256,
        n_cols=256,
        num_rounds=2,
        core_id=0,
    )

    belady_stats_list = []
    latopt_stats_list = []

    for idx, trace in enumerate(mb8_traces):
        costs = analyzer.compute_costs_for_trace(trace)

        print(f"Starting MB8 trace {idx+1}/{len(mb8_traces)}", flush=True)
        belady_stats = analyzer.belady_with_latency_and_breakdown(trace, costs, l1_cfg=l1_cfg)
        print("-Finished Belady")
        latopt_stats = analyzer.latency_optimal_with_hierarchy(trace, costs, l1_cfg=l1_cfg)
        print("-Finished CSOPT")

        belady_stats_list.append(belady_stats)
        latopt_stats_list.append(latopt_stats)

    print(f"\nMB8 TRANSPOSE over {len(mb8_traces)} traces:")
    print("Belady avg_latency      :", avg("avg_latency", belady_stats_list))
    print("Lat-OPT avg_latency     :", avg("avg_latency", latopt_stats_list))
    print("Belady avg_L2_misses    :", avg("L2_misses", belady_stats_list))
    print("Lat-OPT avg_L2_misses   :", avg("L2_misses", latopt_stats_list))
    print("Belady avg_total_cost   :", avg("total_miss_cost", belady_stats_list))
    print("Lat-OPT avg_total_cost  :", avg("total_miss_cost", latopt_stats_list))

    belady_stats = belady_stats_list[-1]
    print("compulsory:", belady_stats["L2_compulsory_misses"])
    print("conflict  :", belady_stats["L2_conflict_misses"])
    print("capacity  :", belady_stats["L2_capacity_misses"])
    print("coherence :", belady_stats["L2_coherence_misses"])


if __name__ == "__main__":
    main()

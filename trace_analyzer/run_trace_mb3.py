# mb3_pipeline.py
#
# MICROBENCHMARK #3 -> 4-stage RMW pipeline across 4 nodes
#
# Conceptual C-side mapping:
#   Stage 0 (core0): priv0   -> buf01
#   Stage 1 (core1): buf01   -> priv1, buf12
#   Stage 2 (core2): buf12   -> priv2, buf23
#   Stage 3 (core3): buf23   -> priv3, buf_final
#
# We model just the ROI loads/stores, and repeat the whole
# 4-stage pipeline num_iters times.
#
# NOTE: With the new low-order-bit striping, the "regions"
# below are just disjoint address ranges. The actual home
# node for each line is determined by MeshConfig.home_node().

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
# Build pipeline sequences
################################################################

def _build_mb3_pipeline_sequences(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,            # kept for API symmetry
    num_total_entries: int = 1 << 17,  # e.g., 131,072 entries
    num_iters: int = 2,                # run the pipeline twice
    core0: int = 0,
    core1: int = 1,
    core2: int = 2,
    core3: int = 3,
) -> List[Access]:
    """
    Build a single global MB3 trace:
      [Stage0 over N] -> [Stage1 over N] -> [Stage2 over N] -> [Stage3 over N]
    repeated num_iters times.

    No flags or spin loops modeled, just the ROI memory references.
    """

    region_size = mesh_cfg.region_size_bytes
    INT_SIZE = 4
    N = num_total_entries
    bytes_per_array = N * INT_SIZE

    # Conceptual regions for each stage.
    # Under region-based NUMA they were actual nodes; now they are just
    # disjoint address ranges, and the analyzer decides home nodes via
    # low-order address bits.
    region0 = 0   # "stage 0 region"
    region1 = 1   # "stage 1 region"
    region2 = 5   # "stage 2 region"
    region3 = 6   # "stage 3 region"

    # Layout within each region:
    #
    # Region 0: [priv0][buf01]
    # Region 1: [priv1][buf12]
    # Region 2: [priv2][buf23]
    # Region 3: [priv3][buf_final]
    #
    base_priv0   = region0 * region_size
    base_buf01   = base_priv0 + bytes_per_array

    base_priv1   = region1 * region_size
    base_buf12   = base_priv1 + bytes_per_array

    base_priv2   = region2 * region_size
    base_buf23   = base_priv2 + bytes_per_array

    base_priv3   = region3 * region_size
    base_buf_fin = base_priv3 + bytes_per_array

    # Sanity checks: arrays fit within each region's address window
    assert base_priv0 + 2 * bytes_per_array <= (region0 + 1) * region_size
    assert base_priv1 + 2 * bytes_per_array <= (region1 + 1) * region_size
    assert base_priv2 + 2 * bytes_per_array <= (region2 + 1) * region_size
    assert base_priv3 + 2 * bytes_per_array <= (region3 + 1) * region_size

    trace: List[Access] = []

    for _it in range(num_iters):
        # ---------------- Stage 0 (core0, region0) ----------------
        # for i: x = priv0[i]; buf01[i] = x * 2 + 1;
        for i in range(N):
            addr_priv0 = base_priv0 + i * INT_SIZE
            addr_buf01 = base_buf01 + i * INT_SIZE

            # priv0[i] read
            trace.append(Access(addr=addr_priv0, core=core0, op='R'))
            # buf01[i] write
            trace.append(Access(addr=addr_buf01, core=core0, op='W'))

        # ---------------- Stage 1 (core1, region1) ----------------
        # for i:
        #   in  = buf01[i];
        #   acc = priv1[i];
        #   priv1[i] = acc + ...;
        #   buf12[i] = ...;
        for i in range(N):
            addr_buf01 = base_buf01 + i * INT_SIZE
            addr_priv1 = base_priv1 + i * INT_SIZE
            addr_buf12 = base_buf12 + i * INT_SIZE

            # read buf01[i]
            trace.append(Access(addr=addr_buf01, core=core1, op='R'))
            # LOCAL read priv1[i]
            trace.append(Access(addr=addr_priv1, core=core1, op='R'))
            # LOCAL write priv1[i]
            trace.append(Access(addr=addr_priv1, core=core1, op='W'))
            # LOCAL write buf12[i]
            trace.append(Access(addr=addr_buf12, core=core1, op='W'))

        # ---------------- Stage 2 (core2, region2) ----------------
        # for i:
        #   in  = buf12[i];
        #   acc = priv2[i];
        #   priv2[i] = acc ^ ...;
        #   buf23[i] = ...;
        for i in range(N):
            addr_buf12 = base_buf12 + i * INT_SIZE
            addr_priv2 = base_priv2 + i * INT_SIZE
            addr_buf23 = base_buf23 + i * INT_SIZE

            # read buf12[i]
            trace.append(Access(addr=addr_buf12, core=core2, op='R'))
            # LOCAL read priv2[i]
            trace.append(Access(addr=addr_priv2, core=core2, op='R'))
            # LOCAL write priv2[i]
            trace.append(Access(addr=addr_priv2, core=core2, op='W'))
            # LOCAL write buf23[i]
            trace.append(Access(addr=addr_buf23, core=core2, op='W'))

        # ---------------- Stage 3 (core3, region3) ----------------
        # for i:
        #   in  = buf23[i];
        #   prev = priv3[i];
        #   priv3[i] = prev + ...;
        #   buf_final[i] = out;
        for i in range(N):
            addr_buf23 = base_buf23 + i * INT_SIZE
            addr_priv3 = base_priv3 + i * INT_SIZE
            addr_final = base_buf_fin + i * INT_SIZE

            # read buf23[i]
            trace.append(Access(addr=addr_buf23, core=core3, op='R'))
            # LOCAL read priv3[i]
            trace.append(Access(addr=addr_priv3, core=core3, op='R'))
            # LOCAL write priv3[i]
            trace.append(Access(addr=addr_priv3, core=core3, op='W'))
            # LOCAL write buf_final[i]
            trace.append(Access(addr=addr_final, core=core3, op='W'))

    return trace


################################################################
# Public MB3 API
################################################################

def generate_mb3_trace(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    num_total_entries: int = 1 << 17,
    num_iters: int = 2,
    core0: int = 0,
    core1: int = 1,
    core2: int = 2,
    core3: int = 3,
) -> List[Access]:
    """
    Generate ONE MB3 global trace with num_iters full pipeline passes.
    """
    return _build_mb3_pipeline_sequences(
        mesh_cfg=mesh_cfg,
        cache_cfg=cache_cfg,
        num_total_entries=num_total_entries,
        num_iters=num_iters,
        core0=core0,
        core1=core1,
        core2=core2,
        core3=core3,
    )


def generate_mb3_traces(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    num_traces: int = 5,
    num_total_entries: int = 1 << 17,
    num_iters: int = 2,
    core0: int = 0,
    core1: int = 1,
    core2: int = 2,
    core3: int = 3,
) -> List[List[Access]]:
    traces: List[List[Access]] = []
    for _ in range(num_traces):
        traces.append(
            generate_mb3_trace(
                mesh_cfg=mesh_cfg,
                cache_cfg=cache_cfg,
                num_total_entries=num_total_entries,
                num_iters=num_iters,
                core0=core0,
                core1=core1,
                core2=core2,
                core3=core3,
            )
        )
    return traces


################################################################
# Runner / reporting (same format as other MBs)
################################################################

def avg(key, stats_list):
    return sum(s[key] for s in stats_list) / len(stats_list)


if __name__ == "__main__":
    # --- Shared configs (match MB1/MB2) ---
    mesh_cfg  = MeshConfig(mesh_dim=4, region_size_bytes=1 << 30)

    # L2: 1MB, 64B lines, 4096 sets, 4-way
    l2_cfg    = CacheConfig(line_size=64, num_sets=4096, assoc=4)

    # L1: 4KB, 64B lines, direct-mapped
    l1_cfg    = SimpleCacheConfig(size_bytes=4*1024, line_size=64, assoc=1)

    lat_cfg   = LatencyConfig()
    analyzer  = TraceAnalyzer(mesh_cfg, l2_cfg, lat_cfg, rng_seed=42)

    print("Generating MB3 traces")
    mb3_traces = generate_mb3_traces(
        mesh_cfg,
        l2_cfg,
        num_traces=10,
        num_total_entries=1 << 17,
        num_iters=2,
        core0=0,
        core1=1,
        core2=2,
        core3=3,
    )

    belady_stats_list = []
    latopt_stats_list = []

    for idx, trace in enumerate(mb3_traces):
        costs = analyzer.compute_costs_for_trace(trace)

        print(f"Starting MB3 trace {idx + 1}/{len(mb3_traces)}", flush=True)
        belady_stats = analyzer.belady_with_latency_and_breakdown(trace, costs, l1_cfg=l1_cfg)
        print("-Finished Belady")
        latopt_stats = analyzer.latency_optimal_with_hierarchy(trace, costs, l1_cfg=l1_cfg)
        print("-Finished CSOPT")

        belady_stats_list.append(belady_stats)
        latopt_stats_list.append(latopt_stats)

        print(f"Finished MB3 trace {idx + 1}/{len(mb3_traces)}", flush=True)

    print(f"\nMB3 PIPELINE over {len(mb3_traces)} traces:")
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

# mb5_hotset_mt.py
#
# MICROBENCHMARK #5 -> Multi-threaded hot-set conflict pattern
#
# - NUM_THREADS cores, all sharing a small hot set of lines.
# - K = num_hot_remote + num_hot_local lines, all forced into
#   the same L2 set (like MB4).
# - Each thread walks a skewed permutation of that same hot set
#   for num_rounds rounds, doing RMW (R+W) per access.
# - Conceptually "remote" lines live in far regions, "local" in region 0.
#   Actual home node comes from MeshConfig.home_node() (striping).
#
# This creates:
#   * many conflicts in one set (K > assoc),
#   * multi-core sharing / coherence traffic,
#   * cost differences between lines depending on NUMA distance.

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
# Helper: construct an address mapping to a specific L2 set
################################################################

def _make_line_addr_for_set(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    region_id: int,
    set_id: int,
    tag_offset: int,
) -> int:
    """
    Construct a physical address that:

      - Maps to L2 set 'set_id'
      - Uses an arbitrary tag chosen via 'tag_offset'
      - Lives in the region [region_id * region_size, (region_id+1)*region_size)

    Under low-order-bit striping, the *true* home node is determined
    by MeshConfig.home_node(addr). The region_id is just a convenient
    way to keep disjoint address groups for conceptual "local/remote"
    placements.
    """
    region_size = mesh_cfg.region_size_bytes
    line_size   = cache_cfg.line_size
    num_sets    = cache_cfg.num_sets

    # Choose a unique line index with given set and tag_offset
    line_index = tag_offset * num_sets + set_id

    # Place it within the chosen region
    addr = region_id * region_size + line_index * line_size
    return addr


################################################################
# MB5 trace generators
################################################################

def generate_mb5_trace(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    num_threads: int = 4,
    num_hot_remote: int = 4,
    num_hot_local: int = 2,
    num_rounds: int = 2000,
    core_ids: List[int] = None,
) -> List[Access]:
    """
    MB5: Multi-threaded hot-set conflict pattern.

    For each thread t:
      - Build a per-thread pattern over the *same* global hot-line set:
          [R0, L0, R1, L1, ..., R_{R-1}, L_{(R-1 mod L)}] (+ one extra local)
        then rotate by 't' positions to skew inter-thread ordering.
      - For each round, the global trace executes:
          T0's pattern, T1's pattern, ..., T_{num_threads-1}'s pattern
        with RMW (R,W) on each line.
    """
    if core_ids is None:
        core_ids = list(range(num_threads))
    assert len(core_ids) >= num_threads

    trace: List[Access] = []

    # Choose one "hot" L2 set (like MB4)
    hot_set = 0

    # --------- Choose "remote" regions based on far mesh nodes ---------
    num_nodes = mesh_cfg.num_nodes()
    distances = []
    # Use core 0 as the reference for "far"
    for node in range(num_nodes):
        d = mesh_cfg.manhattan_distance(core=0, home=node)
        distances.append((d, node))

    # Sort by distance descending, pick farthest non-zero nodes
    distances.sort(reverse=True)
    remote_regions: List[int] = []
    for _, node in distances:
        if node == 0:
            continue
        remote_regions.append(node)
        if len(remote_regions) >= max(1, num_hot_remote):
            break

    local_region = 0  # conceptual "local" region

    # --------- Build global set of hot line addresses ---------
    #
    # K = num_hot_remote + num_hot_local unique lines,
    # all mapped to the same L2 set 'hot_set'.
    #
    hot_remote_addrs: List[int] = []
    hot_local_addrs:  List[int] = []

    tag_offset = 0

    # Remote lines (spread over remote_regions)
    for i in range(num_hot_remote):
        region_id = remote_regions[i % len(remote_regions)]
        addr = _make_line_addr_for_set(
            mesh_cfg=mesh_cfg,
            cache_cfg=cache_cfg,
            region_id=region_id,
            set_id=hot_set,
            tag_offset=tag_offset,
        )
        hot_remote_addrs.append(addr)
        tag_offset += 1

    # Local lines (all within local_region)
    for _j in range(num_hot_local):
        addr = _make_line_addr_for_set(
            mesh_cfg=mesh_cfg,
            cache_cfg=cache_cfg,
            region_id=local_region,
            set_id=hot_set,
            tag_offset=tag_offset,
        )
        hot_local_addrs.append(addr)
        tag_offset += 1

    # Sanity: K > assoc => guaranteed conflicts in that set (recommended).
    # K = num_hot_remote + num_hot_local

    # --------- Build per-thread logical patterns (addresses only) ---------

    thread_patterns: List[List[int]] = []

    for tid in range(num_threads):
        pattern: List[int] = []

        # Base pattern: interleave remote + local, like the C++ version.
        for r in range(num_hot_remote):
            R_addr = hot_remote_addrs[r]
            L_addr = hot_local_addrs[r % max(1, num_hot_local)]
            pattern.append(R_addr)
            pattern.append(L_addr)

        # Extra local touch to bias locality for each thread.
        if num_hot_local > 0:
            extra_local = hot_local_addrs[tid % num_hot_local]
            pattern.append(extra_local)

        # Rotate pattern by 'tid' positions to skew ordering per thread.
        if pattern:
            shift = tid % len(pattern)
            rotated = [pattern[(i + shift) % len(pattern)] for i in range(len(pattern))]
            pattern = rotated

        thread_patterns.append(pattern)

    # --------- Build global trace over num_rounds ---------

    for _round in range(num_rounds):
        # Barrier effect: threads start each round together; we serialize
        # as [T0 pattern][T1 pattern]...[T_{n-1} pattern] in the global trace.
        for tid in range(num_threads):
            core = core_ids[tid]
            pattern = thread_patterns[tid]

            for addr in pattern:
                # RMW on this hot line
                trace.append(Access(addr=addr, core=core, op='R'))
                trace.append(Access(addr=addr, core=core, op='W'))

    return trace


def generate_mb5_traces(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    num_traces: int = 5,
    num_threads: int = 4,
    num_hot_remote: int = 4,
    num_hot_local: int = 2,
    num_rounds: int = 2000,
    core_ids: List[int] = None,
) -> List[List[Access]]:
    traces: List[List[Access]] = []
    for _ in range(num_traces):
        traces.append(
            generate_mb5_trace(
                mesh_cfg=mesh_cfg,
                cache_cfg=cache_cfg,
                num_threads=num_threads,
                num_hot_remote=num_hot_remote,
                num_hot_local=num_hot_local,
                num_rounds=num_rounds,
                core_ids=core_ids,
            )
        )
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

    print("Generating MB5 traces")
    mb5_traces = generate_mb5_traces(
        mesh_cfg,
        l2_cfg,
        num_traces=10,
        num_threads=4,
        num_hot_remote=4,
        num_hot_local=2,
        num_rounds=2000,
        core_ids=[0, 1, 2, 3],
    )

    belady_stats_list = []
    latopt_stats_list = []

    for idx, trace in enumerate(mb5_traces):
        costs = analyzer.compute_costs_for_trace(trace)

        print(f"Starting MB5 trace {idx + 1}/{len(mb5_traces)}", flush=True)
        belady_stats = analyzer.belady_with_latency_and_breakdown(trace, costs, l1_cfg=l1_cfg)
        print("-Finished Belady")
        latopt_stats = analyzer.latency_optimal_with_hierarchy(trace, costs, l1_cfg=l1_cfg)
        print("-Finished CSOPT")

        belady_stats_list.append(belady_stats)
        latopt_stats_list.append(latopt_stats)

        print(f"Finished MB5 trace {idx + 1}/{len(mb5_traces)}", flush=True)

    print(f"\nMB5 HOT-SET-MT over {len(mb5_traces)} traces:")
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

# mb4_hotset.py
#
# MICROBENCHMARK #4 -> Single-thread "hot-set conflict" pattern
#
# - Single core (core_id = 0)
# - A small set of lines (K > assoc) all mapping to the same L2 set
# - Some lines are "local", some "remote" (conceptually).
# - Access pattern induces frequent evictions in that set and mixes
#   cheaper vs more expensive misses.
#
# NOTE: Under the new low-order-bit striping in MeshConfig.home_node(),
# the node_id used below is effectively a "region id" (address range),
# and the *true* home node is decided by the analyzer's mapping. The
# code still builds a single hot set with K lines; remote/local cost
# differences come from the NUMA model in trace_core.

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

    Historically, 'region_id' also implied a specific NUMA home node
    (region-based mapping). With low-order-bit striping, the actual
    home node is determined by MeshConfig.home_node(), but we still
    keep disjoint regions to conceptually group "local" vs "remote"
    lines if desired.
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
# MB4 trace generators
################################################################

def generate_mb4_trace(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    core_id: int = 0,
    num_hot_remote: int = 4,   # number of conceptually remote lines
    num_hot_local: int = 2,    # number of conceptually local lines
    num_rounds: int = 2000,    # how many times to repeat the pattern
) -> List[Access]:
    """
    MB4: Single-thread conflict-heavy pattern in one L2 set.

    - All lines placed in the SAME L2 set (hot_set).
    - "Local" lines are placed in one region; "remote" lines in other regions.
    - Per-round pattern reuses local lines frequently, remote lines less
      frequently => lots of conflicts and cost / reuse trade-offs.
    """

    trace: List[Access] = []

    # Choose a "hot" L2 set (just pick 0 to keep it simple)
    hot_set = 0

    # Conceptual "local region" and "remote regions"
    # (address ranges; actual home nodes come from MeshConfig.home_node())
    local_region = 0

    num_nodes = mesh_cfg.num_nodes()
    # Use other region_ids to mimic "remote" placement
    remote_regions: List[int] = []
    # Pick region_ids that correspond to far-away nodes in the mesh
    distances = []
    for node in range(num_nodes):
        d = mesh_cfg.manhattan_distance(core_id, node)
        distances.append((d, node))
    distances.sort(reverse=True)

    for _, node in distances:
        if node != 0:
            remote_regions.append(node)
        if len(remote_regions) >= max(1, num_hot_remote):
            break

    # Construct addresses for hot remote lines
    hot_remote_addrs: List[int] = []
    tag_offset = 0
    for i in range(num_hot_remote):
        region_id = remote_regions[i % len(remote_regions)]
        addr = _make_line_addr_for_set(
            mesh_cfg, cache_cfg,
            region_id=region_id,
            set_id=hot_set,
            tag_offset=tag_offset,
        )
        hot_remote_addrs.append(addr)
        tag_offset += 1

    # Construct addresses for hot local lines
    hot_local_addrs: List[int] = []
    for _j in range(num_hot_local):
        addr = _make_line_addr_for_set(
            mesh_cfg, cache_cfg,
            region_id=local_region,
            set_id=hot_set,
            tag_offset=tag_offset,
        )
        hot_local_addrs.append(addr)
        tag_offset += 1

    # We now have K = num_hot_remote + num_hot_local lines in a single set.
    # If K > assoc (e.g., assoc=4, K=6), every round will cause evictions.

    # Per-round pattern:
    #
    #   H0, L0, H1, L1, H2, L0, H3, L1, ...
    #
    # Remote lines appear, then get some reuse later, but generally
    # have longer reuse distance than locals. Model each as R+W (RMW).
    pattern_addrs: List[int] = []
    for r in range(num_hot_remote):
        pattern_addrs.append(hot_remote_addrs[r])
        pattern_addrs.append(hot_local_addrs[r % num_hot_local])

    # Optional extra local touch to bias locality
    if num_hot_local > 0:
        pattern_addrs.append(hot_local_addrs[0])

    # Generate the full trace over many rounds
    for _ in range(num_rounds):
        for addr in pattern_addrs:
            # Read-modify-write style access
            trace.append(Access(addr=addr, core=core_id, op='R'))
            trace.append(Access(addr=addr, core=core_id, op='W'))

    return trace


def generate_mb4_traces(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    num_traces: int = 5,
    core_id: int = 0,
    num_hot_remote: int = 4,
    num_hot_local: int = 2,
    num_rounds: int = 2000,
) -> List[List[Access]]:
    traces: List[List[Access]] = []
    for _ in range(num_traces):
        traces.append(
            generate_mb4_trace(
                mesh_cfg=mesh_cfg,
                cache_cfg=cache_cfg,
                core_id=core_id,
                num_hot_remote=num_hot_remote,
                num_hot_local=num_hot_local,
                num_rounds=num_rounds,
            )
        )
    return traces


################################################################
# Runner / reporting
################################################################

def avg(key, stats_list):
    return sum(s[key] for s in stats_list) / len(stats_list)


if __name__ == "__main__":
    # --- Shared configs (same as MB1/MB2/MB3) ---
    mesh_cfg  = MeshConfig(mesh_dim=4, region_size_bytes=1 << 30)

    # L2: 1MB, 64B lines, 4096 sets, 4-way
    l2_cfg    = CacheConfig(line_size=64, num_sets=4096, assoc=4)

    # L1: 4KB, 64B lines, direct-mapped
    l1_cfg    = SimpleCacheConfig(size_bytes=4*1024, line_size=64, assoc=1)

    lat_cfg   = LatencyConfig()
    analyzer  = TraceAnalyzer(mesh_cfg, l2_cfg, lat_cfg, rng_seed=42)

    print("Generating MB4 traces")
    mb4_traces = generate_mb4_traces(
        mesh_cfg,
        l2_cfg,
        num_traces=10,
        core_id=0,
        num_hot_remote=4,
        num_hot_local=2,
        num_rounds=2000,
    )

    belady_stats_list = []
    latopt_stats_list = []

    for idx, trace in enumerate(mb4_traces):
        costs = analyzer.compute_costs_for_trace(trace)

        print(f"Starting MB4 trace {idx + 1}/{len(mb4_traces)}", flush=True)
        belady_stats = analyzer.belady_with_latency_and_breakdown(trace, costs, l1_cfg=l1_cfg)
        print("-Finished Belady")
        latopt_stats = analyzer.latency_optimal_with_hierarchy(trace, costs, l1_cfg=l1_cfg)
        print("-Finished CSOPT")

        belady_stats_list.append(belady_stats)
        latopt_stats_list.append(latopt_stats)

        print(f"Finished MB4 trace {idx + 1}/{len(mb4_traces)}", flush=True)

    print(f"\nMB4 HOT-SET over {len(mb4_traces)} traces:")
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

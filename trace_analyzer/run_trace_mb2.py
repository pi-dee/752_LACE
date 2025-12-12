# mb2_conv.py
#
# MICROBENCHMARK #2 -> Multi-Thread Convolution (ROI only, scaled)
#
# Producer (core 0) populates a shared buffer.
# Consumer (core 1) runs a multi-filter 1D convolution over that buffer,
# using private data and local filter weights.
#
# Global order (like ready_flag barrier):
#   [all producer accesses] then [all consumer accesses].

from typing import List, Tuple
from core.trace_core import (
    Access,
    MeshConfig,
    CacheConfig,
    LatencyConfig,
    SimpleCacheConfig,
    TraceAnalyzer,
)


################################################################
# Build producer/consumer sequences
################################################################

def _build_mb2_conv_roi_sequences(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,          # kept for API symmetry, not used directly
    num_total_entries: int = 1 << 17,   # 131,072 entries ≈ 512KB per array
    num_filters: int = 4,
    filter_radius: int = 4,
    producer_core: int = 0,
    consumer_core: int = 1,
) -> Tuple[List[Access], List[Access]]:
    """
    Return (producer_seq, consumer_seq) for MB2.

    Layout in (conceptual) regions:
      - "Producer region" holds:
          [prod_private][shared_buf]
      - "Consumer region" holds:
          [cons_private][filters][filter_outputs]
    NOTE: With the new low-order-bit striping, these "regions" are just
    disjoint address ranges; home-node selection is now done by the
    analyzer via MeshConfig.home_node(), not by region index.
    """

    region_size = mesh_cfg.region_size_bytes

    # Conceptual regions (not actual NUMA homes anymore)
    producer_region = 0
    consumer_region = 1

    INT_SIZE = 4
    N = num_total_entries
    total_bytes_array = N * INT_SIZE   # ~512KB per array

    filter_len = 2 * filter_radius + 1
    filters_bytes = num_filters * filter_len * INT_SIZE
    filter_outputs_bytes = num_filters * 8  # int64_t outputs

    # Producer region: [prod_private][shared_buf]
    base_prod_priv = producer_region * region_size
    base_shared    = base_prod_priv + total_bytes_array

    # Consumer region: [cons_private][filters][filter_outputs]
    base_cons_priv      = consumer_region * region_size
    base_filters        = base_cons_priv + total_bytes_array
    base_filter_outputs = base_filters + filters_bytes

    # Sanity checks (just to avoid overlapping address ranges)
    assert base_prod_priv + 2 * total_bytes_array <= (producer_region + 1) * region_size
    assert (base_filter_outputs + filter_outputs_bytes) <= (consumer_region + 1) * region_size

    prod_seq: List[Access] = []
    cons_seq: List[Access] = []

    # ------------------------------------------------------------
    # Producer ROI:
    #   shared_buf[i] = prod_private[i] * 2;
    #   → read prod_private[i], write shared_buf[i]
    # ------------------------------------------------------------
    for i in range(N):
        addr_priv   = base_prod_priv + i * INT_SIZE
        addr_shared = base_shared    + i * INT_SIZE

        prod_seq.append(Access(addr=addr_priv,   core=producer_core, op='R'))
        prod_seq.append(Access(addr=addr_shared, core=producer_core, op='W'))

    # ------------------------------------------------------------
    # Consumer ROI:
    #   Multi-filter conv over shared_buf, local filters, local cons_private.
    #
    # For each filter f:
    #   for i in [R .. N-R):
    #     for k in [-R .. R]:
    #       x = shared_buf[i+k];          // conceptually REMOTE earlier
    #       h = filters[f][k+R];          // local
    #     prev = cons_private[i];         // local
    #     cons_private[i] = prev + ...;   // local
    #   filter_outputs[f] = acc;          // local
    #
    # Finally:
    #   final_result += filter_outputs[f]; // local reads
    # ------------------------------------------------------------

    start = filter_radius
    end   = N - filter_radius   # i in [start, end)

    for f in range(num_filters):
        for i in range(start, end):
            # Inner window over shared_buf and filters
            for k in range(-filter_radius, filter_radius + 1):
                idx = i + k

                # x = shared_buf[idx];
                addr_x = base_shared + idx * INT_SIZE
                cons_seq.append(Access(addr=addr_x, core=consumer_core, op='R'))

                # h = filters[f][k+R];
                filt_idx = f * filter_len + (k + filter_radius)
                addr_h = base_filters + filt_idx * INT_SIZE
                cons_seq.append(Access(addr=addr_h, core=consumer_core, op='R'))

            # prev = cons_private[i];
            addr_priv = base_cons_priv + i * INT_SIZE
            cons_seq.append(Access(addr=addr_priv, core=consumer_core, op='R'))

            # cons_private[i] = prev + ...;
            cons_seq.append(Access(addr=addr_priv, core=consumer_core, op='W'))

        # filter_outputs[f] = acc;  (one write per filter)
        addr_out = base_filter_outputs + f * 8
        cons_seq.append(Access(addr=addr_out, core=consumer_core, op='W'))

    # final_result += filter_outputs[f];  (reads back filter outputs)
    for f in range(num_filters):
        addr_out = base_filter_outputs + f * 8
        cons_seq.append(Access(addr=addr_out, core=consumer_core, op='R'))

    return prod_seq, cons_seq


################################################################
# Public MB2 API
################################################################

def generate_mb2_trace(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    num_total_entries: int = 1 << 18,   # 262,144 entries
    num_filters: int = 3,
    filter_radius: int = 2,
    producer_core: int = 0,
    consumer_core: int = 1,
    rng_seed: int = 0,  # kept for API symmetry
) -> List[Access]:
    """
    Generate ONE MB2 global trace.

    Barrier semantics from ready_flag:
      producer completes its ROI loop, then consumer starts.
    So global order = [all producer accesses] then [all consumer accesses].
    """
    prod_seq, cons_seq = _build_mb2_conv_roi_sequences(
        mesh_cfg=mesh_cfg,
        cache_cfg=cache_cfg,
        num_total_entries=num_total_entries,
        num_filters=num_filters,
        filter_radius=filter_radius,
        producer_core=producer_core,
        consumer_core=consumer_core,
    )
    return prod_seq + cons_seq


def generate_mb2_traces(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    num_traces: int = 10,
    num_total_entries: int = 1 << 18,
    num_filters: int = 3,
    filter_radius: int = 2,
    producer_core: int = 0,
    consumer_core: int = 1,
    base_seed: int = 1234,
) -> List[List[Access]]:
    """
    Generate multiple MB2 traces.
    For now, the pattern is deterministic; rng_seed kept for symmetry.
    """
    traces: List[List[Access]] = []
    for t in range(num_traces):
        trace = generate_mb2_trace(
            mesh_cfg=mesh_cfg,
            cache_cfg=cache_cfg,
            num_total_entries=num_total_entries,
            num_filters=num_filters,
            filter_radius=filter_radius,
            producer_core=producer_core,
            consumer_core=consumer_core,
            rng_seed=base_seed + t,
        )
        traces.append(trace)
    return traces


################################################################
# Runner / reporting (same style as other MBs)
################################################################

def avg(key, stats_list):
    return sum(s[key] for s in stats_list) / len(stats_list)


if __name__ == "__main__":
    # --- Shared configs (match other MB scripts) ---
    mesh_cfg  = MeshConfig(mesh_dim=4, region_size_bytes=1 << 30)

    # L2: 1MB, 64B lines, 4096 sets, 4-way
    l2_cfg    = CacheConfig(line_size=64, num_sets=4096, assoc=4)

    # L1: 4KB, 64B lines, direct-mapped
    l1_cfg    = SimpleCacheConfig(size_bytes=4*1024, line_size=64, assoc=1)

    lat_cfg   = LatencyConfig()
    analyzer  = TraceAnalyzer(mesh_cfg, l2_cfg, lat_cfg, rng_seed=42)

    print("Generating MB2 traces")
    mb2_traces = generate_mb2_traces(
        mesh_cfg,
        l2_cfg,
        num_traces=10,
        num_total_entries=1 << 18,
        num_filters=3,
        filter_radius=2,
        producer_core=0,
        consumer_core=1,
    )

    belady_stats_list = []
    latopt_stats_list = []

    for idx, trace in enumerate(mb2_traces):
        costs = analyzer.compute_costs_for_trace(trace)

        print(f"Starting MB2 trace {idx + 1}/{len(mb2_traces)}", flush=True)
        belady_stats = analyzer.belady_with_latency_and_breakdown(trace, costs, l1_cfg=l1_cfg)
        print("-Finished Belady")
        latopt_stats = analyzer.latency_optimal_with_hierarchy(trace, costs, l1_cfg=l1_cfg)
        print("-Finished CSOPT")

        belady_stats_list.append(belady_stats)
        latopt_stats_list.append(latopt_stats)

        print(f"Finished MB2 trace {idx + 1}/{len(mb2_traces)}", flush=True)

    print(f"\nMB2-CONV (ROI, scaled) over {len(mb2_traces)} traces:")
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

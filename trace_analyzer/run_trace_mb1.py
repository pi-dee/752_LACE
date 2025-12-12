# mb1_sensor.py

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
# MICROBENCHMARK #1 -> Single-thread sensor-style pipeline
################################################################

def generate_mb1_trace(
    mesh_cfg: MeshConfig,
    local_region: int = 0,
    remote_region: int = 5,
    num_channels: int = 12,
    num_fields: int = 5,
    sample_rate: int = 64,
    sample_period: int = 1024,
    core_id: int = 0,
) -> List[Access]:
    """
    Synthetic trace for MB1:
      header_fields: remote (region = remote_region)
      sensor_data:   local  (region = local_region)
    """
    region = mesh_cfg.region_size_bytes

    header_base = remote_region * region   # header_fields[0]
    sensor_base = local_region  * region   # sensor_data[0]

    ENTRIES_PER_CHANNEL = sample_rate * sample_period
    INT_SIZE = 4

    trace: List[Access] = []

    for i in range(num_fields):
        addr_header = header_base + i * INT_SIZE
        trace.append(Access(addr=addr_header, core=core_id, op='R'))

        for j in range(num_channels):
            idx = j * ENTRIES_PER_CHANNEL

            addr_hdr_sensor = sensor_base + idx * INT_SIZE
            trace.append(Access(addr=addr_hdr_sensor, core=core_id, op='R'))
            trace.append(Access(addr=addr_hdr_sensor, core=core_id, op='W'))

            for k in range(1, ENTRIES_PER_CHANNEL):
                addr = sensor_base + (idx + k) * INT_SIZE
                trace.append(Access(addr=addr, core=core_id, op='R'))
                trace.append(Access(addr=addr, core=core_id, op='W'))

    return trace


def generate_mb1_traces(
    mesh_cfg: MeshConfig,
    local_region: int = 0,
    remote_region: int = 5,
    num_traces: int = 5,
) -> List[List[Access]]:
    traces: List[List[Access]] = []
    for _ in range(num_traces):
        traces.append(
            generate_mb1_trace(
                mesh_cfg=mesh_cfg,
                local_region=local_region,
                remote_region=remote_region,
            )
        )
    return traces


def avg(key, stats_list):
    return sum(s[key] for s in stats_list) / len(stats_list)


if __name__ == "__main__":
    # Configs
    mesh_cfg  = MeshConfig(mesh_dim=4, region_size_bytes=1 << 30)
    l2_cfg    = CacheConfig(line_size=64, num_sets=4096, assoc=4)
    l1_cfg    = SimpleCacheConfig(size_bytes=4*1024, line_size=64, assoc=1)
    lat_cfg   = LatencyConfig()
    analyzer  = TraceAnalyzer(mesh_cfg, l2_cfg, lat_cfg, rng_seed=42)

    print("Generating MB1 traces")
    mb1_traces = generate_mb1_traces(mesh_cfg, local_region=0, remote_region=5, num_traces=10)

    belady_stats_list = []
    latopt_stats_list = []

    for idx, trace in enumerate(mb1_traces):
        costs = analyzer.compute_costs_for_trace(trace)

        print(f"Starting MB1 trace {idx + 1}/{len(mb1_traces)}", flush=True)
        belady_stats = analyzer.belady_with_latency_and_breakdown(trace, costs, l1_cfg=l1_cfg)
        print("-Finished Belady")
        latopt_stats = analyzer.latency_optimal_with_hierarchy(trace, costs, l1_cfg=l1_cfg)
        print("-Finished CSOPT")

        belady_stats_list.append(belady_stats)
        latopt_stats_list.append(latopt_stats)

    print(f"\nMB1 SENSOR over {len(mb1_traces)} traces:")
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

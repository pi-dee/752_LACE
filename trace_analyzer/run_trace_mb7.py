# mb7_2dconv.py
#
# MICROBENCHMARK #7 -> 2D Convolution (NUMA-weight, local image)
#
# Conceptual C++ behavior (MB-2DCONV):
#   - input_img:   local to core/node
#   - kernel:      remote (weights homed on some far node)
#   - output_img:  local
#
# For each round:
#   for y, x over output pixels:
#       acc = 0
#       for ky, kx over kernel window:
#           w = kernel[ky, kx]              // REMOTE read
#           v = input_img[y+ky, x+kx]       // LOCAL read
#           acc += w * v
#       output_img[y, x] = acc              // LOCAL write

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
# Trace generator
################################################################

def _build_mb7_2dconv_trace(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,    # kept for symmetry (not needed here)
    img_h: int = 256,
    img_w: int = 256,
    kernel_h: int = 5,
    kernel_w: int = 5,
    num_rounds: int = 4,
    core_id: int = 0,
) -> List[Access]:
    """
    Build a single MB7 trace that models the ROI of the 2DConv kernel.

    Conceptual layout:
      - input_img:  lives in a "local" region (core_region_id)
      - output_img: lives in the same local region
      - kernel:     lives in a "remote" region (picked from a far node)

    Under low-order-bit striping, the actual *home node* for each line is
    determined by MeshConfig.home_node(addr); these regions are just
    disjoint address chunks so we don't overlap arrays.
    """
    trace: List[Access] = []

    region_size = mesh_cfg.region_size_bytes
    num_nodes   = mesh_cfg.num_nodes()
    INT_SIZE    = 4

    pad_h = kernel_h // 2
    pad_w = kernel_w // 2

    padded_h = img_h + 2 * pad_h
    padded_w = img_w + 2 * pad_w

    # ---------------- Placement ----------------
    # Region "local" for this core (assume region 0 for core 0).
    core_region_id = 0

    # Find a numerically "far" node to choose a remote region for the kernel.
    # (Distance is only used to pick which region_id to base the kernel in.)
    distances = []
    for node in range(num_nodes):
        d = mesh_cfg.manhattan_distance(core_id, node)
        distances.append((d, node))
    distances.sort(reverse=True)

    remote_region_id = core_region_id
    for _d, node in distances:
        if node != core_region_id:
            remote_region_id = node
            break

    # ---- Local region (input + output) ----
    bytes_input  = padded_h * padded_w * INT_SIZE
    bytes_output = img_h * img_w * INT_SIZE

    base_input  = core_region_id * region_size
    base_output = base_input + bytes_input

    assert base_output + bytes_output <= (core_region_id + 1) * region_size, \
        "MB7: input + output exceed local region; shrink image or region_size."

    # ---- Remote region (kernel) ----
    bytes_kernel = kernel_h * kernel_w * INT_SIZE
    base_kernel  = remote_region_id * region_size

    assert base_kernel + bytes_kernel <= (remote_region_id + 1) * region_size, \
        "MB7: kernel exceeds remote region_size; adjust config."

    # ---------------- Trace generation ----------------
    #
    # For each round:
    #   for y in [0..img_h-1], x in [0..img_w-1]:
    #     for ky, kx:
    #        R kernel[ky, kx]           (remote-region read)
    #        R input_img[y+ky, x+kx]    (local-region read, padded)
    #     W output_img[y, x]
    #
    for _r in range(num_rounds):
        for y in range(img_h):
            for x in range(img_w):
                # Inner kernel window
                for ky in range(kernel_h):
                    in_y = y + ky  # using padded coordinates; pad is baked into base_input
                    for kx in range(kernel_w):
                        in_x = x + kx

                        # kernel[ky, kx] -> remote read
                        w_index = ky * kernel_w + kx
                        addr_w  = base_kernel + w_index * INT_SIZE
                        trace.append(Access(addr=addr_w, core=core_id, op='R'))

                        # input_img[in_y, in_x] -> local read
                        in_index = in_y * padded_w + in_x
                        addr_in  = base_input + in_index * INT_SIZE
                        trace.append(Access(addr=addr_in, core=core_id, op='R'))

                # output_img[y, x] -> local write
                out_index = y * img_w + x
                addr_out  = base_output + out_index * INT_SIZE
                trace.append(Access(addr=addr_out, core=core_id, op='W'))

    return trace


def generate_mb7_trace(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    img_h: int = 256,
    img_w: int = 256,
    kernel_h: int = 5,
    kernel_w: int = 5,
    num_rounds: int = 4,
    core_id: int = 0,
) -> List[Access]:
    """
    Convenience wrapper for one MB7 trace.
    """
    return _build_mb7_2dconv_trace(
        mesh_cfg=mesh_cfg,
        cache_cfg=cache_cfg,
        img_h=img_h,
        img_w=img_w,
        kernel_h=kernel_h,
        kernel_w=kernel_w,
        num_rounds=num_rounds,
        core_id=core_id,
    )


def generate_mb7_traces(
    mesh_cfg: MeshConfig,
    cache_cfg: CacheConfig,
    num_traces: int = 5,
    img_h: int = 256,
    img_w: int = 256,
    kernel_h: int = 5,
    kernel_w: int = 5,
    num_rounds: int = 4,
    core_id: int = 0,
) -> List[List[Access]]:
    """
    Generate multiple identical MB7 traces (deterministic access pattern).
    """
    traces: List[List[Access]] = []
    for _ in range(num_traces):
        traces.append(
            generate_mb7_trace(
                mesh_cfg=mesh_cfg,
                cache_cfg=cache_cfg,
                img_h=img_h,
                img_w=img_w,
                kernel_h=kernel_h,
                kernel_w=kernel_w,
                num_rounds=num_rounds,
                core_id=core_id,
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
    l1_cfg    = SimpleCacheConfig(size_bytes=4 * 1024, line_size=64, assoc=1)

    lat_cfg   = LatencyConfig()
    analyzer  = TraceAnalyzer(mesh_cfg, l2_cfg, lat_cfg, rng_seed=42)

    print("Generating MB7 traces")
    mb7_traces = generate_mb7_traces(
        mesh_cfg,
        l2_cfg,
        num_traces=5,
        img_h=256,
        img_w=256,
        kernel_h=5,
        kernel_w=5,
        num_rounds=4,
        core_id=0,
    )

    belady_stats_list = []
    latopt_stats_list = []

    for idx, trace in enumerate(mb7_traces):
        costs = analyzer.compute_costs_for_trace(trace)

        print(f"Starting MB7 trace {idx+1}/{len(mb7_traces)}", flush=True)
        belady_stats = analyzer.belady_with_latency_and_breakdown(trace, costs, l1_cfg=l1_cfg)
        print("-Finished Belady")
        latopt_stats = analyzer.latency_optimal_with_hierarchy(trace, costs, l1_cfg=l1_cfg)
        print("-Finished CSOPT")

        belady_stats_list.append(belady_stats)
        latopt_stats_list.append(latopt_stats)

    print(f"\nMB7 2DCONV over {len(mb7_traces)} traces:")
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

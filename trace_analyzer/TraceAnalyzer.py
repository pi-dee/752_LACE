from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import random
import math
import functools
import sys



# ----------------- Basic data structures -----------------

@dataclass
class Access:
    """One memory access in the global order."""
    addr: int        # physical byte address
    core: int        # requesting core id (0 .. num_cores-1)
    op: str          # 'R' or 'W' (read or write)

@dataclass
class MeshConfig:
    mesh_dim: int          # N for NxN mesh. Assume num_cores == N*N
    region_size_bytes: int # size of contiguous physical region per home node, e.g. 1 << 30

    def num_nodes(self) -> int:
        return self.mesh_dim * self.mesh_dim

    def core_coord(self, core: int) -> Tuple[int, int]:
        """Map core id to (x,y) coords in the mesh."""
        N = self.mesh_dim
        return (core % N, core // N)

    def home_node(self, addr: int) -> int:
        """Home node id for a physical address."""
        node = (addr // self.region_size_bytes) % self.num_nodes()
        return node

    def node_coord(self, node: int) -> Tuple[int, int]:
        """Map node id to (x,y)."""
        N = self.mesh_dim
        return (node % N, node // N)

    def manhattan_distance(self, core: int, home: int) -> int:
        cx, cy = self.core_coord(core)
        hx, hy = self.node_coord(home)
        return abs(cx - hx) + abs(cy - hy)

@dataclass
class CacheConfig:
    line_size: int          # bytes, e.g. 64
    num_sets: int           # e.g. 4096
    assoc: int              # e.g. 8

    def set_and_tag(self, addr: int) -> Tuple[int, int]:
        line = addr // self.line_size
        s = line % self.num_sets
        t = line // self.num_sets
        return s, t

@dataclass
class LatencyConfig:
    # L1 + L2 hit latencies
    l1_hit_latency: int = 1        # cycles for L1 hit
    l2_hit_latency: int = 4       # cycles for L2 hit (after L1 miss)

    # Base memory costs (for L2 misses)
    base_mem_latency: int = 100    # cycles for 0-hop local DRAM access
    per_hop_latency: int = 10      # extra cycles per mesh hop

    # Coherence penalties (extra cycles)
    penalty_shared_miss: int = 5     # I→S (cold miss)
    penalty_shared_remote: int = 10   # S miss bringing from remote cache / DRAM
    penalty_modified: int = 30        # M→S or M→M transfer
    penalty_write_inval_per_sharer: int = 2

    # Random noise
    noise_factor_min: float = 0.75
    noise_factor_max: float = 1.25

@dataclass
class DirEntry:
    state: str                    # 'I', 'S', or 'M'
    owner: Optional[int] = None   # core id if state=='M'
    sharers: Optional[set] = None # cores if state=='S' (or for debugging)

# Simple cache config for L1 (direct-mapped or set-assoc)
@dataclass
class SimpleCacheConfig:
    size_bytes: int
    line_size: int
    assoc: int  # use 1 for direct-mapped

    @property
    def num_lines(self) -> int:
        return self.size_bytes // self.line_size

    @property
    def num_sets(self) -> int:
        return self.num_lines // self.assoc

# ----------------- Trace Analyzer -----------------

class TraceAnalyzer:
    def __init__(
        self,
        mesh_cfg: MeshConfig,
        cache_cfg: CacheConfig,   # L2 config
        lat_cfg: LatencyConfig,
        rng_seed: int = 0,
    ):
        self.mesh = mesh_cfg
        self.cache = cache_cfg
        self.lat = lat_cfg
        self.rng = random.Random(rng_seed)


    def _home_node_low_order(self, addr: int) -> int:
        """
        Low-order interleaving across NUMA nodes / LLC slices.

        - Compute the cache line index = addr / line_size
        - Home node = line_index mod num_nodes

        This ignores region_size_bytes and your old region-based mapping.
        """
        line_index = addr // self.cache.line_size
        return line_index % self.mesh.num_nodes()

    # ---------- Coherence + NUMA cost model (for L2 miss → memory) ----------

    def _compute_single_access_cost(
        self,
        access: Access,
        dir_entry: DirEntry,
    ) -> int:
        """
        Compute cost *if this access goes to home node*, given current dir state.
        Does NOT update the directory; caller will update after computing cost.
        """
        # Distance-based base latency using low-order striped mapping
        home = self._home_node_low_order(access.addr)
        hops = self.mesh.manhattan_distance(access.core, home)
        base = self.lat.base_mem_latency + hops * self.lat.per_hop_latency


        coh_extra = 0
        op = access.op

        if dir_entry.state == 'I':
            # Cold miss: bring from DRAM (or remote memory)
            coh_extra += self.lat.penalty_shared_miss

        elif dir_entry.state == 'S':
            if op == 'R':
                # Another reader; may come from remote cache or memory
                coh_extra += self.lat.penalty_shared_remote
            else:  # 'W' upgrade from S → M; invalidate sharers
                num_sharers = len(dir_entry.sharers) if dir_entry.sharers else 0
                coh_extra += self.lat.penalty_write_inval_per_sharer * max(0, num_sharers - 1)

        elif dir_entry.state == 'M':
            if dir_entry.owner == access.core:
                # Owner hits its own modified line (in reality, cache hit)
                coh_extra += 0
            else:
                # Another core touching a modified block
                coh_extra += self.lat.penalty_modified

        # Random traffic noise factor
        noise = self.rng.uniform(self.lat.noise_factor_min, self.lat.noise_factor_max)
        cost = int(round((base + coh_extra) * noise))
        return max(cost, 1)

    def _update_directory(self, access: Access, dir_entry: DirEntry) -> None:
        """
        Update directory entry state based on this access.
        Very simplified MESI-like behavior.
        """
        op = access.op
        c = access.core

        if dir_entry.state == 'I':
            if op == 'R':
                dir_entry.state = 'S'
                dir_entry.sharers = {c}
                dir_entry.owner = None
            else:  # W
                dir_entry.state = 'M'
                dir_entry.owner = c
                dir_entry.sharers = None

        elif dir_entry.state == 'S':
            if op == 'R':
                if dir_entry.sharers is None:
                    dir_entry.sharers = set()
                dir_entry.sharers.add(c)
            else:  # W: upgrade to M, invalidating others
                dir_entry.state = 'M'
                dir_entry.owner = c
                dir_entry.sharers = None

        elif dir_entry.state == 'M':
            if dir_entry.owner == c:
                # Owner keeps it modified
                pass
            else:
                # Another core accesses; simplify: writer-wins
                if op == 'R':
                    # downgrade to S shared between owner and reader
                    dir_entry.state = 'S'
                    dir_entry.sharers = {dir_entry.owner, c} if dir_entry.owner is not None else {c}
                    dir_entry.owner = None
                else:
                    # new writer takes ownership
                    dir_entry.state = 'M'
                    dir_entry.owner = c
                    dir_entry.sharers = None

    def compute_costs_for_trace(self, trace: List[Access]) -> List[int]:
        """
        First pass: for each access in the trace, compute the latency cost if
        it misses at L2 and must go to the home node, using the NUMA + coherence
        model. Also evolves directory state over time.
        """
        dir_table: Dict[int, DirEntry] = {}
        costs: List[int] = []

        for acc in trace:
            line_addr = acc.addr // self.cache.line_size

            entry = dir_table.get(line_addr)
            if entry is None:
                entry = DirEntry(state='I', owner=None, sharers=None)
                dir_table[line_addr] = entry

            cost = self._compute_single_access_cost(acc, entry)
            costs.append(cost)

            # Now update directory state
            self._update_directory(acc, entry)

        return costs

    # ---------- L1 simulation for hierarchy ----------

    def _simulate_l1_and_build_l2_stream(
        self,
        trace: List[Access],
        l1_cfg: SimpleCacheConfig,
    ):
        """
        Simulate L1 with LRU within each set.
        Returns:
          - l1_hits, l1_misses
          - l1_miss_bitmap[i]: True if access i missed in L1
          - l2_trace: List[Access] that reach L2 (i.e., L1 misses)
          - l2_orig_index: mapping from L2 index k -> original index i
          - l2_index_of: length-n list mapping original index i -> L2 index k or None
        """
        num_sets = l1_cfg.num_sets
        line_size = l1_cfg.line_size
        assoc = l1_cfg.assoc

        # Per-set LRU: list of tags [MRU..LRU]
        l1_sets: List[List[int]] = [[] for _ in range(num_sets)]

        n = len(trace)
        l1_miss_bitmap = [False] * n
        l2_trace: List[Access] = []
        l2_orig_index: List[int] = []
        l2_index_of: List[Optional[int]] = [None] * n

        l1_hits = 0
        l1_misses = 0
        l2_idx = 0

        for i, acc in enumerate(trace):
            line = acc.addr // line_size
            s = line % num_sets
            t = line // num_sets

            ways = l1_sets[s]
            if t in ways:
                # L1 hit
                l1_hits += 1
                ways.remove(t)
                ways.insert(0, t)  # MRU
                l1_miss_bitmap[i] = False
            else:
                # L1 miss
                l1_misses += 1
                l1_miss_bitmap[i] = True

                # Update L1 replacement state
                if len(ways) < assoc:
                    ways.insert(0, t)
                else:
                    ways.pop()
                    ways.insert(0, t)

                # This access goes to L2
                l2_trace.append(acc)
                l2_orig_index.append(i)
                l2_index_of[i] = l2_idx
                l2_idx += 1

        return l1_hits, l1_misses, l1_miss_bitmap, l2_trace, l2_orig_index, l2_index_of

    # ---------- Belady helpers (used on L2 stream only) ----------

    def _belady_hit_bitmap(self, trace: List[Access], cache_cfg: CacheConfig) -> List[bool]:
        """
        Run Belady on given cache_cfg and return a list hit_bitmap[k]: True if L2 access k is a hit.
        """
        n = len(trace)
        sets = [0] * n
        tags = [0] * n

        for i, acc in enumerate(trace):
            s, t = cache_cfg.set_and_tag(acc.addr)
            sets[i] = s
            tags[i] = t

        next_use = [math.inf] * n
        last_pos: Dict[Tuple[int, int], int] = {}

        for i in range(n - 1, -1, -1):
            key = (sets[i], tags[i])
            next_use[i] = last_pos.get(key, math.inf)
            last_pos[key] = i

        per_set_cache: List[Dict[int, float]] = [dict() for _ in range(cache_cfg.num_sets)]
        hit_bitmap = [False] * n

        for i in range(n):
            s = sets[i]
            t = tags[i]
            nu = next_use[i]
            set_cache = per_set_cache[s]

            if t in set_cache:
                hit_bitmap[i] = True
                set_cache[t] = nu
            else:
                hit_bitmap[i] = False
                if len(set_cache) < cache_cfg.assoc:
                    set_cache[t] = nu
                else:
                    victim_tag, _ = max(set_cache.items(), key=lambda kv: kv[1])
                    del set_cache[victim_tag]
                    set_cache[t] = nu

        return hit_bitmap

        # ---------- Latency-optimal oracle per set (DP + path reconstruction) ----------
    def _latopt_solve_set(
        self,
        block_ids: List[int],     # X_s[k]: line id for k-th access in this set
        miss_costs: List[int],    # C_s[k]: miss cost if that access is a miss
        assoc: int,
    ) -> Tuple[int, int, List[bool]]:
        """
        Exact latency-optimal oracle for ONE set, using *iterative* DP.

        Returns:
            (total_miss_cost, total_miss_count, miss_bitmap_s)

        miss_bitmap_s[k] == True  iff the k-th access in this set is a miss
        under the cost-optimal policy.

        This version does *not* use recursion, so it won't hit Python's
        recursion limit even for long per-set streams.
        """
        X = block_ids
        C = miss_costs
        L = len(X)

        if L == 0:
            return 0, 0, []

        # tables[t][state_fro] = (cost_up_to_t, misses_up_to_t, prev_state_fro)
        tables: List[Dict[frozenset, Tuple[int, int, Optional[frozenset]]]] = []

        # At "time" -1, before any access, cache is empty with cost 0
        dp_prev: Dict[frozenset, Tuple[int, int, Optional[frozenset]]] = {
            frozenset(): (0, 0, None)
        }

        for t in range(L):
            b = X[t]
            dp_cur: Dict[frozenset, Tuple[int, int, Optional[frozenset]]] = {}

            for state_fro, (cost_prev, misses_prev, _prev_dummy) in dp_prev.items():
                state = set(state_fro)

                # Case 1: HIT (b already in cache)
                if b in state:
                    new_state_fro = state_fro
                    cost_new = cost_prev
                    misses_new = misses_prev

                    old = dp_cur.get(new_state_fro)
                    if (old is None or
                        cost_new < old[0] or
                        (cost_new == old[0] and misses_new < old[1])):
                        dp_cur[new_state_fro] = (cost_new, misses_new, state_fro)

                else:
                    # Case 2: MISS
                    miss_cost = C[t]
                    cost_new = cost_prev + miss_cost
                    misses_new = misses_prev + 1

                    # 2a: free way available
                    if len(state) < assoc:
                        new_state = set(state)
                        new_state.add(b)
                        new_state_fro = frozenset(new_state)

                        old = dp_cur.get(new_state_fro)
                        if (old is None or
                            cost_new < old[0] or
                            (cost_new == old[0] and misses_new < old[1])):
                            dp_cur[new_state_fro] = (cost_new, misses_new, state_fro)

                    # 2b: cache full, try all victims
                    else:
                        for victim in state:
                            new_state = set(state)
                            new_state.remove(victim)
                            new_state.add(b)
                            new_state_fro = frozenset(new_state)

                            old = dp_cur.get(new_state_fro)
                            if (old is None or
                                cost_new < old[0] or
                                (cost_new == old[0] and misses_new < old[1])):
                                dp_cur[new_state_fro] = (cost_new, misses_new, state_fro)

            tables.append(dp_cur)
            dp_prev = dp_cur

        # Choose the best final state at t = L-1
        last_table = tables[-1]
        best_state: Optional[frozenset] = None
        best_cost = math.inf
        best_misses = math.inf

        for state_fro, (cost, misses, _prev_state) in last_table.items():
            if (cost < best_cost or
                (cost == best_cost and misses < best_misses)):
                best_cost = cost
                best_misses = misses
                best_state = state_fro

        assert best_state is not None

        total_cost = best_cost
        total_misses = best_misses

        # Reconstruct miss bitmap by walking backward
        miss_bitmap = [False] * L
        state_after = best_state

        for t in range(L - 1, -1, -1):
            table = tables[t]
            cost_t, misses_t, prev_state = table[state_after]
            b = X[t]

            prev_set = set() if prev_state is None else set(prev_state)
            # If b was in prev_set, then this access was a hit; otherwise a miss.
            miss_bitmap[t] = (b not in prev_set)

            state_after = prev_state if prev_state is not None else frozenset()

        return total_cost, total_misses, miss_bitmap






# ---------- Original simple Belady-on-full-trace (kept) ----------

    def belady_with_latency(
        self,
        trace: List[Access],
        costs: List[int],
    ) -> Dict[str, float]:
        """
        Run Belady's OPT for the L2 cache directly on the full trace (ignoring L1).
        """
        assert len(trace) == len(costs)
        n = len(trace)
        cache = self.cache

        sets: List[int] = [0] * n
        tags: List[int] = [0] * n
        for i, acc in enumerate(trace):
            s, t = cache.set_and_tag(acc.addr)
            sets[i] = s
            tags[i] = t

        next_use = [math.inf] * n
        last_pos: Dict[Tuple[int, int], int] = {}

        for i in range(n - 1, -1, -1):
            key = (sets[i], tags[i])
            next_use[i] = last_pos.get(key, math.inf)
            last_pos[key] = i

        per_set_cache: List[Dict[int, float]] = [dict() for _ in range(cache.num_sets)]

        miss_count = 0
        total_latency = 0

        for i in range(n):
            s = sets[i]
            t = tags[i]
            nu = next_use[i]
            set_cache = per_set_cache[s]

            if t in set_cache:
                total_latency += self.lat.l2_hit_latency
                set_cache[t] = nu
            else:
                miss_count += 1
                total_latency += costs[i]

                if len(set_cache) < cache.assoc:
                    set_cache[t] = nu
                else:
                    victim_tag, _ = max(set_cache.items(), key=lambda kv: kv[1])
                    del set_cache[victim_tag]
                    set_cache[t] = nu

        avg_latency = total_latency / n if n > 0 else 0.0

        return {
            "misses": miss_count,
            "total_latency": total_latency,
            "avg_latency": avg_latency,
        }

    # ---------- Proper L1→L2 hierarchy + Belady + breakdown ----------

    def belady_with_latency_and_breakdown(
        self,
        trace: List[Access],
        costs: List[int],
        l1_cfg: SimpleCacheConfig,
    ) -> Dict[str, float]:
        """
        Proper memory hierarchy with Belady at L2:
          - Simulate L1 (set-assoc LRU). Only L1 misses go to L2.
          - Run Belady on the L2 stream and classify L2 misses.
          - Compute end-to-end latency per access.
        """
        assert len(trace) == len(costs)
        n = len(trace)
        cache = self.cache

        # ---- Step 1: L1 sim & build L2 stream ----
        (l1_hits,
         l1_misses,
         l1_miss_bitmap,
         l2_trace,
         l2_orig_index,
         l2_index_of) = self._simulate_l1_and_build_l2_stream(trace, l1_cfg)

        m = len(l2_trace)  # number of L2 accesses (i.e., L1 misses)

        if m == 0:
            total_latency = n * self.lat.l1_hit_latency
            avg_latency = total_latency / n if n > 0 else 0.0
            return {
                "L1_hits": l1_hits,
                "L1_misses": l1_misses,
                "L2_hits": 0,
                "L2_misses": 0,
                "total_miss_cost": 0,
                "total_latency": total_latency,
                "avg_latency": avg_latency,
                "L2_compulsory_misses": 0,
                "L2_conflict_misses": 0,
                "L2_capacity_misses": 0,
                "L2_coherence_misses": 0,
            }

        # ---- Step 2: Belady hit bitmap on L2 stream ----
        l2_hit_bitmap = self._belady_hit_bitmap(l2_trace, cache)
        L2_hits = sum(1 for h in l2_hit_bitmap if h)
        L2_misses = m - L2_hits

        # Per-L2-access miss costs and line IDs
        miss_costs_l2 = [costs[i] for i in l2_orig_index]
        line_ids_l2   = [acc.addr // cache.line_size for acc in l2_trace]

        # Total miss cost under Belady
        total_miss_cost = 0
        for k in range(m):
            if not l2_hit_bitmap[k]:
                total_miss_cost += miss_costs_l2[k]

        # ---- Step 3: Fully-assoc Belady for miss-type classification ----
        total_lines = cache.num_sets * cache.assoc
        fa_cfg = CacheConfig(
            line_size=cache.line_size,
            num_sets=1,
            assoc=total_lines,
        )
        fa_hit_bitmap = self._belady_hit_bitmap(l2_trace, fa_cfg)

        # First-touch map
        first_seen: Dict[int, int] = {}
        for k, line_id in enumerate(line_ids_l2):
            if line_id not in first_seen:
                first_seen[line_id] = k

        compulsory = 0
        conflict = 0
        capacity = 0
        coherence = 0  # still 0 for single-thread MB1

        for k in range(m):
            if l2_hit_bitmap[k]:
                continue  # classify only Belady's misses

            line_id = line_ids_l2[k]
            if first_seen[line_id] == k:
                compulsory += 1
            else:
                if fa_hit_bitmap[k]:
                    conflict += 1
                else:
                    capacity += 1

        # ---- Step 4: End-to-end latency per original access ----
        total_latency = 0

        for i in range(n):
            if not l1_miss_bitmap[i]:
                total_latency += self.lat.l1_hit_latency
            else:
                k = l2_index_of[i]
                assert k is not None
                if l2_hit_bitmap[k]:
                    total_latency += self.lat.l1_hit_latency + self.lat.l2_hit_latency
                else:
                    total_latency += self.lat.l1_hit_latency + costs[i]

        avg_latency = total_latency / n if n > 0 else 0.0

        return {
            "L1_hits": l1_hits,
            "L1_misses": l1_misses,
            "L2_hits": L2_hits,
            "L2_misses": L2_misses,
            "total_miss_cost": total_miss_cost,
            "total_latency": total_latency,
            "avg_latency": avg_latency,
            "L2_compulsory_misses": compulsory,
            "L2_conflict_misses": conflict,
            "L2_capacity_misses": capacity,
            "L2_coherence_misses": coherence,
        }


    def latency_optimal_with_hierarchy(
        self,
        trace: List[Access],
        costs: List[int],
        l1_cfg: SimpleCacheConfig,
    ) -> Dict[str, float]:
        """
        Latency-optimal oracle (Cost-OPT) for the L2, with a proper L1→L2 hierarchy.

        Returns a dict with the SAME keys as belady_with_latency_and_breakdown:
          L1_hits, L1_misses,
          L2_hits, L2_misses,
          total_miss_cost, total_latency, avg_latency,
          L2_compulsory_misses, L2_conflict_misses, L2_capacity_misses, L2_coherence_misses.
        """
        assert len(trace) == len(costs)
        n = len(trace)
        cache = self.cache

        # ---- Step 1: L1 sim & build L2 stream ----
        (l1_hits,
         l1_misses,
         l1_miss_bitmap,
         l2_trace,
         l2_orig_index,
         l2_index_of) = self._simulate_l1_and_build_l2_stream(trace, l1_cfg)

        m = len(l2_trace)  # number of L2 accesses (i.e., L1 misses)

        # If nothing reaches L2, latency is all L1 hits
        if m == 0:
            total_latency = n * self.lat.l1_hit_latency
            avg_latency = total_latency / n if n > 0 else 0.0
            return {
                "L1_hits": l1_hits,
                "L1_misses": l1_misses,
                "L2_hits": 0,
                "L2_misses": 0,
                "total_miss_cost": 0,
                "total_latency": total_latency,
                "avg_latency": avg_latency,
                "L2_compulsory_misses": 0,
                "L2_conflict_misses": 0,
                "L2_capacity_misses": 0,
                "L2_coherence_misses": 0,
            }

        # ---- Step 2: Build per-L2-access line IDs and miss costs ----
        line_ids_l2   = [acc.addr // cache.line_size for acc in l2_trace]
        miss_costs_l2 = [costs[i] for i in l2_orig_index]

        # ---- Step 3: Partition L2 stream per set and solve Lat-OPT per set ----
        per_set_indices: List[List[int]] = [[] for _ in range(cache.num_sets)]
        for k, acc in enumerate(l2_trace):
            s, _ = cache.set_and_tag(acc.addr)
            per_set_indices[s].append(k)

        total_miss_cost = 0
        total_misses = 0
        # Global miss bitmap over the L2 stream
        latopt_miss_bitmap = [False] * m

        for s in range(cache.num_sets):
            idxs = per_set_indices[s]
            if not idxs:
                continue

            block_ids_s  = [line_ids_l2[k]   for k in idxs]
            miss_costs_s = [miss_costs_l2[k] for k in idxs]

            cost_s, misses_s, miss_bitmap_s = self._latopt_solve_set(
                block_ids_s, miss_costs_s, cache.assoc
            )
            total_miss_cost += cost_s
            total_misses    += misses_s

            # Map per-set miss bitmap back to global L2 indices
            for local_idx, k in enumerate(idxs):
                if miss_bitmap_s[local_idx]:
                    latopt_miss_bitmap[k] = True

        L2_misses = total_misses
        L2_hits   = m - L2_misses

        # ---- Step 4: Miss-type classification using FA oracle (same as Belady) ----
        total_lines = cache.num_sets * cache.assoc
        fa_cfg = CacheConfig(
            line_size=cache.line_size,
            num_sets=1,
            assoc=total_lines,
        )
        fa_hit_bitmap = self._belady_hit_bitmap(l2_trace, fa_cfg)

        first_seen: Dict[int, int] = {}
        for k, line_id in enumerate(line_ids_l2):
            if line_id not in first_seen:
                first_seen[line_id] = k

        compulsory = 0
        conflict = 0
        capacity = 0
        coherence = 0  # still 0 for your single-thread MB1

        for k in range(m):
            if not latopt_miss_bitmap[k]:
                continue  # classify only Lat-OPT's misses

            line_id = line_ids_l2[k]
            if first_seen[line_id] == k:
                compulsory += 1
            else:
                if fa_hit_bitmap[k]:
                    conflict += 1
                else:
                    capacity += 1

        # ---- Step 5: End-to-end latency (aggregate formula) ----
        # Every access pays at least L1 hit latency.
        # Each L2 hit (which is necessarily an L1 miss) adds L2 hit latency.
        # Each L2 miss adds its miss cost, and we've summed all miss costs above.
        total_latency = (
            n * self.lat.l1_hit_latency
            + L2_hits * self.lat.l2_hit_latency
            + total_miss_cost
        )
        avg_latency = total_latency / n if n > 0 else 0.0

        return {
            "L1_hits": l1_hits,
            "L1_misses": l1_misses,
            "L2_hits": L2_hits,
            "L2_misses": L2_misses,
            "total_miss_cost": total_miss_cost,
            "total_latency": total_latency,
            "avg_latency": avg_latency,
            "L2_compulsory_misses": compulsory,
            "L2_conflict_misses": conflict,
            "L2_capacity_misses": capacity,
            "L2_coherence_misses": coherence,
        }
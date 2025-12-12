#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <thread>
#include <atomic>
#include <barrier>

// ------------------------------------------------------------
// Configuration (parallel MB5)
// ------------------------------------------------------------

static const int NUM_THREADS     = 4;    // 4 stages / cores
static const int NUM_HOT_REMOTE  = 4;    // “remote” logical lines
static const int NUM_HOT_LOCAL   = 2;    // “local” logical lines
static const int NUM_ROUNDS      = 2000; // how many times we walk the pattern

// Each hot "line" is one cache line’s worth of state.
struct alignas(64) HotLine {
    int32_t value;
    int32_t pad[15];  // padding to keep it roughly one cache line
};

// ------------------------------------------------------------
// Global hot set (shared across all threads)
// ------------------------------------------------------------

// Conceptually, in the simulator / NUMA model:
//   - Some hot_lines[*] are homed on the local node of a given core
//   - Others are homed on remote nodes.
// In real code you’d use numa_alloc_onnode or page interleaving;
// here we just model the access pattern.
static HotLine hot_local[NUM_HOT_LOCAL];
static HotLine hot_remote[NUM_HOT_REMOTE];

// Per-thread logical access patterns (each is a sequence of pointers
// into the shared hot_* arrays).
static std::vector<HotLine*> thread_patterns[NUM_THREADS];

// Simple barrier so that threads stay roughly in phase per round.
// (C++20 std::barrier; if unavailable, replace with a manual barrier.)
static std::barrier sync_barrier(NUM_THREADS);


// ------------------------------------------------------------
// Build per-thread access patterns
// ------------------------------------------------------------

// Helper: fill a single thread’s pattern as a small permutation / skewed view
// of the same underlying hot set.
static void build_thread_pattern(int tid) {
    auto &pattern = thread_patterns[tid];
    pattern.clear();

    // Base pattern: interleave remote and local lines,
    // just like single-thread MB5.
    //
    // For each remote line r, pair it with a “preferred” local line.
    for (int r = 0; r < NUM_HOT_REMOTE; ++r) {
        HotLine* R = &hot_remote[r];
        HotLine* L = &hot_local[r % NUM_HOT_LOCAL];

        pattern.push_back(R);
        pattern.push_back(L);
    }

    // Extra local touch to slightly bias local reuse.
    if (NUM_HOT_LOCAL > 0) {
        pattern.push_back(&hot_local[tid % NUM_HOT_LOCAL]);
    }

    // To avoid the threads having *identical* traversal order (which would
    // make coherence patterns too regular), we rotate each thread’s pattern
    // by tid positions.
    if (!pattern.empty()) {
        int shift = tid % static_cast<int>(pattern.size());
        std::vector<HotLine*> rotated;
        rotated.reserve(pattern.size());
        for (size_t i = 0; i < pattern.size(); ++i) {
            rotated.push_back(pattern[(i + shift) % pattern.size()]);
        }
        pattern.swap(rotated);
    }
}


// ------------------------------------------------------------
// Worker: each thread repeatedly walks its hot-set pattern
// ------------------------------------------------------------

static void worker(int tid) {
    // Build this thread’s logical access pattern.
    build_thread_pattern(tid);

    auto &pattern = thread_patterns[tid];

    // ROI: NUM_ROUNDS iterations over the same hot set.
    for (int round = 0; round < NUM_ROUNDS; ++round) {
        // Optional barrier to keep rounds roughly aligned across threads.
        sync_barrier.arrive_and_wait();

        for (HotLine* line : pattern) {
            // Read–modify–write on a shared cache line.
            // In your simulator, each such (R,W) pair becomes:
            //    Access(addr(line), core=tid, 'R')
            //    Access(addr(line), core=tid, 'W')

            int32_t x = line->value;      // LOAD
            x += (tid + 1);               // small per-thread perturbation
            line->value = x;              // STORE
        }
    }
}


// ------------------------------------------------------------
// Main: spawn NUM_THREADS workers
// ------------------------------------------------------------
int main() {
    // Minimal initialization: give lines some non-zero values.
    for (int i = 0; i < NUM_HOT_LOCAL; ++i) {
        hot_local[i].value = 0;
    }
    for (int i = 0; i < NUM_HOT_REMOTE; ++i) {
        hot_remote[i].value = 0;
    }

    // In a real NUMA experiment you would:
    //   - place pages for some hot_lines on node 0 (local),
    //   - and others on nodes 1–3 (remote),
    //   - and pin each worker thread to a different core / node.

    std::thread threads[NUM_THREADS];
    for (int t = 0; t < NUM_THREADS; ++t) {
        threads[t] = std::thread(worker, t);
    }
    for (int t = 0; t < NUM_THREADS; ++t) {
        threads[t].join();
    }

    // Simple checksum to keep the compiler honest.
    long long sum = 0;
    for (int i = 0; i < NUM_HOT_LOCAL; ++i) {
        sum += hot_local[i].value;
    }
    for (int i = 0; i < NUM_HOT_REMOTE; ++i) {
        sum += hot_remote[i].value;
    }

    std::printf("MB5 final sum = %lld\n", sum);
    return 0;
}

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>

// ------------------------------------------------------------
// Configuration (mirrors Python MB4 parameters)
// ------------------------------------------------------------

static const int NUM_HOT_REMOTE = 4;   // remote high-cost lines
static const int NUM_HOT_LOCAL  = 2;   // local low-cost lines
static const int NUM_ROUNDS     = 2000;

// Each hot "line" is one cache line's worth of state.
// alignas(64) to keep it on its own line.
struct alignas(64) HotLine {
    int32_t value;
    // (Optional padding to roughly 64B)
    int32_t pad[15];
};

// ------------------------------------------------------------
// Global state (conceptually mapped to NUMA nodes)
// ------------------------------------------------------------

// Local hot lines: home on NUMA node 0 (same as running core).
// In a real app you'd place these with numa_alloc_onnode(0).
static HotLine hot_local[NUM_HOT_LOCAL];

// Remote hot lines: conceptually home on other NUMA nodes (1, 2, ...).
// In a real app you'd place these on remote nodes via numa_alloc_onnode(1/2/...).
static HotLine hot_remote[NUM_HOT_REMOTE];

// Access pattern over "logical lines":
// We'll fill this with pointers into hot_local / hot_remote.
static std::vector<HotLine*> access_pattern;


// ------------------------------------------------------------
// ROI: build a conflict-heavy hot-set pattern and run it
// ------------------------------------------------------------

static void build_access_pattern() {
    access_pattern.clear();
    access_pattern.reserve(NUM_HOT_REMOTE * 2 + 1);

    // Pattern idea (same as Python MB4):
    //   R0, L0, R1, L1, R2, L0, R3, L1, L0
    // where R* are remote lines, L* are local lines.
    //
    // This gives:
    //  - K = NUM_HOT_REMOTE + NUM_HOT_LOCAL distinct lines
    //  - If K > L2 associativity for the target set,
    //    we get frequent evictions in that set.
    for (int r = 0; r < NUM_HOT_REMOTE; ++r) {
        HotLine* remote_line = &hot_remote[r];
        HotLine* local_line  = &hot_local[r % NUM_HOT_LOCAL];

        access_pattern.push_back(remote_line);  // "remote" line
        access_pattern.push_back(local_line);   // "local" line
    }

    // Extra local touch to bias local reuse slightly
    if (NUM_HOT_LOCAL > 0) {
        access_pattern.push_back(&hot_local[0]);
    }
}

static void run_mb4_roi() {
    // ROI: single-thread RMW over the pattern for NUM_ROUNDS
    for (int round = 0; round < NUM_ROUNDS; ++round) {
        for (HotLine* line : access_pattern) {
            // Read–modify–write on one hot cache line.
            int32_t x = line->value;      // LOAD (modeled as L2 access → home node)
            x = x + 1;                    // Some small computation
            line->value = x;              // STORE (write back)
        }
    }
}


// ------------------------------------------------------------
// Main (skeleton)
// ------------------------------------------------------------

int main() {
    // (Optional) Initialize hot_local / hot_remote values.
    // We skip detailed initialization here since we only care about ROI.
    for (int i = 0; i < NUM_HOT_LOCAL; ++i) {
        hot_local[i].value = 0;
    }
    for (int i = 0; i < NUM_HOT_REMOTE; ++i) {
        hot_remote[i].value = 0;
    }

    // In a real NUMA experiment, at this point you could:
    //   - pin this thread to core 0
    //   - place hot_local[] on node 0, hot_remote[] on nodes 1/2/...
    // via libnuma or first-touch policies.

    build_access_pattern();
    run_mb4_roi();

    // Simple checksum to keep compiler from optimizing everything away
    long long sum = 0;
    for (int i = 0; i < NUM_HOT_LOCAL; ++i) {
        sum += hot_local[i].value;
    }
    for (int i = 0; i < NUM_HOT_REMOTE; ++i) {
        sum += hot_remote[i].value;
    }

    std::printf("MB4 final sum = %lld\n", sum);
    return 0;
}

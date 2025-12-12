#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <pthread.h>

// ------------------------------------------------------------
// Shared state
// ------------------------------------------------------------

#define NUM_TOTAL_ENTRIES   (1 << 20)   // 1M entries

// Stage-to-stage buffers (logically placed on different NUMA nodes)
//
//   Stage 0 (T0, node 0) writes buf01
//   Stage 1 (T1, node 1) reads buf01, writes buf12
//   Stage 2 (T2, node 2) reads buf12, writes buf23
//   Stage 3 (T3, node 3) reads buf23, produces final result
//
static int32_t buf01[NUM_TOTAL_ENTRIES];   // home: node 0
static int32_t buf12[NUM_TOTAL_ENTRIES];   // home: node 1
static int32_t buf23[NUM_TOTAL_ENTRIES];   // home: node 2

// Optional final buffer on the last stage's node
static int32_t buf_final[NUM_TOTAL_ENTRIES];  // home: node 3

// Pipeline stage flags
// 0 -> 1 means: "stage X finished producing its whole buffer"
static std::atomic<int> ready_01;  // T0 -> T1
static std::atomic<int> ready_12;  // T1 -> T2
static std::atomic<int> ready_23;  // T2 -> T3


// ------------------------------------------------------------
// Stage 0: Thread on NUMA node 0
// Generates initial values into buf01
// ------------------------------------------------------------
void* stage0_thread(void* arg) {
    // Local private input (conceptually on node 0)
    static int32_t priv0[NUM_TOTAL_ENTRIES];
    /* Load / initialize priv0 from sensor or input source */

    for (size_t i = 0; i < NUM_TOTAL_ENTRIES; ++i) {
        int32_t x = priv0[i];      // LOCAL read
        // Simple generation function
        int32_t y = x * 2 + 1;
        buf01[i] = y;              // LOCAL write (buf on node 0)
    }

    // Signal that buf01 is ready for stage 1
    ready_01.store(1, std::memory_order_release);
    return (nullptr);
}


// ------------------------------------------------------------
// Stage 1: Thread on NUMA node 1
// Reads buf01 (remote) and writes buf12 (local)
// ------------------------------------------------------------
void* stage1_thread(void* arg) {
    // Private state for this stage (node 1)
    static int32_t priv1[NUM_TOTAL_ENTRIES];

    // Wait for stage 0 to finish producing buf01
    while (ready_01.load(std::memory_order_acquire) == 0) {
        // spin
    }

    for (size_t i = 0; i < NUM_TOTAL_ENTRIES; ++i) {
        int32_t in  = buf01[i];       // REMOTE read (home node 0)
        int32_t tmp = in + 3;         // some operation
        int32_t acc = priv1[i];       // LOCAL read
        acc += tmp;
        priv1[i] = acc;               // LOCAL write

        buf12[i] = acc ^ 0x5a5a5a5a;  // LOCAL write (buf on node 1)
    }

    // Signal that buf12 is ready for stage 2
    ready_12.store(1, std::memory_order_release);
    return nullptr;
}


// ------------------------------------------------------------
// Stage 2: Thread on NUMA node 2
// Reads buf12 (remote) and writes buf23 (local)
// ------------------------------------------------------------
void* stage2_thread(void* arg) {
    static int32_t priv2[NUM_TOTAL_ENTRIES];

    // Wait for stage 1
    while (ready_12.load(std::memory_order_acquire) == 0) {
        // spin
    }

    for (size_t i = 0; i < NUM_TOTAL_ENTRIES; ++i) {
        int32_t in  = buf12[i];        // REMOTE read (home node 1)
        int32_t tmp = in * 7;          // some operation
        int32_t acc = priv2[i];        // LOCAL read
        acc ^= tmp;
        priv2[i] = acc;                // LOCAL write

        buf23[i] = acc - 42;           // LOCAL write (buf on node 2)
    }

    // Signal that buf23 is ready for stage 3
    ready_23.store(1, std::memory_order_release);
    return nullptr;
}


// ------------------------------------------------------------
// Stage 3: Thread on NUMA node 3
// Reads buf23 (remote), produces final outputs and a reduction
// ------------------------------------------------------------
void* stage3_thread(void* arg) {
    static int32_t priv3[NUM_TOTAL_ENTRIES];

    // Wait for stage 2
    while (ready_23.load(std::memory_order_acquire) == 0) {
        // spin
    }

    long long final_sum = 0;

    for (size_t i = 0; i < NUM_TOTAL_ENTRIES; ++i) {
        int32_t in  = buf23[i];         // REMOTE read (home node 2)
        int32_t tmp = in ^ 0x12345678;  // some operation

        int32_t prev = priv3[i];        // LOCAL read
        int32_t out  = prev + tmp;      // LOCAL compute
        priv3[i]     = out;             // LOCAL write

        buf_final[i] = out;             // LOCAL write (final buffer on node 3)
        final_sum   += (long long)out;  // reduction
    }

    std::printf("Stage3 final_sum = %lld\n", final_sum);
    return nullptr;
}


// ------------------------------------------------------------
// Main: create 4 pipeline threads
// ------------------------------------------------------------
int main() {
    // Initialize flags
    ready_01.store(0, std::memory_order_relaxed);
    ready_12.store(0, std::memory_order_relaxed);
    ready_23.store(0, std::memory_order_relaxed);

    // Create threads
    pthread_t t0, t1, t2, t3;
    pthread_create(&t0, nullptr, stage0_thread, nullptr);
    pthread_create(&t1, nullptr, stage1_thread, nullptr);
    pthread_create(&t2, nullptr, stage2_thread, nullptr);
    pthread_create(&t3, nullptr, stage3_thread, nullptr);

    // Join threads
    pthread_join(t0, nullptr);
    pthread_join(t1, nullptr);
    pthread_join(t2, nullptr);
    pthread_join(t3, nullptr);

    return 0;
}
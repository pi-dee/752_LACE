#include <atomic>
#include <cstdlib>
#include <cstdio>
#include <pthread.h>

// ------------------------------------------------------------
// Shared state
// ------------------------------------------------------------

#define NUM_TOTAL_ENTRIES    (1 << 20)   // 1M Entries
#define NUM_FILTERS          8
#define FILTER_RADIUS        4
#define FILTER_LEN           (2 * FILTER_RADIUS + 1)

// Shared buffer lives on producer's node
static int32_t shared_buf[NUM_TOTAL_ENTRIES];

// Synchronization flag: 0 = not ready, 1 = producer finished
static std::atomic<int> ready_flag;



// ------------------------------------------------------------
// Producer thread: on NUMA node 0
// ------------------------------------------------------------
void* producer_thread(void* arg) {
    // Producer private data
    static int32_t prod_private[NUM_TOTAL_ENTRIES];
    /* Loading of data into private buffer from sensor*/

    // Single-pass write: shared_buf[i] = f(prod_private[i])
    for (size_t i = 0; i < NUM_TOTAL_ENTRIES; ++i) {
        // Shared write (producer owns the line, consumer will read)
        shared_buf[i] = prod_private[i] * 2;
    }

    // Make the entire buffer visible to the consumer
    ready_flag.store(1, std::memory_order_release);
    return (nullptr);
}



// ------------------------------------------------------------
// Consumer thread: on NUMA node 1
// ------------------------------------------------------------
void* consumer_thread(void* arg) {
    // Consumer private data (local to node 1)
    static int32_t cons_private[NUM_TOTAL_ENTRIES];

    // Local filter bank and per-filter outputs (all local)
    static int32_t filters[NUM_FILTERS][FILTER_LEN];
    static int64_t filter_outputs[NUM_FILTERS];

    /* Initialize consumer private data */
    /* Initialize filters */

    // Wait until producer has finished writing the entire shared_buf
    while (ready_flag.load(std::memory_order_acquire) == 0) {
        // spin
    }

    // Multi-filter 1D convolution
    const size_t start = FILTER_RADIUS;
    const size_t end   = NUM_TOTAL_ENTRIES - FILTER_RADIUS;  // inclusive range [start, end)

    for (int f = 0; f < NUM_FILTERS; ++f) {
        int64_t acc = 0;

        for (size_t i = start; i < end; ++i) {
            int64_t conv = 0;

            // 1D window centered at i
            for (int k = -FILTER_RADIUS; k <= FILTER_RADIUS; ++k) {
                size_t idx = i + (size_t)k;
                int32_t x = shared_buf[idx];                       // REMOTE read (node 0)
                int32_t h = filters[f][k + FILTER_RADIUS];         // LOCAL read (filter)
                conv += (int64_t)x * (int64_t)h;
            }

            // Mix in some local state as well (optional)
            int32_t prev = cons_private[i];                        // LOCAL read
            cons_private[i] = prev + (int32_t)(conv & 0x7fffffff); // LOCAL write

            acc += conv;
        }

        filter_outputs[f] = acc;
    }

    // Combine all filter outputs into a single result
    int64_t final_result = 0;
    for (int f = 0; f < NUM_FILTERS; ++f) {
        final_result += filter_outputs[f];
    }

    std::printf("Consumer final result = %ld\n", (long)final_result);
    return (nullptr);
}


// ------------------------------------------------------------
// Main: allocate on nodes & start threads
// ------------------------------------------------------------
int main() {
    // Initialize flags
    ready_flag.store(0, std::memory_order_relaxed);

    // Invoke Threads
    pthread_t prod_tid, cons_tid;
    pthread_create(&prod_tid, nullptr, producer_thread, nullptr);
    pthread_create(&cons_tid, nullptr, consumer_thread, nullptr);
    pthread_join(prod_tid, nullptr);
    pthread_join(cons_tid, nullptr);
    return (0);
}
#include <cstdlib>
#include <cstdint>

/*
MB-RANDOM:
- Single-thread microbenchmark with random memory accesses
- random_idx[] is a small index array (remote)
- data[] is a large data array (local)
- For each access:
    idx = random_idx[i];   // REMOTE read
    x   = data[idx];       // RANDOM local read
    data[idx] = x * scale + bias;  // RANDOM local write
*/

#define NUM_ELEMS          (1 << 20)     // 1M data elements
#define NUM_ACCESSES       (1 << 22)     // 4M random accesses
#define NUM_ROUNDS         4             // repeat pattern
#define SCALE              3
#define BIAS               7

// Small index array (conceptually REMOTE to core/node)
static uint32_t *random_idx;

// Large data array (conceptually LOCAL to core/node)
static int32_t  *data_array;

int main(void) {
    /*
     * Initialization / placement:
     *  - random_idx: allocate / first-touch on a remote NUMA node
     *  - data_array: allocate / first-touch on the local NUMA node
     *
     * In real experiments, use numa_alloc_onnode or mbind() to enforce
     * placement; here we just malloc and imagine the mapping.
     */
    random_idx = (uint32_t *) std::malloc(NUM_ACCESSES * sizeof(uint32_t));
    data_array = (int32_t  *) std::malloc(NUM_ELEMS    * sizeof(int32_t));

    // (Initialization of random_idx and data_array omitted from ROI)
    // e.g., fill random_idx[i] with uniform random in [0, NUM_ELEMS).

    /*
     * ------------------- REGION OF INTEREST -------------------
     * Random gather/scatter over data_array, driven by remote indices.
     * ----------------------------------------------------------
     */
    for (int r = 0; r < NUM_ROUNDS; ++r) {
        for (int i = 0; i < NUM_ACCESSES; ++i) {
            uint32_t idx = random_idx[i];          // REMOTE read (index)
            // Optionally mask if you want power-of-two wrapping:
            // idx &= (NUM_ELEMS - 1);

            int32_t x = data_array[idx];           // RANDOM local read
            x = x * SCALE + BIAS;                  // simple compute
            data_array[idx] = x;                   // RANDOM local write
        }
    }

    long long checksum = 0;
    for (int i = 0; i < NUM_ELEMS; ++i) {
        checksum += data_array[i];
    }

    std::free(random_idx);
    std::free(data_array);
    return 0;
}

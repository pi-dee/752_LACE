#include <cstdlib>
#include <cstdint>
#include <cstdio>

/*
MB8:
- Single-thread microbenchmark for matrix transpose.
- Captures:
    * Strided reads from the input matrix
    * Contiguous writes to the output matrix
- In a NUMA-aware experiment:
    * You can place A on a remote node (remote reads)
    * And B on the local node (local writes)
*/

#define N_ROWS        (1 << 10)   // 1024 rows
#define N_COLS        (1 << 10)   // 1024 cols
#define NUM_ROUNDS    4           // repeat transpose to generate more traffic

// Conceptually, A can be REMOTE and B LOCAL (or vice-versa).
static float *A;   // [N_ROWS x N_COLS], row-major
static float *B;   // [N_COLS x N_ROWS], row-major (transpose destination)

int main(void) {
    /*
     * Allocation / placement (outside ROI):
     *  - In real NUMA experiments:
     *      A: allocate / first-touch on remote node
     *      B: allocate / first-touch on local node
     *    Here we just use malloc and imagine the mapping.
     */
    A = (float *) std::malloc(N_ROWS * N_COLS * sizeof(float));
    B = (float *) std::malloc(N_ROWS * N_COLS * sizeof(float)); // same total elems

    if (!A || !B) {
        std::perror("malloc failed");
        return 1;
    }

    // (Optional) initialization of A/B omitted from ROI.
    // e.g., fill A with some values so compiler doesn't optimize everything away.

    /*
     * ------------------- REGION OF INTEREST -------------------
     *   NUM_ROUNDS times:
     *     for i in [0..N_ROWS):
     *       for j in [0..N_COLS):
     *         B[j, i] = A[i, j]
     * ----------------------------------------------------------
     *
     * Access patterns (row-major):
     *   - A[i,j] is at A[i * N_COLS + j]  --> contiguous in j (row-wise)
     *   - B[j,i] is at B[j * N_ROWS + i]  --> strided in i for fixed j
     *
     * If A is remote:
     *   - Mostly streaming remote reads, plus local writes to B.
     * If B is remote:
     *   - Mostly streaming local reads, plus remote writes with awkward strides.
     */

    for (int r = 0; r < NUM_ROUNDS; ++r) {
        for (int i = 0; i < N_ROWS; ++i) {
            for (int j = 0; j < N_COLS; ++j) {
                // Row-major index for A(i,j)
                int idx_A = i * N_COLS + j;
                // Row-major index for B(j,i) in an N_COLS x N_ROWS matrix
                int idx_B = j * N_ROWS + i;

                float x = A[idx_A];    // LOAD (remote or local)
                B[idx_B] = x;          // STORE (local or remote)
            }
        }
    }

    // Simple checksum (post-ROI) to keep the compiler honest
    double checksum = 0.0;
    for (int i = 0; i < N_ROWS * N_COLS; ++i) {
        checksum += B[i];
    }
    std::printf("MB8 transpose checksum = %.3f\n", checksum);

    std::free(A);
    std::free(B);
    return 0;
}

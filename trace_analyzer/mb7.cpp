#include <cstdlib>
#include <cstdint>
#include <cstdio>

/*
MB-2DCONV:
- Single-thread 2D convolution kernel.
- input_img[] (conceptually LOCAL to the core/node)
- kernel[]    (conceptually REMOTE to the core/node)
- output_img[] (LOCAL)

For each round:
  For each output pixel (y, x):
    acc = 0;
    For ky in [0..K_H-1], kx in [0..K_W-1]:
      w = kernel[ky, kx];              // REMOTE read
      v = input_img[y+ky-pad_y, x+kx-pad_x];  // LOCAL read
      acc += w * v;
    output_img[y, x] = acc;            // LOCAL write
*/

#define IMG_H            1024      // image height
#define IMG_W            1024      // image width
#define KERNEL_H         5
#define KERNEL_W         5
#define PAD_H            (KERNEL_H / 2)
#define PAD_W            (KERNEL_W / 2)
#define NUM_ROUNDS       4         // repeat full convolution for reuse

// Input with halo padding so we can do "same" convolution
static int32_t *input_img;   // size: (IMG_H + 2*PAD_H) * (IMG_W + 2*PAD_W)
static int32_t *output_img;  // size: IMG_H * IMG_W
static int32_t *kernel;      // size: KERNEL_H * KERNEL_W

int main(void) {
    /*
     * Placement / initialization:
     *
     *  - input_img, output_img: allocate / first-touch on the local NUMA node
     *  - kernel: allocate / first-touch on a REMOTE NUMA node
     *
     * In real NUMA experiments, you would use numa_alloc_onnode() or mbind()
     * to enforce placement. Here we just malloc and conceptually treat
     * kernel[] as remote.
     */

    const int padded_h = IMG_H + 2 * PAD_H;
    const int padded_w = IMG_W + 2 * PAD_W;

    input_img  = (int32_t *) std::malloc(padded_h * padded_w * sizeof(int32_t));
    output_img = (int32_t *) std::malloc(IMG_H * IMG_W * sizeof(int32_t));
    kernel     = (int32_t *) std::malloc(KERNEL_H * KERNEL_W * sizeof(int32_t));

    if (!input_img || !output_img || !kernel) {
        std::fprintf(stderr, "Allocation failed\n");
        return 1;
    }

    // --- Initialization (not part of ROI) ---
    // Fill with some deterministic values; details not important.
    for (int y = 0; y < padded_h; ++y) {
        for (int x = 0; x < padded_w; ++x) {
            input_img[y * padded_w + x] = (y + x) & 0xFF;
        }
    }
    for (int i = 0; i < IMG_H * IMG_W; ++i) {
        output_img[i] = 0;
    }
    for (int ky = 0; ky < KERNEL_H; ++ky) {
        for (int kx = 0; kx < KERNEL_W; ++kx) {
            kernel[ky * KERNEL_W + kx] = (ky + kx + 1);  // small positive ints
        }
    }

    /*
     * ------------------- REGION OF INTEREST -------------------
     * 2D convolution over NUM_ROUNDS to generate reuse + pressure.
     * ----------------------------------------------------------
     */
    for (int r = 0; r < NUM_ROUNDS; ++r) {
        for (int y = 0; y < IMG_H; ++y) {
            for (int x = 0; x < IMG_W; ++x) {
                int32_t acc = 0;

                // Convolution window centered at (y, x)
                for (int ky = 0; ky < KERNEL_H; ++ky) {
                    int in_y = y + ky;  // because we padded input by PAD_H above

                    for (int kx = 0; kx < KERNEL_W; ++kx) {
                        int in_x = x + kx;  // padded by PAD_W

                        // REMOTE read: kernel[ky, kx]
                        int32_t w = kernel[ky * KERNEL_W + kx];

                        // LOCAL read: input_img[in_y, in_x]
                        int32_t v = input_img[in_y * padded_w + in_x];

                        acc += w * v;
                    }
                }

                // LOCAL write: output_img[y, x]
                output_img[y * IMG_W + x] = acc;
            }
        }
    }

    long long checksum = 0;
    for (int i = 0; i < IMG_H * IMG_W; ++i) {
        checksum += output_img[i];
    }

    std::free(input_img);
    std::free(output_img);
    std::free(kernel);
    return 0;
}
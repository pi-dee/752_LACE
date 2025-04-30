//Read multiple arrays twice
#include <stdint.h>
#include <stdio.h>

#define N (1024 * 16)  // Smaller size to fit into cache if possible
int a[N], b[N], c[N];

int main(){
    // Initialize all arrays
    for (int i = 0; i < N; i++){
        a[i] = i % 256;
        b[i] = (i * 2) % 256;
        c[i] = (i * 3) % 256;
    }

    int sum = 0;

    // Interleaved reads: access a, b, c in turn
    for (int i = 0; i < N; i++){
        sum += a[i];
        sum += b[i];
        sum += c[i];
    }

    // Interleaved re-reads (second pass, same pattern)
    for (int i = 0; i < N; i++){
        sum += a[i];
        sum += b[i];
        sum += c[i];
    }

    // Prevent optimization
    volatile int dummy = sum;
    return dummy;
}

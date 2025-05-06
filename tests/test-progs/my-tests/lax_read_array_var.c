#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <gem5/m5ops.h>

int main(int argc, char *argv[]) {
    uint32_t size = 8 * 1024;
    
    if (argc > 1) {
        size = atoi(argv[1]) * 1024;
    }
    
    printf("Running with size: %u\n", size);
    
    uint32_t *arr = (uint32_t*)malloc(size * sizeof(uint32_t));
    if (!arr) {
        return 1;
    }
    
    uint32_t result = 0;
    
    m5_dump_reset_stats(0, 0);
    for(uint32_t i = 0; i < size; i+=16) {
        asm volatile (
            "lax %0, 0(%1)"
            : "=r" (result)
            : "r" (arr+i)
            : "memory"
        );
    }
    m5_dump_reset_stats(0, 0);
    
    free(arr);
    return 0;
}
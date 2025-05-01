#include <stdint.h>

#define SIZE 8*1024

int main() {
    uint32_t result = 0;
    uint32_t arr1[SIZE];
    uint32_t arr2[SIZE];
    uint32_t arr3[SIZE];
    for(int i = 0; i < SIZE; i+=16) {
        asm volatile (
        "lax %0, 0(%1)"
        : "=r" (result)
        : "r" (arr1+i)
        : "memory"
    );

        asm volatile (
        "lax %0, 0(%1)"
        : "=r" (result)
        : "r" (arr2+i)
        : "memory"
    );

        asm volatile (
        "lax %0, 0(%1)"
        : "=r" (result)
        : "r" (arr3+i)
        : "memory"
    );
    }

    for(int i = 0; i < SIZE; i+=16) {
        asm volatile (
        "lax %0, 0(%1)"
        : "=r" (result)
        : "r" (arr1+i)
        : "memory"
    );

        asm volatile (
        "lax %0, 0(%1)"
        : "=r" (result)
        : "r" (arr2+i)
        : "memory"
    );

        asm volatile (
        "lax %0, 0(%1)"
        : "=r" (result)
        : "r" (arr3+i)
        : "memory"
    );
    }

    }
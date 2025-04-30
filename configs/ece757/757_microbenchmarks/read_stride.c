// Read non-consecutively
#include <stdint.h>
#include <stdio.h>

#define N (1024 * 64)
int data[N];

int sum_strided(int *arr, int stride, int n){
    int sum = 0;
    for (int i = 0; i < n; i += stride){
        sum += arr[i];
    }
    return sum;
}

int main(){
    for (int i = 0; i < N; i++){
        data[i] = i % 256;
    }

    volatile int out = sum_strided(data, 4, N);  // larger strides may reduce locality
    return 0;
}

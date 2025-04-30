#include <stdint.h>
#include <stdio.h>

#define N (1024 * 16)
int data[2 * N];

int interleaved_sum(int *arr, int n){
    int sum = 0;
    for (int i = 0; i < n; i++){
        sum += arr[i];       // near access
        sum += arr[n - i];   // far access interleaved
    }
    return sum;
}

int main(){
    for (int i = 0; i < 2 * N; i++){
        data[i] = i % 256;
    }

    int result = interleaved_sum(data, N);

    // Prevent optimization
    volatile int dummy = result;
    return dummy;
}

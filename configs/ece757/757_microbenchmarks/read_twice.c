#include <stdint.h>
#include <stdio.h>

#define N (1024 * 64)
int data[N];

int sum(int *arr, int n){
    int sum = 0;
    for (int i = 0; i < n; i++){
        sum += arr[i];
    }
    return sum;
}

int count_greater_than(int *arr, int n, int threshold){
    int count = 0;
    for (int i = 0; i < n; i++){
        if (arr[i] > threshold){
            count++;
        }
    }
    return count;
}

int main(){
    for (int i = 0; i < N; i++){
        data[i] = i % 256;
    }

    // First read
    int total = sum(data, N);

    // Second read, separate purpose
    int count = count_greater_than(data, N, 128);

    // Prevent optimization
    volatile int dummy = total + count;
    return dummy;
}

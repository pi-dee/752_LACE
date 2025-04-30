// Read one array and sum it up
#include <stdint.h>
#include <stdio.h>

#define N 1024*64
int data[N];

int sum(int *arr, int n){
    int sum = 0;
    for (int i = 0; i < n; i++){
        sum += arr[i];
    }
    return sum;
}

int main(){
    for (int i = 0; i < N; i++){
        data[i] = i%100;
    }

    int out = sum(data, N);

    return 0;
}
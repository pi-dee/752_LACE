#include <cstdio>
#include <random>
#include <ctime>    
#include <cstdlib>  

int main()
{
    srand(time(0));
	const int N = 4096;
	int X[N], Y[N], alpha = 2;
	for (int i = 0; i < N; ++i)
	{
		X[i] = rand();
		Y[i] = rand();
	}

	// Start of daxpy loop
	for (int i = 0; i < N; ++i)
	{
        asm("xchg %ecx,%ecx;"); // magic instruction
		Y[i] = alpha * X[i] + Y[i];
        asm("xchg %ecx,%ecx;"); // magic instruction
	}
	// End of daxpy loop

	int sum = 0;
	for (int i = 0; i < N; ++i)
	{
		sum += Y[i];
	}
	printf("%d\n", sum);
	return 0;
}
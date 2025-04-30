#include <cstdio>
#include <random>

int main()
{
	const int N = 4096;
	float X[N], Y[N], alpha = 0.5;
	std::random_device rd; std::mt19937 gen(rd());
	std::uniform_real_distribution<> dis(1, 2);
	for (int i = 0; i < N; ++i)
	{
		X[i] = dis(gen);
		Y[i] = dis(gen);
	}

	// Start of daxpy loop
	for (int i = 0; i < N; ++i)
	{
		asm("xchg %ecx,%ecx;"); // magic instruction
		Y[i] = alpha * X[i] + Y[i];
		asm("xchg %ecx,%ecx;"); // magic instruction
	}
	// End of daxpy loop

	float sum = 0;
	for (int i = 0; i < N; ++i)
	{
		sum += Y[i];
	}
	printf("%f\n", sum);
	return 0;
}
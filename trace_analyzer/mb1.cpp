#include <cstdlib>
/*
MB1:
- Single-Thread Microbenchmark for private data access to local and remote data
*/

#define NUM_CHANNELS           12
#define NUM_FIELDS             5
#define SAMPLE_RATE            64
#define SAMPLE_PERIOD          1024
#define ENTRIES_PER_CHANNEL    SAMPLE_RATE*SAMPLE_PERIOD

/*
Initialization of Channel Header Masks (Remote to Node)
*/
int *header_fields = (int *) malloc(NUM_FIELDS * sizeof(int));

int main(void) {
    /*
    Initialization of data & filters (Local to Node)
    */
    int *sensor_data = (int *) malloc(NUM_CHANNELS * ENTRIES_PER_CHANNEL * sizeof(int));
    const int scale = 3;

    // Process Sensor Data
    for (int i = 0; i < NUM_FIELDS; ++i) {
        int header_mask = header_fields[i];

        for (int j = 0; j < NUM_CHANNELS; ++j) {
            int idx = j * ENTRIES_PER_CHANNEL;

            // Mask Sensor Header
            sensor_data[idx] = sensor_data[idx] + header_mask; 

            // Process Channel Data
            for (int k = 1; k < ENTRIES_PER_CHANNEL; ++k) {
                sensor_data[idx + k] = sensor_data[idx + k] * scale;
            }
        }
    }
}
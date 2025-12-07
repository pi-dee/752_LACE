#include <map>
#include <iostream>
#include <vector>
#include "mem/ruby/structures/L2LatencyTracker.hh"
namespace gem5 
{
namespace ruby 
{
// --- CONFIGURATION ---
// IMPORTANT: These must match your Python configuration!
// If your Python config says "2 Memory Controllers", set NUM_BANKS to 2.
static const int NUM_BANKS = 16; 

// The size of the stripe (Granularity). 
// 64KB = 65536 bytes.
// If you want cache-line interleaving, set this to 64.
static const uint64_t STRIPE_SIZE = 64; 

static const double ALPHA = 0.2;

struct LatencyStats 
{
    double ewma = 0.0;
    Cycles last = Cycles(0);
    uint64_t samples = 0;
};

// Global Map: MachineID -> Banks
static std::map<NodeID, std::vector<LatencyStats>> global_stats;

void
L2LatencyTracker::recordLatency(MachineID mid, Addr addr, Cycles lat)
{
    auto id = mid.getNum();
    // 1. Initialize vector for this controller if needed
    if (global_stats[id].empty()) 
    {
        // We now resize to the number of memory banks/channels we are tracking
        global_stats[id].resize(NUM_BANKS);
    }

    // 2. Determine Bank (Modulo Arithmetic)
    // Step A: "Remove" the offset within the stripe.
    //         If Stripe is 64KB, addr 0 and addr 64000 both become '0'.
    uint64_t stripe_index = addr / STRIPE_SIZE;

    // Step B: Round-Robin distribution across banks
    //         Stripe 0 -> Bank 0
    //         Stripe 1 -> Bank 1
    //         ...
    //         Stripe 8 -> Bank 0
    int bank_id = stripe_index % NUM_BANKS;

    LatencyStats &s = global_stats[id][bank_id];

    // 3. Update Stats (Same as before)
    s.last = lat;
    if (s.samples == 0) 
    {
        s.ewma = (double)lat;
    } else {
        if(lat <= Cycles(125)) {
            s.ewma = ALPHA * (double)lat + (1.0 - ALPHA) * s.ewma;
        }
    }
    s.samples++;
}

double
L2LatencyTracker::getLatency(MachineID mid, Addr addr)
{
    auto id = mid.getNum();

    // 1. Check if controller exists
    auto it = global_stats.find(id);
    if (it == global_stats.end()) 
    {
        return 0.0;
    }

    // 2. Check if Bank exists
    uint64_t stripe_index = addr / STRIPE_SIZE;
    int bank_id = stripe_index % NUM_BANKS;

    const auto& buckets = it->second;
    if (bank_id < buckets.size()) 
    {
        return buckets[bank_id].ewma;
    }

    return 0.0;
}


// --- Printer Helper ---
struct L2StatsPrinter 
{
    ~L2StatsPrinter() 
    {
        std::cout << 
        "\n==========================================================\n";
        std::cout << 
        "FINAL L2 MISS LATENCY REPORT (Per Memory Bank)\n";
        std::cout << 
        "==========================================================\n";
        std::cout << "Config: " << NUM_BANKS << " Banks, " 
                  << STRIPE_SIZE << " bytes per stripe.\n";

        for (auto const& [machID, buckets] : global_stats) 
        {
            std::cout << "Controller: " << machID << "\n";
            for (size_t i = 0; i < buckets.size(); ++i) 
            {
                // We print all banks, even if empty, to see load imbalance
                std::cout << "  [Bank " << i << "]"
                          << " EWMA: " << buckets[i].ewma
                << " cycles | Samples: " << buckets[i].samples << "\n";
            }
            std::cout 
            << "----------------------------------------------------------\n";
        }
    }
};

static L2StatsPrinter printer;

} // namespace ruby
} // namespace gem5
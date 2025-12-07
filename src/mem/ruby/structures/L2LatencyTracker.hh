#ifndef __MEM_RUBY_STRUCTURES_L2LATENCYTRACKER_HH__
#define __MEM_RUBY_STRUCTURES_L2LATENCYTRACKER_HH__
#include "base/types.hh"
#include "mem/ruby/common/MachineID.hh"

namespace gem5 
{
namespace ruby 
{
class L2LatencyTracker 
{
  public:
    // Default constructor (required for SLICC instantiation)
    L2LatencyTracker() 
    {
    }

    // The method we will call from SLICC
    void recordLatency(MachineID mid, Addr addr, Cycles lat);

    // Add this declaration inside the class
    static double getLatency(MachineID mid, Addr addr);
};

} // namespace ruby
} // namespace gem5

#endif // __MEM_RUBY_STRUCTURES_L2LATENCYTRACKER_HH__
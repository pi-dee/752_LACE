#ifndef __MEM_CACHE_REPLACEMENT_POLICIES_LATENCY_AWARE_BRRIP_RP_HH__
#define __MEM_CACHE_REPLACEMENT_POLICIES_LATENCY_AWARE_BRRIP_RP_HH__

#include "mem/cache/replacement_policies/brrip_rp.hh"
#include "mem/ruby/common/MachineID.hh"

namespace gem5 {
struct LatencyAwareBRRIPRPParams;
namespace replacement_policy 
{
class LatencyAwareBRRIP : public BRRIP
{
  protected:
    // Store the ID relative to L2Cache
    int m_node_id;
    double m_k_factor;

  public:
    typedef LatencyAwareBRRIPRPParams Params;
    LatencyAwareBRRIP(const Params &p);
    ~LatencyAwareBRRIP() = default;

    ReplaceableEntry* getVictim
    (const ReplacementCandidates& candidates) const override;
};

} // namespace replacement_policy
} // namespace gem5

#endif // __MEM_CACHE_REPLACEMENT_POLICIES_LATENCY_AWARE_BRRIP_RP_HH__
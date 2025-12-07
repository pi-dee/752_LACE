#include <memory>
#include "base/logging.hh"
#include "base/trace.hh"
#include "debug/CacheRepl.hh"
#include "debug/LACE.hh"
#include "debug/RubyCache.hh"
#include "params/LatencyAwareBRRIPRP.hh"
#include "mem/cache/replacement_policies/latency_aware_brrip_rp.hh"
#include "mem/ruby/structures/L2LatencyTracker.hh"
#include "mem/ruby/slicc_interface/AbstractCacheEntry.hh"
#include "mem/ruby/protocol/MachineType.hh" 
namespace gem5 {
namespace replacement_policy {

LatencyAwareBRRIP::LatencyAwareBRRIP(const Params &p)
    : BRRIP(p), m_node_id(p.node_id), m_k_factor(p.k_factor), m_num_bits(p.num_bits)
{
}

ReplaceableEntry*
LatencyAwareBRRIP::getVictim(const ReplacementCandidates& candidates) const
{
    std::cout << "Inside getVictim\n" << std::endl;
    assert(candidates.size() > 0);

    ReplaceableEntry* victim = candidates[0];
    double min_score = 1.0e100; 
    double victim_rrpv = 0.0;
    double victim_lat = 0.0;

    // Reconstruct the MachineID locally
    // Since we are only using this for L2 Caches, 
    //we assume MachineType::L2Cache
    ruby::MachineID my_id;
    my_id.type = ruby::MachineType::MachineType_L2Cache;
    my_id.num = m_node_id;

    Addr addr;
    // [DEBUG] Start of decision
    DPRINTF(LACE, "--- Eviction Decision Start ---\n");

    for (const auto& candidate : candidates) {
        
        // 1. Get RRPV Priority
        std::shared_ptr<BRRIPReplData> repl_data = 
            std::static_pointer_cast<BRRIPReplData>
            (candidate->replacementData);
        double rrpv_importance = (double)repl_data->rrpv.saturate();

        // 2. Get Latency Bonus
        double lat = 0.0;
        
        ruby::AbstractCacheEntry *ruby_entry = 
            static_cast<ruby::AbstractCacheEntry *>(candidate);
        
        if (ruby_entry) {
            addr = ruby_entry->m_Address;
            
            // CYCLE FIX: We don't map the address anymore.
            // We assume that if the line is in THIS 
            //cache, it belongs to THIS NodeID.
            lat = ruby::L2LatencyTracker::getLatency(my_id, addr);
        }

        // 3. Final Score
        double q = std::min(pow(2, m_num_bits) - 1, (lat - 16) / 7);
        double nls = (pow(2, m_num_bits) - 1) - q;

        double score = ((1-m_k_factor) * rrpv_importance) + (m_k_factor * nls);

        // [DEBUG] Print details for EVERY candidate
        DPRINTF(LACE, " Cand Addr: %#x | RRPV: %2.0f | Latency: %6.2f | Score: %6.2f\n", addr, rrpv_importance, lat, score);

        if (score < min_score) {
            min_score = score;
            victim = candidate;

            victim_rrpv = rrpv_importance;
            victim_lat = lat;
        }
    }

    // [DEBUG] Print the winner
    ruby::AbstractCacheEntry *victim_entry = 
            static_cast<ruby::AbstractCacheEntry *>(victim);

    DPRINTF(LACE, ">>> EVICTING: %#x | RRPV: %2.0f | Latency: %6.2f | Score: %6.2f\n", 
            victim_entry ? victim_entry->m_Address : 0, 
            victim_rrpv, 
            victim_lat, 
            min_score);

    // Standard BRRIP Aging logic...
    int diff = std::static_pointer_cast<BRRIPReplData>(
        victim->replacementData)->rrpv.saturate();

    if (diff > 0) {
        for (const auto& candidate : candidates) {
            std::static_pointer_cast<BRRIPReplData>(
                candidate->replacementData)->rrpv += diff;
        }
    }

    return victim;
}

} // namespace replacement_policy
} // namespace gem5
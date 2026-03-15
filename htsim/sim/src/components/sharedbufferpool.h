// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#ifndef SHARED_BUFFER_POOL_H
#define SHARED_BUFFER_POOL_H

/*
 * SharedBufferPool - Manages a shared buffer pool for all ports
 *
 * This class implements a shared buffer architecture where multiple
 * ports/queues draw from a common buffer pool. This enables more
 * efficient buffer utilization compared to static partitioning.
 *
 * Design follows UEC specification recommendations:
 * - Tail drop threshold based on Plane_BDP (typically 2-5 * Plane_BDP)
 * - Thread-safe operations via mutex protection
 * - Simple allocate/deallocate interface compatible with Queue classes
 */

#include <mutex>
#include "config.h"

class SharedBufferPool {
public:
    /*
     * Constructor
     *
     * @param total_buffer_size  Total buffer pool size in bytes
     * @param tail_drop_threshold  Tail drop threshold in bytes
     *                           UEC spec recommendation: 2-5 * Plane_BDP
     *                           When current usage exceeds this threshold,
     *                           new allocations may be rejected to prevent
     *                           buffer bloat and reduce latency
     */
    SharedBufferPool(mem_b total_buffer_size, mem_b tail_drop_threshold);

    /*
     * Check if buffer space can be allocated for a new packet
     *
     * @param size  Requested allocation size in bytes
     * @return true if allocation would succeed, false otherwise
     *
     * This is a non-blocking check that does not modify pool state.
     * Useful for preemptive drop decisions in queue implementations.
     */
    bool canAllocate(mem_b size) const;

    /*
     * Allocate buffer space from the pool
     *
     * @param size  Requested allocation size in bytes
     * @return true if allocation succeeded, false if pool is exhausted
     *           or would exceed tail drop threshold
     *
     * Thread-safe: uses mutex to protect shared state
     */
    bool allocate(mem_b size);

    /*
     * Release buffer space back to the pool
     *
     * @param size  Amount of space to deallocate in bytes
     *
     * Thread-safe: uses mutex to protect shared state
     * Note: Does not validate that deallocation amount was previously allocated
     */
    void deallocate(mem_b size);

    /*
     * Get current buffer usage
     *
     * @return Current used buffer space in bytes
     *
     * Thread-safe: uses mutex to protect shared state
     */
    mem_b getUsage() const;

    /*
     * Get buffer utilization as percentage
     *
     * @return Utilization percentage (0-100)
     *
     * Thread-safe: uses mutex to protect shared state
     */
    double getUtilization() const;

    /*
     * Check if current usage exceeds tail drop threshold
     *
     * @return true if usage >= tail_drop_threshold, false otherwise
     *
     * When this returns true, queues should consider dropping
     * incoming packets to prevent buffer bloat.
     *
     * Thread-safe: uses mutex to protect shared state
     */
    bool isOverThreshold() const;

    /*
     * Get total buffer pool size
     *
     * @return Total buffer capacity in bytes
     */
    mem_b getTotalSize() const { return _total_buffer_size; }

    /*
     * Get tail drop threshold
     *
     * @return Tail drop threshold in bytes
     */
    mem_b getTailDropThreshold() const { return _tail_drop_threshold; }

private:
    mem_b _total_buffer_size;    // Total buffer pool capacity in bytes
    mem_b _current_usage;        // Currently allocated bytes
    mem_b _tail_drop_threshold;  // Threshold for tail drop (UEC spec: 2-5 * Plane_BDP)
    mutable std::mutex _mutex;   // Mutex for thread-safe access
};

#endif

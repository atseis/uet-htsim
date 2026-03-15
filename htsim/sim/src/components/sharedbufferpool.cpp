// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#include "sharedbufferpool.h"
#include <algorithm>

SharedBufferPool::SharedBufferPool(mem_b total_buffer_size, mem_b tail_drop_threshold)
    : _total_buffer_size(total_buffer_size),
      _current_usage(0),
      _tail_drop_threshold(tail_drop_threshold) {
    // Validate parameters
    assert(_total_buffer_size > 0);
    assert(_tail_drop_threshold > 0);
    assert(_tail_drop_threshold <= _total_buffer_size);
}

bool SharedBufferPool::canAllocate(mem_b size) const {
    std::lock_guard<std::mutex> lock(_mutex);

    // Check if allocation would exceed total capacity
    if (_current_usage + size > _total_buffer_size) {
        return false;
    }

    // Check if allocation would exceed tail drop threshold
    // This provides early congestion signal per UEC specification
    if (_current_usage + size > _tail_drop_threshold) {
        return false;
    }

    return true;
}

bool SharedBufferPool::allocate(mem_b size) {
    std::lock_guard<std::mutex> lock(_mutex);

    // Check if allocation would exceed total capacity
    if (_current_usage + size > _total_buffer_size) {
        return false;
    }

    // Check if allocation would exceed tail drop threshold
    // Per UEC spec, tail drop should activate when buffer usage
    // exceeds 2-5 * Plane_BDP to prevent buffer bloat
    if (_current_usage + size > _tail_drop_threshold) {
        return false;
    }

    _current_usage += size;
    return true;
}

void SharedBufferPool::deallocate(mem_b size) {
    std::lock_guard<std::mutex> lock(_mutex);

    // Prevent underflow - clamp to zero if deallocation exceeds current usage
    if (size >= _current_usage) {
        _current_usage = 0;
    } else {
        _current_usage -= size;
    }
}

mem_b SharedBufferPool::getUsage() const {
    std::lock_guard<std::mutex> lock(_mutex);
    return _current_usage;
}

double SharedBufferPool::getUtilization() const {
    std::lock_guard<std::mutex> lock(_mutex);

    if (_total_buffer_size == 0) {
        return 0.0;
    }

    return (static_cast<double>(_current_usage) / _total_buffer_size) * 100.0;
}

bool SharedBufferPool::isOverThreshold() const {
    std::lock_guard<std::mutex> lock(_mutex);
    return _current_usage >= _tail_drop_threshold;
}

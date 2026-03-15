// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#include "sharedbufferqueue.h"
#include <sstream>
#include "ecn.h"

static int global_sbq_id = 0;

SharedBufferQueue::SharedBufferQueue(linkspeed_bps bitrate,
                                     mem_b maxsize,
                                     EventList& eventlist,
                                     QueueLogger* logger,
                                     SharedBufferPool& buffer_pool,
                                     bool is_low_priority)
    : Queue(bitrate, maxsize, eventlist, logger),
      _buffer_pool(buffer_pool),
      _local_queued_bytes(0),
      _is_low_priority(is_low_priority),
      _ecn_minthresh(maxsize * 2),
      _ecn_maxthresh(maxsize * 2),
      _num_tail_drops(0),
      _num_ecn_marks(0),
      _serv(0) {
    std::stringstream ss;
    ss << "sharedqueue(" << bitrate / 1000000 << "Mb/s," << maxsize << "bytes,"
       << (is_low_priority ? "low" : "high") << ")";
    _nodename = ss.str();
}

void SharedBufferQueue::beginService() {
    assert(!_enqueued.empty());
    eventlist().sourceIsPendingRel(*this, drainTime(_enqueued.back()));
}

void SharedBufferQueue::completeService() {
    if (_enqueued.empty()) {
        _serv = 0;
        return;
    }

    Packet* pkt = _enqueued.pop();
    _queuesize -= pkt->size();
    _local_queued_bytes -= pkt->size();
    _buffer_pool.deallocate(pkt->size());

    bool ecn = decideEcn();
    if (ecn) {
        pkt->set_flags(pkt->flags() | ECN_CE);
        _num_ecn_marks++;
    }

    pkt->flow().logTraffic(*pkt, *this, TrafficLogger::PKT_DEPART);
    if (_logger)
        _logger->logQueue(*this, QueueLogger::PKT_SERVICE, *pkt);

    log_packet_send(drainTime(pkt));

    pkt->sendOn();

    if (!_enqueued.empty()) {
        beginService();
    }
}

void SharedBufferQueue::doNextEvent() {
    // Only complete service if there's something to service
    if (!_enqueued.empty()) {
        completeService();
    } else {
        // Queue is empty, reset service flag
        _serv = 0;
    }
}

bool SharedBufferQueue::decideEcn() {
    if (_local_queued_bytes > _ecn_maxthresh) {
        return true;
    } else if (_local_queued_bytes > _ecn_minthresh) {
        uint64_t p = (0x7FFFFFFF * (_local_queued_bytes - _ecn_minthresh)) /
                     (_ecn_maxthresh - _ecn_minthresh);
        if ((uint64_t)random() < p) {
            return true;
        }
    }
    return false;
}

void SharedBufferQueue::setEcnThreshold(mem_b ecn_thresh) {
    _ecn_minthresh = ecn_thresh;
    _ecn_maxthresh = ecn_thresh;
}

void SharedBufferQueue::setEcnThresholds(mem_b min_thresh, mem_b max_thresh) {
    _ecn_minthresh = min_thresh;
    _ecn_maxthresh = max_thresh;
}

void SharedBufferQueue::receivePacket(Packet& pkt) {
    pkt.flow().logTraffic(pkt, *this, TrafficLogger::PKT_ARRIVE);
    if (_logger)
        _logger->logQueue(*this, QueueLogger::PKT_ENQUEUE, pkt);

    mem_b pkt_size = pkt.size();

    bool exceeds_pool_threshold = _buffer_pool.isOverThreshold();
    bool would_exceed_queue = (_queuesize + pkt_size > _maxsize);
    bool would_exceed_pool = !_buffer_pool.canAllocate(pkt_size);

    if (exceeds_pool_threshold || would_exceed_queue || would_exceed_pool) {
        if (_logger)
            _logger->logQueue(*this, QueueLogger::PKT_DROP, pkt);
        pkt.flow().logTraffic(pkt, *this, TrafficLogger::PKT_DROP);
        pkt.free();
        _num_tail_drops++;
        _num_drops++;
        return;
    }

    if (!_buffer_pool.allocate(pkt_size)) {
        if (_logger)
            _logger->logQueue(*this, QueueLogger::PKT_DROP, pkt);
        pkt.flow().logTraffic(pkt, *this, TrafficLogger::PKT_DROP);
        pkt.free();
        _num_tail_drops++;
        _num_drops++;
        return;
    }

    Packet* pkt_p = &pkt;
    _enqueued.push(pkt_p);
    _queuesize += pkt_size;
    _local_queued_bytes += pkt_size;

    if (_serv == 0) {
        beginService();
    }
}

mem_b SharedBufferQueue::queuesize() const {
    return _queuesize;
}

bool SharedBufferQueue::isEmpty() const {
    return _queuesize == 0;
}

uint8_t SharedBufferQueue::getQueueUsage() const {
    if (_maxsize == 0)
        return 0;
    return (uint8_t)((_queuesize * 100) / _maxsize);
}

// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#ifndef SHARED_BUFFER_QUEUE_H
#define SHARED_BUFFER_QUEUE_H

#include "queue.h"
#include "sharedbufferpool.h"

class SharedBufferQueue : public Queue {
public:
    SharedBufferQueue(linkspeed_bps bitrate,
                      mem_b maxsize,
                      EventList& eventlist,
                      QueueLogger* logger,
                      SharedBufferPool& buffer_pool,
                      bool is_low_priority = true);

    virtual void doNextEvent();
    virtual void receivePacket(Packet& pkt);
    virtual mem_b queuesize() const override;
    virtual mem_b maxsize() const override { return _maxsize; }
    virtual bool isEmpty() const;
    virtual uint8_t getQueueUsage() const;

    void setEcnThreshold(mem_b ecn_thresh);
    void setEcnThresholds(mem_b min_thresh, mem_b max_thresh);

    bool isLowPriority() const { return _is_low_priority; }
    SharedBufferPool& getBufferPool() const { return _buffer_pool; }
    int numTailDrops() const { return _num_tail_drops; }
    int numEcnMarks() const { return _num_ecn_marks; }

protected:
    virtual void beginService();
    virtual void completeService();
    bool decideEcn();

    SharedBufferPool& _buffer_pool;
    mem_b _local_queued_bytes;
    bool _is_low_priority;
    CircularBuffer<Packet*> _enqueued;
    mem_b _ecn_minthresh;
    mem_b _ecn_maxthresh;
    int _num_tail_drops;
    int _num_ecn_marks;
    int _serv;
};

#endif

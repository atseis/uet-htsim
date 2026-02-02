// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#include "uec_logger.h"
#include <iomanip>
#include <iostream>
#include <vector>
#include "uecpacket.h"

UecSinkLoggerSampling::UecSinkLoggerSampling(simtime_picosec period, EventList& eventlist)
    : SinkLoggerSampling(period, eventlist, Logger::UEC_SINK, UecLogger::RATE) {
    cout << "UecSinkLoggerSampling(p=" << timeAsSec(period) << " init \n";
}

void UecSinkLoggerSampling::doNextEvent() {
    eventlist().sourceIsPendingRel(*this, _period);
    simtime_picosec now = eventlist().now();
    simtime_picosec delta = now - _last_time;
    _last_time = now;
    TcpAck::seq_t deltaB;
    // uint32_t deltaSnd = 0;
    double rate;
    // cout << "UecSinkLoggerSampling(p=" << timeAsSec(_period) << "), t=" << timeAsSec(now) <<
    // "\n";
    for (uint64_t i = 0; i < _sinks.size(); i++) {
        UecSink* sink = (UecSink*)_sinks[i];
        if ((mem_b)_last_seq[i] <= sink->total_received()) {
            deltaB = sink->total_received() - _last_seq[i];
            if (delta > 0)
                rate = deltaB * 1000000000000.0 / delta;  // Bps
            else
                rate = 0;

            _logfile->writeRecord(_sink_type, sink->get_id(), _event_type, sink->cumulative_ack(),
                                  /*deltaB>0?(deltaSnd * 100000 / deltaB):0*/
                                  sink->reorder_buffer_size(), rate);

            _last_rate[i] = rate;
        }
        _last_seq[i] = sink->total_received();
    }
}

string UecSinkLoggerSampling::event_to_str(RawLogEvent& event) {
    stringstream ss;
    ss << fixed << setprecision(9) << event._time;
    switch (event._type) {
        case Logger::UEC_SINK:
            assert(event._ev == UecLogger::RATE);
            ss << " Type UEC_SINK ID " << event._id << " Ev RATE"
               << " CAck " << (uint64_t)event._val1 << " ReorderBuffer " << (uint64_t)event._val2
               << " Rate " << (uint64_t)event._val3;
            // val2 seems to always be zero - maybe a bug
            break;
        default:
            ss << "Unknown event " << event._type;
    }
    return ss.str();
}

/*
UecNicLoggerSampling::UecNicLoggerSampling(simtime_picosec period,
                                             EventList& eventlist):
    NicLoggerSampling(period, eventlist)
{
    cout << "UecNicLoggerSampling(p=" << timeAsSec(period) << " init \n";
}
*/

void UecTrafficLogger::logTraffic(Packet& pkt, Logged& location, TrafficEvent ev) {
    int val3 = 0;
    switch (pkt.type()) {
        case UECDATA:
            if (pkt.type() == UECDATA) {
                // Safe downcast because we checked type
                UecDataPacket& dpkt = static_cast<UecDataPacket&>(pkt);
                // PacketType is an enum in UecDataPacket
                val3 = dpkt.packet_type();
                // DATA_PULL=0, DATA_SPEC=1, DATA_RTX=2, DATA_PROBE=3
            }
            break;
        case UECACK:
            val3 = 100;
            break;
        case UECNACK:
            val3 = 101;
            break;
        case UECPULL:
            val3 = 102;
            break;
        case UECRTS:
            val3 = 103;
            break;
        default:
            val3 = 0;
            break;
    }

    _logfile->writeRecord(Logger::UEC_TRAFFIC, location.get_id(), ev, pkt.flow().get_id(), pkt.id(),
                          val3);
}

string UecTrafficLogger::event_to_str(RawLogEvent& event) {
    stringstream ss;
    ss << fixed << setprecision(9) << event._time;
    // assert(event._type == Logger::TRAFFIC_EVENT);
    // It might be TRAFFIC_EVENT but registered to this logger?
    // Actually Logger::TRAFFIC_EVENT is generic.
    // TrafficLoggerSimple filters by Type TRAFFIC.
    // We should use TRAFFIC_EVENT as well.

    ss << " Type UECTRAFFIC ID " << event._id;
    switch ((TrafficLogger::TrafficEvent)event._ev) {
        case PKT_ARRIVE:
            ss << " Ev ARRIVE ";
            break;
        case PKT_DEPART:
            ss << " Ev DEPART ";
            break;
        case PKT_CREATESEND:
            ss << " Ev CREATESEND ";
            break;
        case PKT_CREATE:
            ss << " Ev CREATE ";
            break;
        case PKT_SEND:
            ss << " Ev SEND ";
            break;
        case PKT_DROP:
            ss << " Ev DROP ";
            break;
        case PKT_RCVDESTROY:
            ss << " Ev RCV ";
            break;
        case PKT_TRIM:
            ss << " Ev TRIM ";
            break;
        case PKT_BOUNCE:
            ss << " Ev BOUNCE ";
            break;
        default:
            ss << " Ev UNKNOWN(" << event._ev << ") ";
            break;
    }
    ss << " FlowID " << (uint64_t)event._val1 << " PktID " << (uint64_t)event._val2;

    // Decode val3
    int val3 = (int)event._val3;
    if (val3 == 100)
        ss << " PktType ACK";
    else if (val3 == 101)
        ss << " PktType NACK";
    else if (val3 == 102)
        ss << " PktType PULL";
    else if (val3 == 103)
        ss << " PktType RTS";
    else if (val3 == 3)
        ss << " PktType PROBE";  // UecDataPacket::DATA_PROBE
    else if (val3 == 2)
        ss << " PktType RX";  // UecDataPacket::DATA_RTX
    else if (val3 == 1)
        ss << " PktType SPEC";  // UecDataPacket::DATA_SPEC
    else if (val3 == 0)
        ss << " PktType DATA";  // UecDataPacket::DATA_PULL (Normal)

    return ss.str();
}

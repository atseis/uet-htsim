#include <string.h>
#include <sys/types.h>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <vector>
#include "clock.h"
#include "compositequeue.h"
#include "config.h"
#include "drawable.h"
#include "eqds.h"
#include "eventlist.h"
#include "logfile.h"
#include "loggers.h"
#include "loggertypes.h"
#include "ndp.h"
#include "network.h"
#include "pipe.h"
#include "queue.h"
#include "route.h"

using namespace std;

int main(int argc, char* argv[]) {
    // freopen("output.txt", "w", stdout);
    EventList eventlist;
    simtime_picosec end_time = timeFromSec(1);
    Clock c(timeFromSec(50 / 100.), eventlist);
    //--------------------------------------------------
    // 基本参数设置
    uint32_t cwnd = 50;
    int seed = 13;
    srand(seed);
    srandom(seed);
    mem_b queuesize = 35;
    mem_b ecn_threshold = 70;
    stringstream filename(ios_base::out);
    filename << "logout.dat";
    bool rts = false;
    uint32_t mtu = 4000;
    linkspeed_bps SERVICE1 = speedFromMbps((uint64_t)100000);
    simtime_picosec RTT1 = timeFromUs((uint32_t)1);

    int flow_count = 200;
    //--------------------------------------------------
    // 模拟初始设置，包括日志的设置
    eventlist.setEndtime(end_time);
    Logfile logfile(filename.str(), eventlist);
    logfile.setStartTime(timeFromSec(0.0));
    Packet::set_packet_size(mtu);
    queuesize = memFromPkt(queuesize);
    ecn_threshold =
        memFromPkt(ecn_threshold);  // 这几行代码，本质就是将原先的“数目”转换为实际的字节数大小
    QueueLoggerSampling qs1 = QueueLoggerSampling(timeFromUs((uint32_t)10), eventlist);
    logfile.addLogger(qs1);
    //--------------------------------------------------
    // 网络构建
    Pipe pipe1(RTT1, eventlist);
    pipe1.setName("pipe1");
    logfile.writeName(pipe1);
    Pipe pipe2(RTT1, eventlist);
    pipe2.setName("pipe2");
    logfile.writeName(pipe2);
    CompositeQueue queue1(SERVICE1, queuesize, eventlist, NULL, 64, false);
    queue1.setName("Queue1");
    logfile.writeName(queue1);
    queue1.set_ecn_threshold(ecn_threshold);
    CompositeQueue queue2(SERVICE1, queuesize, eventlist, NULL, 64, false);
    queue2.setName("Queue2");
    logfile.writeName(queue2);
    queue2.set_ecn_threshold(ecn_threshold);

    NdpSrc* ndpSrc;
    NdpSink* ndpSink;
    NdpSinkLoggerSampling sinkLogger(timeFromUs((uint32_t)25), eventlist);
    logfile.addLogger(sinkLogger);
    NdpRtxTimerScanner ndpRtxScanner(timeFromMs(1), eventlist);

    route_t* routeout;
    route_t* routein;

    NdpSink::_oversubscribed_congestion_control = true;

    vector<NdpSrc*> ndp_srcs;

    bool log_flow_events = true;
    FlowEventLoggerSimple* event_logger = NULL;
    if (log_flow_events) {
        event_logger = new FlowEventLoggerSimple();
        logfile.addLogger(*event_logger);
    }
    for (int i = 0; i < flow_count; i++) {
        // Create Src
        ndpSrc = new NdpSrc(NULL, NULL, eventlist, rts);
        ndpSrc->setRouteStrategy(SINGLE_PATH);
        ndpSrc->setCwnd(cwnd * Packet::data_packet_size());
        ndpSrc->set_flowsize(100 * Packet::data_packet_size());
        ndpSrc->setName("NDP");
        logfile.writeName(*ndpSrc);
        ndp_srcs.push_back(ndpSrc);
        if (log_flow_events) {
            ndpSrc->logFlowEvents(*event_logger);
        }
        // Create Sink
        ndpSink = new NdpSink(eventlist, SERVICE1, 10);
        ndpSink->setName("NDPSink");
        ndpSink->setRouteStrategy(SINGLE_PATH);
        logfile.writeName(*ndpSink);
        ndpRtxScanner.registerNdp(*ndpSrc);
        // src->sink
        routeout = new route_t();
        routeout->push_back(new FairPriorityQueue(SERVICE1, memFromPkt(1000), eventlist, NULL));
        routeout->push_back(new Pipe(RTT1, eventlist));
        routeout->push_back(&queue1);
        routeout->push_back(&pipe1);
        routeout->push_back(
            new CompositeQueue(SERVICE1, memFromPkt(1000), eventlist, NULL, 64, true));
        routeout->push_back(new Pipe(RTT1, eventlist));
        routeout->push_back(ndpSink);
        routein = new route_t();
        routein->push_back(&queue2);
        routein->push_back(&pipe2);
        routein->push_back(ndpSrc);
        ndpSrc->connect(routeout, routein, *ndpSink, timeFromUs(0.0));
        // log
        sinkLogger.monitorSink(ndpSink);
    }
    int pktsize = Packet::data_packet_size();
    logfile.write("# PktSize=" + ntoa(pktsize) + "bytes");
    double rtt = timeAsSec(RTT1);
    logfile.write("# RTT=" + ntoa(rtt));
    Logged::dump_idmap();

    while (eventlist.doNextEvent()) {
    }
    cout << "DONE" << endl;
    int new_pkts = 0, rtx_pkts = 0, bounce_pkts = 0;
    for (size_t i = 0; i < ndp_srcs.size(); i++) {
        new_pkts += ndp_srcs[i]->_new_packets_sent;
        rtx_pkts += ndp_srcs[i]->_rtx_packets_sent;
        bounce_pkts += ndp_srcs[i]->_bounces_received;
    }
    printf("New: %d Rtx: %d Bounced: %d\n", new_pkts, rtx_pkts, bounce_pkts);
    return 0;
}

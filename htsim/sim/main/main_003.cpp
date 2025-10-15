#include <string.h>
#include "connection_matrix.h"
#include "fat_tree_switch.h"
#include "fat_tree_topology.h"

#include <sys/types.h>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <iterator>
#include <list>
#include <memory>
#include <regex>
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
#include "trigger.h"

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

    // int flow_count = 20;
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

    uint32_t path_entropy_size = 10000000;
    RouteStrategy route_strategy = SINGLE_PATH;
    NdpSink::_oversubscribed_congestion_control = true;
    NdpSrc::setMinRTO(50000);  // increase RTO to avoid spurious retransmits
    NdpSrc::setPathEntropySize(path_entropy_size);
    NdpSrc::setRouteStrategy(route_strategy);
    NdpSink::setRouteStrategy(route_strategy);

    vector<NdpSrc*> ndp_srcs;

    bool log_flow_events = true;
    FlowEventLoggerSimple* event_logger = NULL;
    if (log_flow_events) {
        event_logger = new FlowEventLoggerSimple();
        logfile.addLogger(*event_logger);
    }
    //--------------------------------------------------
    // 创建拓扑
    unique_ptr<FatTreeTopology> top;
    unique_ptr<FatTreeTopologyCfg> topo_cfg;
    uint32_t tiers = 3, no_of_nodes = 16;
    simtime_picosec switch_latency = timeFromUs((uint32_t)0);
    queue_type qt = COMPOSITE;
    queue_type snd_type = FAIR_PRIO;
    topo_cfg = make_unique<FatTreeTopologyCfg>(tiers, no_of_nodes, SERVICE1, queuesize, RTT1,
                                               switch_latency, qt, snd_type);

    uint32_t topo_num_failed = 0;
    if (topo_num_failed > 0) {
        topo_cfg->set_failed_links(topo_num_failed);
    }
    QueueLoggerFactory* qlf = 0;
    top = make_unique<FatTreeTopology>(topo_cfg.get(), qlf, &eventlist, nullptr);
    //--------------------------------------------------
    // 获得 net_paths
    vector<const Route*>*** net_paths = new vector<const Route*>**[no_of_nodes];
    int** path_refcounts = new int*[no_of_nodes];
    for (size_t s = 0; s < no_of_nodes; s++) {
        net_paths[s] = new vector<const Route*>*[no_of_nodes];
        path_refcounts[s] = new int[no_of_nodes];
        for (size_t d = 0; d < no_of_nodes; d++) {
            net_paths[s][d] = NULL;
            path_refcounts[s][d] = 0;
        }
    }
    ConnectionMatrix* conns = new ConnectionMatrix(no_of_nodes);
    const char* tm_file = "one.cm";
    if (!conns->load(tm_file)) {
        cout << "Failed to load connection matrix " << tm_file << endl;
        exit(-1);
    }
    if (conns->N != no_of_nodes) {
        cout << "Connection matrix number of node is " << conns->N << " while I am using "
             << no_of_nodes << endl;
        exit(-1);
    }
    for (size_t c = 0; c < conns->failures.size(); c++) {
        failure* crt = conns->failures.at(c);
        cout << "Adding link failure switch type " << crt->switch_type << " Switch ID "
             << crt->switch_id << endl;
        top->add_failed_link(crt->switch_type, crt->switch_id, crt->link_id);
    }
    vector<NdpPullPacer*> pacers;
    for (size_t ix = 0; ix < no_of_nodes; ix++) {
        pacers.push_back(new NdpPullPacer(eventlist, SERVICE1, 0.99));
    }
    list<const Route*> routes;
    vector<connection*>* all_conns = conns->getAllConnections();
    for (size_t c = 0; c < all_conns->size(); c++) {
        connection* crt = all_conns->at(c);
        int src = crt->src, dst = crt->dst;
        path_refcounts[src][dst]++;
        path_refcounts[dst][src]++;
        if (!net_paths[src][dst]) {
            vector<const Route*>* paths = top->get_bidir_paths(src, dst, false);
            net_paths[src][dst] = paths;
        }
        if (!net_paths[dst][src]) {
            vector<const Route*>* paths = top->get_bidir_paths(dst, src, false);
            net_paths[dst][src] = paths;
        }
    }

    //--------------------------------------------------
    // 构造 Flow
    int path_burst = 1;
    map<flowid_t, TriggerTarget*> flowmap;
    for (size_t c = 0; c < all_conns->size(); c++) {
        connection* crt = all_conns->at(c);
        int src = crt->src, dst = crt->dst;
        ndpSrc = new NdpSrc(NULL, NULL, eventlist, rts);
        ndpSrc->setCwnd(cwnd * Packet::data_packet_size());
        ndp_srcs.push_back(ndpSrc);
        ndpSrc->set_dst(dst);
        ndpSrc->set_path_burst(path_burst);
        if (crt->flowid) {
            ndpSrc->set_flowid(crt->flowid);
            assert(flowmap.find(crt->flowid) == flowmap.end());  // ensure no dup flows
            flowmap[crt->flowid] = ndpSrc;
        }
        if (crt->size > 0) {
            ndpSrc->set_flowsize(crt->size);
        }
        if (crt->trigger) {
            Trigger* trig = conns->getTrigger(crt->trigger, eventlist);
            trig->add_target(*ndpSrc);
        }
        if (crt->send_done_trigger) {
            Trigger* trig = conns->getTrigger(crt->send_done_trigger, eventlist);
            ndpSrc->set_end_trigger(*trig);
        }
        ndpSink = new NdpSink(pacers[dst]);
        ndpSink->set_src(src);
        ndpSrc->setName("ndp_" + ntoa(src) + "_" + ntoa(dst));
        ndpSink->setName("ndp_sink_" + ntoa(dst) + "_" + ntoa(src));
        logfile.writeName(*ndpSrc);
        logfile.writeName(*ndpSink);
        if (crt->recv_done_trigger) {
            Trigger* trig = conns->getTrigger(crt->recv_done_trigger, eventlist);
            ndpSink->set_end_trigger(*trig);
        }
        ndpSink->set_priority(crt->priority);
        ndpRtxScanner.registerNdp(*ndpSrc);
        // 路由策略
        // assert(route_strategy == SINGLE_PATH);
        int choice = rand() % net_paths[src][dst]->size();
        routeout = new Route(*(net_paths[src][dst]->at(choice)));
        routeout->add_endpoints(ndpSrc, ndpSink);
        // routein = new Route(*(net_paths[dst][src]->at(choice)));
        routein = new Route(*top->get_bidir_paths(dst, src, false)->at(choice));
        routein->add_endpoints(ndpSink, ndpSrc);
        ndpSrc->connect(routeout, routein, *ndpSink, crt->start);
        // 路径统计
        path_refcounts[src][dst]--;
        path_refcounts[dst][src]--;
        if (path_refcounts[src][dst] == 0 && net_paths[src][dst]) {
            for (auto& route : *net_paths[src][dst]) {
                if (route->reverse()) {
                    delete route->reverse();
                }
                delete route;
            }
            delete net_paths[src][dst];
        }
        if (path_refcounts[dst][src] == 0 && net_paths[dst][src]) {
            for (auto& route : *net_paths[dst][src]) {
                if (route->reverse()) {
                    delete route->reverse();
                }
                delete route;
            }
            delete net_paths[dst][src];
        }
        sinkLogger.monitorSink(ndpSink);
    }
    for (size_t ix = 0; ix < no_of_nodes; ix++) {
        delete path_refcounts[ix];
    }
    int pktsize = Packet::data_packet_size();
    logfile.write("# PktSize=" + ntoa(pktsize) + "bytes");
    double rtt = timeAsSec(RTT1);
    logfile.write("# RTT=" + ntoa(rtt));
    Logged::dump_idmap();

    cout << "Starting Simulation" << endl;
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

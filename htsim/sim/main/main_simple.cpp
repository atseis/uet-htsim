// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#include "config.h"
#include <sstream>

#include <iostream>
#include <string.h>
#include <math.h>
#include <unistd.h>
#include "network.h"
#include "randomqueue.h"
#include "shortflows.h"
#include "pipe.h"
#include "eventlist.h"
#include "logfile.h"
#include "loggers.h"
#include "clock.h"
#include "ndp.h"
#include "compositequeue.h"
#include "firstfit.h"
#include "topology.h"
#include "queue_lossless_input.h"
#include "connection_matrix.h"

#include <list>

// 使用最简单的拓扑：3个节点（2个发送方，1个接收方）
#define SIMPLE_NODES 3

EventList eventlist;

// 简单的直连拓扑类
class SimpleTopology : public Topology {
public:
    Pipe* pipes[SIMPLE_NODES][SIMPLE_NODES];
    RandomQueue* queues[SIMPLE_NODES][SIMPLE_NODES];

    SimpleTopology(mem_b queuesize, linkspeed_bps speed, simtime_picosec latency) {
        // 初始化所有队列和管道
        for (int i = 0; i < SIMPLE_NODES; i++) {
            for (int j = 0; j < SIMPLE_NODES; j++) {
                if (i != j) {
                    // 创建队列
                    queues[i][j] = new RandomQueue(speed, queuesize, eventlist, NULL);
                    queues[i][j]->setName("Queue_" + ntoa(i) + "_to_" + ntoa(j));

                    // 创建管道
                    pipes[i][j] = new Pipe(latency, eventlist);
                    pipes[i][j]->setName("Pipe_" + ntoa(i) + "_to_" + ntoa(j));

                    // 连接队列和管道
                    queues[i][j]->connectTo(pipes[i][j]);
                } else {
                    queues[i][j] = NULL;
                    pipes[i][j] = NULL;
                }
            }
        }
    }

    virtual vector<const Route*>* get_bidir_paths(uint32_t src, uint32_t dest, bool reverse) {
        vector<const Route*>* paths = new vector<const Route*>();

        if (src >= SIMPLE_NODES || dest >= SIMPLE_NODES || src == dest) {
            return paths;
        }

        // 创建简单的直连路径
        Route* route = new Route();

        // 添加源队列和管道
        route->push_back(queues[src][dest]);
        route->push_back(pipes[src][dest]);

        paths->push_back(route);

        return paths;
    }

    virtual vector<uint32_t>* get_neighbours(uint32_t src) {
        vector<uint32_t>* neighbours = new vector<uint32_t>();
        for (uint32_t i = 0; i < SIMPLE_NODES; i++) {
            if (i != src) {
                neighbours->push_back(i);
            }
        }
        return neighbours;
    }

    virtual uint32_t no_of_nodes() const {
        return SIMPLE_NODES;
    }

    virtual ~SimpleTopology() {
        for (int i = 0; i < SIMPLE_NODES; i++) {
            for (int j = 0; j < SIMPLE_NODES; j++) {
                if (queues[i][j]) delete queues[i][j];
                if (pipes[i][j]) delete pipes[i][j];
            }
        }
    }
};

int main(int argc, char **argv) {
    Clock c(timeFromSec(5 / 100.), eventlist);

    // 固定参数设置
    mem_b queuesize = memFromPkt(15);
    linkspeed_bps linkspeed = speedFromMbps((double)100000); // 100Gbps
    int packet_size = 9000;
    uint32_t cwnd = 15;
    double logtime = 0.25; // ms
    stringstream filename(ios_base::out);
    simtime_picosec hop_latency = timeFromUs((uint32_t)1);
    simtime_picosec switch_latency = timeFromUs((uint32_t)0);
    queue_type qt = COMPOSITE;
    queue_type snd_type = FAIR_PRIO;

    // 路由策略：单一路径
    RouteStrategy route_strategy = SINGLE_PATH;
    int seed = 13;
    int end_time = 1000; // 微秒

    filename << "logout_simple.dat";

    srand(seed);
    srandom(seed);

    Packet::set_packet_size(packet_size);

    eventlist.setEndtime(timeFromUs((uint32_t)end_time));

    // 准备日志文件
    cout << "Logging to " << filename.str() << endl;
    Logfile logfile(filename.str(), eventlist);
    logfile.setStartTime(timeFromSec(0));

    // 设置NDP参数
    NdpSrc::setMinRTO(50000);
    NdpSrc::setRouteStrategy(route_strategy);
    NdpSink::setRouteStrategy(route_strategy);

    NdpSrc* ndpSrc1;
    NdpSrc* ndpSrc2;
    NdpSink* ndpSnk;

    Route* routeout1, *routein1;
    Route* routeout2, *routein2;

    // 重传定时器扫描器
    NdpRtxTimerScanner ndpRtxScanner(timeFromUs((uint32_t)9), eventlist);

    // 创建简单的3节点拓扑（2个发送方，1个接收方）
    // 节点0和1是发送方，节点2是接收方

    // 创建连接矩阵
    ConnectionMatrix* conns = new ConnectionMatrix(SIMPLE_NODES);

    // 添加两个连接：节点0->节点2 和 节点1->节点2
    conns->setFlow(0, 2, 0, 1000000); // 1MB流量
    conns->setFlow(1, 2, 0, 1000000); // 1MB流量

    // 创建简单的直连拓扑
    SimpleTopology* top = new SimpleTopology(queuesize, linkspeed, hop_latency);

    // 获取路径
    vector<const Route*>* paths_0_to_2 = top->get_bidir_paths(0, 2, false);
    vector<const Route*>* paths_1_to_2 = top->get_bidir_paths(1, 2, false);
    vector<const Route*>* paths_2_to_0 = top->get_bidir_paths(2, 0, false);
    vector<const Route*>* paths_2_to_1 = top->get_bidir_paths(2, 1, false);

    // 创建拉取调度器
    vector<NdpPullPacer*> pacers;
    for (size_t ix = 0; ix < SIMPLE_NODES; ix++)
        pacers.push_back(new NdpPullPacer(eventlist, linkspeed, 0.99));

    // 创建第一个连接：节点0 -> 节点2
    ndpSrc1 = new NdpSrc(NULL, NULL, eventlist, false);
    ndpSrc1->setCwnd(cwnd * Packet::data_packet_size());
    ndpSrc1->set_dst(2);
    ndpSrc1->set_flowsize(1000000); // 1MB

    ndpSnk = new NdpSink(pacers[2]);
    ndpSnk->set_src(0);

    ndpSrc1->setName("ndp_0_2");
    logfile.writeName(*ndpSrc1);
    ndpSnk->setName("ndp_sink_0_2");
    logfile.writeName(*ndpSnk);

    ndpRtxScanner.registerNdp(*ndpSrc1);

    // 选择路径
    int choice = rand() % paths_0_to_2->size();
    routeout1 = new Route(*(paths_0_to_2->at(choice)));
    routeout1->add_endpoints(ndpSrc1, ndpSnk);

    routein1 = new Route(*(paths_2_to_0->at(choice)));
    routein1->add_endpoints(ndpSnk, ndpSrc1);

    ndpSrc1->connect(routeout1, routein1, *ndpSnk, 0);

    // 创建第二个连接：节点1 -> 节点2
    ndpSrc2 = new NdpSrc(NULL, NULL, eventlist, false);
    ndpSrc2->setCwnd(cwnd * Packet::data_packet_size());
    ndpSrc2->set_dst(2);
    ndpSrc2->set_flowsize(1000000); // 1MB

    NdpSink* ndpSnk2 = new NdpSink(pacers[2]);
    ndpSnk2->set_src(1);

    ndpSrc2->setName("ndp_1_2");
    logfile.writeName(*ndpSrc2);
    ndpSnk2->setName("ndp_sink_1_2");
    logfile.writeName(*ndpSnk2);

    ndpRtxScanner.registerNdp(*ndpSrc2);

    // 选择路径
    choice = rand() % paths_1_to_2->size();
    routeout2 = new Route(*(paths_1_to_2->at(choice)));
    routeout2->add_endpoints(ndpSrc2, ndpSnk2);

    routein2 = new Route(*(paths_2_to_1->at(choice)));
    routein2->add_endpoints(ndpSnk2, ndpSrc2);

    ndpSrc2->connect(routeout2, routein2, *ndpSnk2, 0);

    // 记录设置
    int pktsize = Packet::data_packet_size();
    logfile.write("# pktsize=" + ntoa(pktsize) + " bytes");
    logfile.write("# hostnicrate = " + ntoa(linkspeed/1000000) + " Mbps");
    double rtt = timeAsSec(timeFromUs(1));
    logfile.write("# rtt =" + ntoa(rtt));
    logfile.write("# Simple test: 2 senders -> 1 receiver");

    // 开始仿真
    cout << "Starting simple simulation" << endl;
    while (eventlist.doNextEvent()) {
    }

    cout << "Simple simulation done" << endl;

    // 输出统计信息
    int new_pkts1 = ndpSrc1->_new_packets_sent;
    int rtx_pkts1 = ndpSrc1->_rtx_packets_sent;
    int bounce_pkts1 = ndpSrc1->_bounces_received;

    int new_pkts2 = ndpSrc2->_new_packets_sent;
    int rtx_pkts2 = ndpSrc2->_rtx_packets_sent;
    int bounce_pkts2 = ndpSrc2->_bounces_received;

    cout << "Connection 0->2: New: " << new_pkts1 << " Rtx: " << rtx_pkts1 << " Bounced: " << bounce_pkts1 << endl;
    cout << "Connection 1->2: New: " << new_pkts2 << " Rtx: " << rtx_pkts2 << " Bounced: " << bounce_pkts2 << endl;

    // 清理资源
    delete conns;
    delete top;
    for (auto pacer : pacers) {
        delete pacer;
    }

    // 清理路径
    delete paths_0_to_2;
    delete paths_1_to_2;
    delete paths_2_to_0;
    delete paths_2_to_1;

    return 0;
}
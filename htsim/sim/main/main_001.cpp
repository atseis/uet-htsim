// #include <math.h>
// #include <string.h>
// #include <iostream>
// #include <sstream>
// #include "clock.h"
// #include "compositequeue.h"
// #include "config.h"
// #include "eventlist.h"
// #include "logfile.h"
// #include "loggers.h"
// #include "ndp.h"
// #include "network.h"
// #include "pipe.h"

#include <iostream>
#include "clock.h"
#include "config.h"
#include "eventlist.h"
#include "network.h"

class DummyTraffic : public EventSource {
public:
    DummyTraffic(EventList& eventlist) : EventSource(eventlist, "dummy") {
        eventlist.sourceIsPendingRel(*this, timeFromSec(0));
    }
    void doNextEvent() override { eventlist().sourceIsPendingRel(*this, timeFromSec(1)); }
    bool isTraffic() override { return true; }
};
using namespace std;
int main(int argc, char* argv[]) {
    EventList eventlist;
    DummyTraffic dummy(eventlist);
    Clock c(timeFromSec(1 / 10.), eventlist);
    eventlist.setEndtime(timeFromSec(5));
    cout << "开始模拟，运行5秒" << endl;
    while (eventlist.doNextEvent()) {
    }
    cout << "\n模拟结束" << endl;
    return 0;
}

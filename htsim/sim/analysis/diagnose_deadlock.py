import re
import argparse
import sys
from collections import defaultdict

def parse_sender_log(log_path):
    """
    Parses sender log (output.log) for RTO events.
    Returns a dict: {flow_id: [list of (time_us, seq_no, context)]}
    Example line: At 717.923 Uec_304_0 uecSrc ... rtx timer expired ...
    """
    rto_events = defaultdict(list)
    # Regex to capture time, flow info, and RTO event
    # Trying to be generic enough to catch variations
    rto_pattern = re.compile(r"At\s+(\d+\.?\d*)\s+.*uecSrc\s+.*flowid\s+(\d+).*rtx timer expired")
    
    try:
        with open(log_path, 'r', errors='replace') as f:
            for line in f:
                if "rtx timer expired" in line:
                    match = rto_pattern.search(line)
                    if match:
                        time_us = float(match.group(1))
                        flow_id = int(match.group(2))
                        rto_events[flow_id].append({'time': time_us, 'line': line.strip()})
    except FileNotFoundError:
        print(f"Error: Sender log file '{log_path}' not found.")
    
    return rto_events

def parse_receiver_log(log_path):
    """
    Parses receiver log (stdout.log/recv_log) for packet reception.
    Returns a dict: {flow_id: {seq_no: time_us}}
    Example line: UecSink ... recvd_bytes ... recv 11 ...
    This format depends heavily on users debug prints. 
    Assuming a line like "... flowid X ... recv Y ..." or similar.
    """
    recv_events = defaultdict(dict)
    # Identifying recv lines. Based on previous context: "recv 11"
    # Needs a regex that captures Flow ID and Seq No. 
    # Example: "flowid 10 recv 11" or similar context.
    # Adjusting based on common debug outputs seen in this project
    recv_pattern = re.compile(r"flowid\s+(\d+).*recv\s+(\d+)")
    
    try:
        with open(log_path, 'r', errors='replace') as f:
            for line in f:
                if "recv" in line:
                    match = recv_pattern.search(line)
                    if match:
                        flow_id = int(match.group(1))
                        seq_no = int(match.group(2))
                        # We might need timestamp if available at start of line
                        # Assuming standard htsim log format "Time ... msg"
                        time_match = re.match(r"\s*(\d+\.?\d*)", line)
                        time_us = float(time_match.group(1)) if time_match else 0
                        
                        if seq_no not in recv_events[flow_id]:
                             recv_events[flow_id][seq_no] = time_us
    except FileNotFoundError:
        print(f"Error: Receiver log file '{log_path}' not found.")

    return recv_events

def check_deadlock_issues(sender_log, receiver_log):
    """
    Analyzes sender and receiver logs to find potential silent deadlock events.
    Returns: List of dicts, e.g. [{'flow_id': 10, 'time': 717.9, 'type': 'Silent Packet', 'details': '...'}]
    """
    rtos = parse_sender_log(sender_log)
    recvs = parse_receiver_log(receiver_log)
    
    issues = []
    
    for flow_id, events in rtos.items():
        for rto in events:
            rto_time = rto['time']
            # We don't explicitly know WHICH seq no timed out from the generic "timer expired" message 
            # unless we parse more deep. But often the log says "rtx timer expired ... seqno X" if implemented.
            # Assuming we can broadly check: Was there a packet received BEFORE this RTO that wasn't ACKed?
            
            # Heuristic: Check for any packet received for this flow in the window [RTO - 1000us, RTO]
            # If we see a 'recv X' but then an RTO happens, it's suspicious.
            
            # Check receiver logs for this flow
            if flow_id in recvs:
                # Find recent receptions
                recent_recvs = {seq: t for seq, t in recvs[flow_id].items() if rto_time - 1000 < t < rto_time}
                if recent_recvs:
                     details_list = []
                     for seq, t in recent_recvs.items():
                         details_list.append(f"Seq {seq} @ {t}us ({rto_time - t:.2f}us pre-RTO)")
                     
                     issues.append({
                         "flow_id": flow_id,
                         "time": rto_time,
                         "type": "Silent Deadlock",
                         "details": "; ".join(details_list),
                         "rto_context": rto['line']
                     })
    return issues

def diagnose(sender_log, receiver_log):
    print(f"--- UEC Deadlock Diagnosis ---")
    print(f"Sender Log: {sender_log}")
    print(f"Receiver Log: {receiver_log}")
    
    issues = check_deadlock_issues(sender_log, receiver_log)
    
    if not issues:
        print(f"\nDiagnosis Complete. No silent deadlock events found.")
        return

    print(f"\nFound {len(issues)} potential silent deadlock events:")
    for issue in issues:
        print(f"\n[Flow {issue['flow_id']}] RTO Analysis at {issue['time']} us")
        print(f"  > Context: {issue['rto_context']}")
        print(f"  > ⚠️  SUSPICIOUS: Receiver got packets shortly before RTO (Silent?):")
        print(f"      - {issue['details']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diagnose UEC Silent Deadlocks")
    parser.add_argument("--sender_log", default="output.log", help="Path to sender log")
    parser.add_argument("--receiver_log", default="stdout.log", help="Path to receiver log")
    args = parser.parse_args()
    
    diagnose(args.sender_log, args.receiver_log)

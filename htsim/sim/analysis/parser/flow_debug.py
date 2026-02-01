import re
import pandas as pd
from typing import Dict, List, Any

def parse_flow_trace(log_content: str, target_flow_name: str) -> Dict[str, List[Any]]:
    """
    Parses stdout.log content for a specific flow, extracting detailed events 
    matched by recent plot_trace.py requirements.

    Args:
        log_content: The full content of stdout.log
        target_flow_name: The string name of the flow (e.g. "Uec_304_0")

    Returns:
        A dictionary of event lists: 
        {
            "send_t": [], "send_seq": [],
            "rtx_t": [], "rtx_seq": [],
            "ack_t": [], "ack_seq": [],
            "rto_t": [],
            "cwnd_t": [], "cwnd_val": [],
            "inflight_t": [], "inflight_val": [],
            "rtt_t": [], "delay_val": [], "raw_rtt_val": []
        }
    """
    events = {
        "send_t": [], "send_seq": [], "send_ar": [], 
        "rtx_t": [], "rtx_seq": [],
        "ack_t": [], "ack_seq": [],
        "sack_t": [], "sack_seq": [],
        "probe_t": [], "probe_seq": [], 
        "probe_recv_t": [], "probe_recv_seq": [], # [New] Probe Arrival
        "recv_t": [], "recv_seq": [],
        "rto_t": [],
        "cwnd_t": [], "cwnd_val": [],
        "inflight_t": [], "inflight_val": [],
        "rtt_t": [], "delay_val": [], "raw_rtt_val": [],
        "internal_id": [], # [New] Internal Flow ID (from flowId in log)
    }

    # Regexes from plot_trace.py
    
    # Send: "703.9 Uec_304_0 ... sending pkt 5 ..."
    p_send = re.compile(r"([\d\.]+)\s+.*sending pkt (\d+)")
    
    # Probe: "703.9 flowid 102 sendProbe _probe_seqno 1"
    # Matches: time, flowid (ignored), seqno
    p_probe = re.compile(r"([\d\.]+)\s+.*sendProbe.*_probe_seqno\s+(\d+)")

    # Probe Receive: "703.9 flowid 102 receiveProbe _probe_seqno 1"
    # Matches: time, seqno
    p_probe_recv = re.compile(r"([\d\.]+)\s+.*receiveProbe.*_probe_seqno\s+(\d+)")

    # RTX: "717.9 Uec_304_0 ... sending rtx pkt 6 ..."
    p_rtx = re.compile(r"([\d\.]+)\s+.*sending rtx pkt (\d+)")
    
    # ACK: "At 720.5 ... processAck cum_ack: 5 ..."
    p_ack = re.compile(r"At ([\d\.]+)\s+.*processAck.*cum_ack:\s*(\d+)")
    
    # SACK: "    Sack 10 flow Uec_304_0"
    p_sack = re.compile(r"\s+Sack (\d+)")

    # RTO: "rtx timer expired ... now time is 703.9" 
    p_rto = re.compile(r".*rtx timer expired.*now time is ([\d\.]+)")

    # Flow Start: "Flow Uec_304_0 flowId 23 uecSrc 22 starting at 0"
    # Captures: Name, FlowID, SrcID values (dynamic)
    p_flow_start = re.compile(r"Flow\s+(\S+)\s+flowId\s+(\d+)\s+uecSrc\s+(\d+)\s+.*starting")
    
    # State (from Send): "... cwnd 4150 ... in_flight 4150"
    p_state = re.compile(r"([\d\.]+)\s+.*cwnd (\d+).*in_flight (\d+)")
    
    # State (from ACK): "At 720.5 ... cwnd 10623 flightsize 8300"
    p_ack_state = re.compile(r"At ([\d\.]+)\s+.*cwnd (\d+).*flightsize (\d+)")

    # RTT info: "At ... delay 12.5 ... raw rtt 124.5"
    p_rtt_info = re.compile(r"At ([\d\.]+)\s+.*delay ([\d\.]+).*raw rtt (\d+)")

    last_ack_time = None
    current_internal_id = None # Initialize current_internal_id

    lines = log_content.splitlines()
    for line in lines:
        # 1. Update Internal ID Mapping
        m_start = p_flow_start.search(line)
        if m_start:
            fname = m_start.group(1)
            fid = int(m_start.group(2))
            sid = int(m_start.group(3)) # SrcID (Component ID)
            
            if fname == target_flow_name:
                current_internal_id = fid
                events["internal_id"].append(fid) # Store FlowId as InternalID
                # Found our target starting (or restarting).
            elif current_internal_id == fid:
                # [Crucial] ID Reuse Detection
                # The ID we were tracking (fid) is now assigned to a DIFFERENT flow (fname).
                # Only happens if the previous flow ended and ID was recycled.
                # Stop tracking to avoid mixing logs.
                current_internal_id = None
        
        # 2. Filter lines: Must contain Flow Name OR (Current ID AND "flowid {id}")
        # Note: Standard logs have Name. Probe logs have ID.
        has_name = target_flow_name in line
        has_id = (current_internal_id is not None) and (f"flowid {current_internal_id}" in line)
        
        if not (has_name or has_id):
            continue

        # --- Parse Send ---
        # Note: "sending rtx pkt" matches "sending pkt" regex if not careful?
        # "sending pkt" regex is: `.*sending pkt (\d+)`
        # "sending rtx pkt" regex is: `.*sending rtx pkt (\d+)`
        # In plot_trace.py: `if m_send and "rtx" not in line:`
        
        m_send = p_send.search(line)
        if m_send and "rtx" not in line:
            try:
                events["send_t"].append(float(m_send.group(1)))
                events["send_seq"].append(int(m_send.group(2)))
                
                # [New] Parse AR Flag (ACK Request)
                # Matches "ack request 1" or "ar 1"
                m_ar = re.search(r"(?:ack request|ar)\s+(\d)", line)
                if m_ar:
                     events["send_ar"].append(int(m_ar.group(1)))
                else:
                     events["send_ar"].append(0) # Default to 0 if not found
            except ValueError: pass

        # --- Parse Send Probe ---
        # Only parse if line contains "sendProbe" AND matches our ID
        if "sendProbe" in line:
            m_probe = p_probe.search(line)
            if m_probe:
                # Double check ID if usage
                # The regex doesn't extract ID, but we filtered by `has_id`.
                # Wait, p_probe is generic. We trust `has_id` filter.
                try:
                    events["probe_t"].append(float(m_probe.group(1)))
                    events["probe_seq"].append(int(m_probe.group(2)))
                except ValueError: pass

        # --- Parse Probe Receive ---
        m_probe_recv = p_probe_recv.search(line)
        if m_probe_recv:
            try:
                events["probe_recv_t"].append(float(m_probe_recv.group(1)))
                events["probe_recv_seq"].append(int(m_probe_recv.group(2)))
            except ValueError: pass

        # --- Parse RTX ---
        m_rtx = p_rtx.search(line)
        if m_rtx:
            try:
                events["rtx_t"].append(float(m_rtx.group(1)))
                events["rtx_seq"].append(int(m_rtx.group(2)))
            except ValueError: pass

        # --- Parse ACK ---
        m_ack = p_ack.search(line)
        if m_ack:
            try:
                t = float(m_ack.group(1))
                seq = int(m_ack.group(2))
                events["ack_t"].append(t)
                events["ack_seq"].append(seq)
                last_ack_time = t # Update context for subsequent SACKs
            except ValueError: pass
        
        # --- Parse SACK ---
        if "Sack" in line and last_ack_time is not None:
             m_sack = p_sack.search(line)
             if m_sack:
                 try:
                     events["sack_t"].append(last_ack_time)
                     events["sack_seq"].append(int(m_sack.group(1)))
                 except ValueError: pass

        # --- Parse Recv (Sink) ---
        # Look for "recv X" in lines associated with this flow
        # Regex: `... recv (\d+) ...` (simple) or `... recv\s+(\d+)`
        # We rely on timestamp being at start of line for HTSim logs: `703.9 ...`
        if "recv" in line:
             m_recv = re.search(r"([\d\.]+)\s+.*recv\s+(\d+)", line)
             if m_recv:
                 try:
                     events["recv_t"].append(float(m_recv.group(1)))
                     events["recv_seq"].append(int(m_recv.group(2)))
                 except ValueError: pass

        # --- Parse RTO ---
        m_rto = p_rto.search(line)
        if m_rto:
            try:
                events["rto_t"].append(float(m_rto.group(1)))
            except ValueError: pass

        # --- Parse CWND & InFlight (From Send Log) ---
        # Matches lines starting with timestamp (like send logs)
        if "sending" in line:
            m_state = p_state.search(line)
            if m_state:
                try:
                    t = float(m_state.group(1))
                    c = int(m_state.group(2))
                    i = int(m_state.group(3))
                    events["cwnd_t"].append(t)
                    events["cwnd_val"].append(c)
                    events["inflight_t"].append(t)
                    events["inflight_val"].append(i)
                except ValueError: pass

        # --- Parse CWND & InFlight (From Ack Log) ---
        # Matches lines starting with "At"
        if "At " in line:
            m_ack_st = p_ack_state.search(line)
            if m_ack_st:
                try:
                    t = float(m_ack_st.group(1))
                    c = int(m_ack_st.group(2))
                    i = int(m_ack_st.group(3))
                    events["cwnd_t"].append(t)
                    events["cwnd_val"].append(c)
                    events["inflight_t"].append(t)
                    events["inflight_val"].append(i)
                except ValueError: pass

            # --- Parse RTT (Delay & Raw) ---
            m_rtt = p_rtt_info.search(line)
            if m_rtt:
                try:
                    t = float(m_rtt.group(1))
                    delay_us = float(m_rtt.group(2))
                    raw_ps = float(m_rtt.group(3))
                    raw_us = raw_ps / 1_000_000.0
                    
                    if raw_us > 0:
                        events["rtt_t"].append(t)
                        events["delay_val"].append(delay_us)
                        events["raw_rtt_val"].append(raw_us)
                except ValueError: pass

    return events

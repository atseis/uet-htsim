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
        "send_t": [], "send_seq": [],
        "rtx_t": [], "rtx_seq": [],
        "ack_t": [], "ack_seq": [],
        "rto_t": [],
        "cwnd_t": [], "cwnd_val": [],
        "inflight_t": [], "inflight_val": [],
        "rtt_t": [], "delay_val": [], "raw_rtt_val": [],
    }

    # Regexes from plot_trace.py
    # Note: We rely on the log line containing the flow ID, so we filter lines first.
    
    # Send: "703.9 Uec_304_0 ... sending pkt 5 ..."
    p_send = re.compile(r"([\d\.]+)\s+.*sending pkt (\d+)")
    
    # RTX: "717.9 Uec_304_0 ... sending rtx pkt 6 ..."
    p_rtx = re.compile(r"([\d\.]+)\s+.*sending rtx pkt (\d+)")
    
    # ACK: "At 720.5 ... processAck cum_ack: 5 ..."
    p_ack = re.compile(r"At ([\d\.]+)\s+.*processAck.*cum_ack:\s*(\d+)")
    
    # RTO: "rtx timer expired ... now time is 703.9" 
    # Usually log has Flow Name associated? "flow Uec_304_0"
    p_rto = re.compile(r".*rtx timer expired.*now time is ([\d\.]+)")

    # State (from Send): "... cwnd 4150 ... in_flight 4150"
    p_state = re.compile(r"([\d\.]+)\s+.*cwnd (\d+).*in_flight (\d+)")
    
    # State (from ACK): "At 720.5 ... cwnd 10623 flightsize 8300"
    # Note: Regex in plot_trace.py was: re.compile(r"At ([\d\.]+)\s+.*cwnd (\d+).*flightsize (\d+)")
    p_ack_state = re.compile(r"At ([\d\.]+)\s+.*cwnd (\d+).*flightsize (\d+)")

    # RTT info: "At ... delay 12.5 ... raw rtt 124.5"
    p_rtt_info = re.compile(r"At ([\d\.]+)\s+.*delay ([\d\.]+).*raw rtt (\d+)")

    lines = log_content.splitlines()
    for line in lines:
        # Optimization: Only process lines related to expected events
        # But we must be careful: "rtx timer expired" might not have flow name in the SAME line segment if grep wasn't used?
        # Actually UecSrc log usually includes flow name.
        # "uecSrc 23 rtx timer expired for seqno 11 flow Uec_304_0 packet sent at ..."
        
        if target_flow_name not in line:
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
                events["ack_t"].append(float(m_ack.group(1)))
                events["ack_seq"].append(int(m_ack.group(2)))
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

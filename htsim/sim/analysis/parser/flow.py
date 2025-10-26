# parser/flow.py
import re
import pandas as pd
from typing import List, Dict, Optional, Union

def parse_flow_events(text: str) -> pd.DataFrame:
    """
    解析parse_output的ASCII输出，提取流事件信息
    
    Args:
        text: parse_output的ASCII输出文本
        
    Returns:
        包含流事件信息的DataFrame，字段包括:
        flow_id, src, dst, start_time, finish_time, size_bytes, fct_ns
    """
    # 初始化存储流信息的字典
    flows = {}
    
    # 正则表达式匹配流事件
    # 匹配开始事件: Type FLOW_EVENT SrcID xxx Ev START FlowID xxx
    start_pattern = r'(\d+\.\d+)\s+Type\s+FLOW_EVENT\s+SrcID\s+(\d+)\s+Ev\s+START\s+FlowID\s+(\d+)'
    # 匹配结束事件: Type FLOW_EVENT SrcID xxx Ev FINISH FlowID xxx Bytes xxx Pkts xxx
    finish_pattern = r'(\d+\.\d+)\s+Type\s+FLOW_EVENT\s+SrcID\s+(\d+)\s+Ev\s+FINISH\s+FlowID\s+(\d+)\s+Bytes\s+(\d+)\s+Pkts\s+(\d+)'
    
    # 查找所有开始事件
    for match in re.finditer(start_pattern, text):
        time = float(match.group(1)) * 1e9  # 转换为纳秒
        src_id = match.group(2)
        flow_id = match.group(3)
        
        flows[flow_id] = {
            'flow_id': flow_id,
            'src_id': src_id,
            'start_time': time,
            'finish_time': None,
            'size_bytes': None,
            'packets': None,
            'fct_ns': None
        }
    
    # 查找所有结束事件
    for match in re.finditer(finish_pattern, text):
        time = float(match.group(1)) * 1e9  # 转换为纳秒
        src_id = match.group(2)
        flow_id = match.group(3)
        size_bytes = int(match.group(4))
        packets = int(match.group(5))
        
        # 如果流ID不存在，创建一个新条目（可能没有捕获到开始事件）
        if flow_id not in flows:
            flows[flow_id] = {
                'flow_id': flow_id,
                'src_id': src_id,
                'start_time': None,
                'finish_time': None,
                'size_bytes': None,
                'packets': None,
                'fct_ns': None
            }
        
        flows[flow_id]['finish_time'] = time
        flows[flow_id]['size_bytes'] = size_bytes
        flows[flow_id]['packets'] = packets
        
        # 如果有开始时间，计算FCT
        if flows[flow_id]['start_time'] is not None:
            flows[flow_id]['fct_ns'] = flows[flow_id]['finish_time'] - flows[flow_id]['start_time']
    
    # 转换为DataFrame
    df = pd.DataFrame(list(flows.values()))
    
    # 只保留有结束时间的流
    df = df.dropna(subset=['finish_time'])
    
    return df

def parse_flow_events_from_file(file_path: str) -> pd.DataFrame:
    """
    从文件中读取parse_output的ASCII输出，并解析流事件信息
    
    Args:
        file_path: 文件路径
        
    Returns:
        包含流事件信息的DataFrame
    """
    with open(file_path, 'r') as f:
        text = f.read()
    
    return parse_flow_events(text)
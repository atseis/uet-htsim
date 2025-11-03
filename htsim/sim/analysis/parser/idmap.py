import re
from types import MappingProxyType
from typing import Protocol
from .. import runner

FLOW_PATTERN = re.compile(r"^([^_]+)_([0-9]+)_([0-9]+)$")


def parse_flow_id(value: str):
    m = FLOW_PATTERN.match(value)
    if not m:
        return None
    proto, src, sink = m.groups()
    return proto, src, sink


def build_from_index(mapping: dict[int, str]):
    flows_by_src = {}
    flows_by_sink = {}
    for id, value in mapping.items():
        parsed = parse_flow_id(value)
        if not parsed:
            continue
        proto, src, sink = parsed
        flows_by_src.setdefault(int(src), []).append(id)
        flows_by_sink.setdefault(int(sink), []).append(id)
    return flows_by_src, flows_by_sink


def get_flows_from_src(flows_by_src, src):
    return flows_by_src.get(src, [])


def get_flows_from_sink(flows_by_sink, sink):
    return flows_by_sink.get(sink, [])

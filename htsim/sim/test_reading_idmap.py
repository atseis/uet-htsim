from analysis.runner import load_idmap
from analysis.parser import idmap


idmap_example = "/root/code/uet-htsim/htsim/sim/results/OriginExps/spray_comparison/conns1024_nodes1024_paths128_randseed13/idmap.txt"


d = load_idmap(idmap_example)

flows_by_src, flows_by_sink = idmap.build_from_index(d)


# print(flows_by_src[700])
# print(flows_by_sink[276])

print(flows_by_src)
print(flows_by_sink)

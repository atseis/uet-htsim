from ptpython.ipython import embed
from analysis.parser import collective
from pathlib import Path

folder = Path("/root/code/uet-htsim/htsim/sim/results/SimpleTests/cct_algorithms")

butterfly = folder / "conns64_flowsize4MB_groups27_paths128_typeallreduce_butterfly"
ring = folder / "conns432_flowsize256KB_paths128_typeallreduce"


# butterfly = collective.get_collective_ccts_from_directory(butterfly)
# ring = collective.get_collective_ccts_from_directory(ring)
# butterfly = collective.get_collective_details_from_directory(butterfly)
# ring = collective.get_collective_details_from_directory(ring)

#
# print("butterfly: ")
# print(butterfly)
# print("ring: ")
# print(ring)
#


embed()

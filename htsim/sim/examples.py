import analysis.runner as runner
from analysis.parser import flow
from analysis.config.traffic_patterns import generate_allreduce_traffic
import yaml
from analysis.config import experiment
import sys


SAMPLE_LOG = "./out/Debug/logout.dat"  # 请替换为实际的日志文件路径

# flows = runner.analyze_by_purpose(SAMPLE_LOG, runner.AnalysisType.FLOW_INFO)
# flows = flow.parse_flow_events(flows)
# print(flows)
# config_file = "./analysis/config/oblivious_trim_ecn.yaml.yaml"
if __name__ == "__main__":
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
        with open(config_file, "r") as f:
            config = yaml.safe_load(f)
        experiment.run_experiment(config)
    else:
        print("Usage: python examples.py <config_file>")
    # file = generate_allreduce_traffic(
    #     nodes=16, conns=16, groupsize=16, flowsize="2MB", locality=0, randseed=13
    # )
    # print(file)

import analysis.runner as runner
from analysis.parser import flow
from analysis.config.traffic_patterns import generate_allreduce_traffic
import yaml
from analysis.config import experiment
import sys
import argparse


# SAMPLE_LOG = "./out/Debug/logout.dat"  # 请替换为实际的日志文件路径

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run network simulation experiments.")
    parser.add_argument("config_file", help="Path to the YAML configuration file.")
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force rerun all experiments, ignoring existing status.",
    )
    parser.add_argument(
        "--continue",
        "-c",
        dest="continue_on_error",
        action="store_true",
        help="Continue running other experiments even if one fails.",
    )
    args = parser.parse_args()

    experiment.main(args.config_file, args.force, args.continue_on_error)
    # experiment.main("experiments/spray_comparison.yaml", True, True)

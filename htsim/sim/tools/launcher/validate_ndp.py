import json
import argparse
from itertools import product
import subprocess
import os
import shutil
from pathlib import Path

# Get the directory of this script
SCRIPT_DIR = Path(__file__).parent.resolve()


def resolve_script_path(relative_path):
    """Resolve a path relative to this script's directory"""
    return (SCRIPT_DIR / relative_path).resolve()


def delete_folder_contents(folder_path):
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")


def get_global_config(global_parameters):
    global_string = ""
    global_string += f"_size_topo{global_parameters['topology_sizes']}"
    return global_string


def get_file_to_run(name_exp, parameters_experiment, global_params, args):
    dir = f"{name_exp}_size{global_params['topology_sizes']}/tmp"
    cm_name = ""
    output_file = ""
    
    if name_exp == "permutation":
        cm_name = f"{args.output_folder}/{dir}/permutation_size{parameters_experiment['message_size_bytes']}B.cm"
        output_file = f"{args.output_folder}/{dir}/permutation_size{parameters_experiment['message_size_bytes']}B_"
        gen_permutation_path = resolve_script_path("../../htsim/sim/datacenter/connection_matrices/gen_permutation.py")
        cmd_to_run_cm_file = (
            "python {} {} {} {} {} 0 42".format(
                gen_permutation_path,
                cm_name,
                global_params["topology_sizes"],
                global_params["topology_sizes"],
                parameters_experiment["message_size_bytes"],
            )
        )
        try:
            print(f"Creating CM named {cmd_to_run_cm_file}")
            subprocess.run(cmd_to_run_cm_file, shell=True, check=True)
        except subprocess.CalledProcessError as e:
            print(f"An error occurred while running the command: {e}")
    else:
        print("Error: Invalid experiment name")
        exit(1)

    return cm_name, output_file


def read_json_file(file_path):
    with open(file_path, "r") as file:
        data = json.load(file)
    return data


def get_global_combinations(global_parameters):
    keys = global_parameters.keys()
    values = (
        global_parameters[key]
        if isinstance(global_parameters[key], list)
        else [global_parameters[key]]
        for key in keys
    )
    return [dict(zip(keys, combination)) for combination in product(*values)]


def run_experiment(experiment_name, global_params, subparams, args):
    print(
        f"Running {experiment_name} with global parameters: {global_params} and subparameters: {subparams}"
    )

    connection_matrix, output_file = get_file_to_run(
        experiment_name, subparams, global_params, args
    )
    output_file, logout_file = (
        output_file + get_global_config(global_params) + ".out",
        output_file + get_global_config(global_params) + ".logout.dat",
    )

    # Launch NDP experiment
    command = "../../htsim/sim/build/datacenter/htsim_ndp -nodes {} -tm {} -o {} -end 10000 -strat perm {} > {}".format(
        global_params["topology_sizes"],
        connection_matrix,
        logout_file,
        args.command_flags,
        output_file,
    )
    command = " ".join(command.split())
    print(f"Executing: {command}")
    try:
        subprocess.run(command, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while running the command: {e}")


def handle_experiment(experiment, global_combinations, global_params, args):
    for topology_size in global_params["topology_sizes"]:
        directory = os.path.join(
            args.output_folder,
            f"{experiment['name']}_size{topology_size}",
        )
        if not os.path.exists(directory):
            os.makedirs(directory)
        delete_folder_contents(directory)
        
        directory_tmp = os.path.join(directory, "tmp")
        if not os.path.exists(directory_tmp):
            os.makedirs(directory_tmp)
        delete_folder_contents(directory_tmp)
        
        subparam_keys = [key for key in experiment.keys() if key != "name"]
        subparam_values = (
            experiment[key]
            if isinstance(experiment[key], list)
            else [experiment[key]]
            for key in subparam_keys
        )
        for subparam_combination in product(*subparam_values):
            subparams = dict(zip(subparam_keys, subparam_combination))
            glob_params = {}
            glob_params["topology_sizes"] = topology_size
            run_experiment(experiment["name"], glob_params, subparams, args)


def launch_experiments(experiments, global_combinations, global_parameters, args):
    print("\nExperiments:")
    for experiment in experiments:
        print(f"Experiment Name: {experiment['name']}")
        handle_experiment(experiment, global_combinations, global_parameters, args)


def main():
    parser = argparse.ArgumentParser(
        description="NDP validation testing framework"
    )
    parser.add_argument(
        "--config_json_file", required=True, help="Path to the JSON configuration file"
    )
    parser.add_argument(
        "--output_folder",
        required=False,
        help="Output folder for results",
        default="results/ndp",
    )
    parser.add_argument(
        "--command_flags",
        required=False,
        help='Additional command flags',
        default="",
    )

    args = parser.parse_args()

    # Create output directory
    if not os.path.exists(args.output_folder):
        os.makedirs(args.output_folder)

    # Read configuration
    data = read_json_file(args.config_json_file)

    # Print global parameters
    global_parameters = data["global_parameters"]
    print("Global Parameters:")
    for key, value in global_parameters.items():
        print(f"  {key.replace('_', ' ').capitalize()}: {value}")

    # Get all global parameter combinations
    global_combinations = get_global_combinations(global_parameters)

    # Launch experiments
    launch_experiments(
        data["experiments"], global_combinations, global_parameters, args
    )


if __name__ == "__main__":
    main()
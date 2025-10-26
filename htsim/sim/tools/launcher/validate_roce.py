import json
import argparse
from itertools import product
import subprocess
import os
import shutil

# Get absolute path to datacenter directory
DATACENTER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
    # Extract single value if it's a list
    topo_size = global_parameters['topology_sizes']
    if isinstance(topo_size, list):
        topo_size = topo_size[0]
    global_string += f"_size_topo{topo_size}"
    if "queue_size" in global_parameters:
        # Extract single value if it's a list
        qsize = global_parameters['queue_size']
        if isinstance(qsize, list):
            qsize = qsize[0]
        global_string += f"_qsize{qsize}"
    if "queue_type" in global_parameters:
        # Extract single value if it's a list
        qtype = global_parameters['queue_type']
        if isinstance(qtype, list):
            qtype = qtype[0]
        global_string += f"_qtype{qtype}"
    return global_string


def get_file_to_run(name_exp, parameters_experiment, global_params, args):
    dir = f"{name_exp}_size{global_params['topology_sizes']}/tmp"
    cm_name = ""
    output_file = ""
    
    if name_exp == "permutation":
        cm_name = f"{args.output_folder}/{dir}/permutation_size{parameters_experiment['message_size_bytes']}B.cm"
        output_file = f"{args.output_folder}/{dir}/permutation_size{parameters_experiment['message_size_bytes']}B_"
        cmd_to_run_cm_file = (
            "python {}/connection_matrices/gen_permutation.py {} {} {} {} 0 42".format(
                DATACENTER_DIR,
                cm_name,
                global_params["topology_sizes"],
                global_params["topology_sizes"],
                parameters_experiment["message_size_bytes"],
            )
        )
        try:
            print(f"Creating CM named {cmd_to_run_cm_file}")
            result = subprocess.run(cmd_to_run_cm_file, shell=True, check=True, capture_output=True, text=True)
            print(f"CM creation stdout: {result.stdout}")
            if result.stderr:
                print(f"CM creation stderr: {result.stderr}")
        except subprocess.CalledProcessError as e:
            print(f"An error occurred while running the command: {e}")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
    elif name_exp == "incast":
        cm_name = f"{args.output_folder}/{dir}/incast_{parameters_experiment['ratio']}to1_size{parameters_experiment['message_size_bytes']}B.cm"
        output_file = f"{args.output_folder}/{dir}/incast_{parameters_experiment['ratio']}to1_size{parameters_experiment['message_size_bytes']}B_"
        cmd_to_run_cm_file = (
            "python {}/connection_matrices/gen_incast.py {} {} {} {} 0 42 1".format(
                DATACENTER_DIR,
                cm_name,
                global_params["topology_sizes"],
                parameters_experiment["ratio"],
                parameters_experiment["message_size_bytes"],
            )
        )
        try:
            print(f"Creating CM named {cmd_to_run_cm_file}")
            result = subprocess.run(cmd_to_run_cm_file, shell=True, check=True, capture_output=True, text=True)
            print(f"CM creation stdout: {result.stdout}")
            if result.stderr:
                print(f"CM creation stderr: {result.stderr}")
        except subprocess.CalledProcessError as e:
            print(f"An error occurred while running the command: {e}")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
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

    # Build RoCE command
    # Extract single value for topology size
    topo_size = global_params['topology_sizes']
    if isinstance(topo_size, list):
        topo_size = topo_size[0]
    
    command_parts = [
        f"{DATACENTER_DIR}/htsim_roce",
        f"-nodes {topo_size}",
        f"-tm {connection_matrix}",
        f"-o {logout_file}",
        "-end 10000",
        "-strat single"  # RoCE only supports single path and ECMP_FIB strategies
    ]
    
    # Add optional parameters
    if "queue_size" in global_params:
        qsize = global_params['queue_size']
        if isinstance(qsize, list):
            qsize = qsize[0]
        command_parts.append(f"-q {qsize}")
    if "queue_type" in global_params:
        qtype = global_params['queue_type']
        if isinstance(qtype, list):
            qtype = qtype[0]
        command_parts.append(f"-queue_type {qtype}")
    
    command_parts.append(args.command_flags)
    
    # First run without output redirection to check for errors
    test_command = " ".join(command_parts)
    print(f"Testing command: {test_command}")
    try:
        result = subprocess.run(test_command, shell=True, check=True, capture_output=True, text=True, timeout=30)
        print(f"Command successful, stdout: {len(result.stdout)} chars, stderr: {len(result.stderr)} chars")
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}")
        print(f"STDOUT: {e.stdout}")
        print(f"STDERR: {e.stderr}")
        return
    except subprocess.TimeoutExpired:
        print("Command timed out")
        return
    
    # Now run with output redirection
    command_parts.append(f"> {output_file}")
    command = " ".join(command_parts)
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
            # Copy other global parameters
            for key in global_params:
                if key != "topology_sizes":
                    glob_params[key] = global_params[key]
            run_experiment(experiment["name"], glob_params, subparams, args)


def launch_experiments(experiments, global_combinations, global_parameters, args):
    print("\nExperiments:")
    for experiment in experiments:
        print(f"Experiment Name: {experiment['name']}")
        handle_experiment(experiment, global_combinations, global_parameters, args)


def main():
    parser = argparse.ArgumentParser(
        description="RoCE validation testing framework"
    )
    parser.add_argument(
        "--config_json_file", required=True, help="Path to the JSON configuration file"
    )
    parser.add_argument(
        "--output_folder",
        required=False,
        help="Output folder for results",
        default="results/roce",
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
#!/usr/bin/env python3
"""
Plotting module that extracts parameters directly from simulation output files
Input: simulation output file (.out)
Output: generates visualization plots
"""

import sys
import os
import argparse
import re

def extract_parameters_from_out(out_file_path):
    """Extract simulation parameters from .out or .tmp file"""
    params = {
        'nodes': None,
        'conns': None,
        'strategy': 'perm',  # Default strategy
        'cwnd': 50,          # Default initial window
        'parallel': 1,       # Default parallel connections
        'flow_size_bytes': None
    }
    
    try:
        with open(out_file_path, 'r') as f:
            content = f.read()
            
            # Extract nodes and connections - try both formats
            # First try the out file format: no_of_nodes X, no_of_conns Y
            nodes_match = re.search(r'no_of_nodes (\d+)', content)
            if nodes_match:
                params['nodes'] = int(nodes_match.group(1))
            
            conns_match = re.search(r'no_of_conns (\d+)', content)
            if conns_match:
                params['conns'] = int(conns_match.group(1))
            
            # If not found, try the alternative format: Nodes: X Connections: Y
            if params['nodes'] is None or params['conns'] is None:
                nodes_match = re.search(r'Nodes: (\d+) Connections: (\d+)', content)
                if nodes_match:
                    params['nodes'] = int(nodes_match.group(1))
                    params['conns'] = int(nodes_match.group(2))
            
            # If still not found, try to get from filename pattern
            if params['conns'] is None:
                conns_match = re.search(r'_(\d+)conns', out_file_path)
                if conns_match:
                    params['conns'] = int(conns_match.group(1))
            
            # Extract cwnd - try both formats
            cwnd_match = re.search(r'cwnd (\d+)', content)
            if cwnd_match:
                params['cwnd'] = int(cwnd_match.group(1))
            
            # Extract flow size from connection matrix filename
            cm_match = re.search(r'connection matrix.*?([^\s]+\.cm)', content)
            if cm_match:
                cm_filename = cm_match.group(1)
                size_match = re.search(r'size(\d+)B', cm_filename)
                if size_match:
                    params['flow_size_bytes'] = int(size_match.group(1))
            
            # Extract strategy from filename or content
            if 'perm' in out_file_path or 'perm' in content:
                params['strategy'] = 'perm'
            elif 'ecmp' in out_file_path.lower() or 'ecmp' in content.lower():
                params['strategy'] = 'ecmp'
            
    except Exception as e:
        print(f"Error reading out file: {e}")
        return None
    
    return params

def plot_overlap_from_out(out_file_path, cm_file_path, params, output_dir="."):
    """Process simulation output to generate overlap data from .out file"""
    
    if not os.path.exists(cm_file_path):
        print(f"Error: Connection matrix file {cm_file_path} not found")
        return False
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Read connection matrix to build flow information
    triggers = {}  # map of trigger id to flow id
    starts = {}    # map of flow id to trigger
    srcs = {}      # flow id to src
    dsts = {}      # flow id to dst
    dstcounts = {} # dsts to refcount
    srclist = []
    srcset = set()
    
    with open(cm_file_path, "r") as file:
        for line in file:
            if "->" in line:
                parts = line.split()
                p2 = parts[0].split("-")
                src = p2[0]
                dst = p2[1][1:]
                
                assert parts[1] == "id"
                flow_id = parts[2]
                srcs[flow_id] = src
                dsts[flow_id] = dst
                dstcounts[dst] = 0
                
                if src not in srcset:
                    srclist.append(src)
                    srcset.add(src)
                
                if parts[3] == "trigger":
                    trigger = parts[4]
                    triggers[trigger] = flow_id
                
                if "send_done" in line:
                    assert parts[7] == "send_done_trigger"
                    sdt = parts[8]
                    starts[flow_id] = sdt
    
    # Process simulation output from .out file
    output_filename = os.path.join(output_dir, f"incast_{params['nodes']}_{params['conns']}_{params['strategy']}_{params['cwnd']}iw_{params['parallel']}par.tmp")
    
    with open(out_file_path, "r") as infile, open(output_filename, "w") as outfile:
        prevtime = -4000
        count = 0
        
        for line in infile:
            if "startflow" in line:
                parts = line.split()
                flowid = parts[1]
                p2 = flowid.split('_')
                if len(p2) >= 3:
                    dst = p2[2]
                    if dst in dstcounts:
                        dstcounts[dst] += 1
                
            if "finished" in line and ("flowId" in line or "flow_id" in line):
                parts = line.split()
                if len(parts) >= 7:
                    try:
                        # Find the index of 'finished'
                        finished_idx = parts.index('finished')
                        if finished_idx + 2 < len(parts):
                            t = float(parts[finished_idx + 2])
                            
                            # Find flow_id - handle both formats
                            flow_id = None
                            if "flowId" in line:
                                # Format: flowId X
                                flow_id_idx = parts.index('flowId') + 1
                                if flow_id_idx < len(parts):
                                    flow_id = parts[flow_id_idx]
                            elif "flow_id" in line:
                                # Format: flow_id X  
                                flow_id_idx = parts.index('flow_id') + 1
                                if flow_id_idx < len(parts):
                                    flow_id = parts[flow_id_idx]
                            
                            if flow_id and flow_id in dsts:
                                dst = dsts[flow_id]
                                if dst in dstcounts:
                                    dstcounts[dst] -= 1
                            
                            count += 1
                            if t - prevtime > 4000:
                                count = 0
                                prevtime = t
                                for j, node in enumerate(srclist, 1):
                                    if node in dstcounts:
                                        print(t, j, dstcounts[node], file=outfile)
                    except (ValueError, IndexError):
                        continue
    
    return True

def process_incast_color(input_file, target_parallel, output_dir="."):
    """Add color coding based on concurrency levels"""
    if not os.path.exists(input_file):
        print(f"Error: Input file {input_file} not found")
        return None
    
    # Ensure input file is in output directory
    if not os.path.isabs(input_file) and not input_file.startswith(output_dir + "/"):
        input_file = os.path.join("output", os.path.basename(input_file))
    
    output_file = os.path.join(output_dir, os.path.basename(input_file).replace(".tmp", ".color.tmp"))
    
    with open(input_file, "r") as infile, open(output_file, "w") as outfile:
        for line in infile:
            parts = line.split()
            if len(parts) < 3:
                continue
            
            height = float(parts[2])
            if height <= target_parallel:
                col = 0
            elif height <= 1.5 * target_parallel:
                col = 1
            elif height <= 2 * target_parallel:
                col = 2
            else:
                col = 3
            
            print(parts[0], parts[1], parts[2], col, file=outfile)
    
    return output_file

def generate_gnuplot_script(params, flow_size_mb=None, output_dir="."):
    """Generate gnuplot script for visualization"""
    if flow_size_mb is None and params.get('flow_size_bytes'):
        flow_size_mb = params['flow_size_bytes'] / (1024 * 1024)
    else:
        flow_size_mb = flow_size_mb or 1.0
    
    # Build file names
    svg_file = os.path.join(output_dir, f'incast_{params["nodes"]}_{params["conns"]}_{params["strategy"]}_{params["cwnd"]}iw_{params["parallel"]}par.svg')
    color_file = os.path.join(output_dir, f'incast_{params["nodes"]}_{params["conns"]}_{params["strategy"]}_{params["cwnd"]}iw_{params["parallel"]}par.color.tmp')
    
    script_content = f'''set terminal svg enhanced background rgb "white"
set output "{svg_file}"
set title "{params['conns']} node sequential all-to-all, {params['nodes']} fat tree, {params['strategy']} strategy, {params['cwnd']} pkt IW, {flow_size_mb:.1f}MB flow size" offset 0,-3
set zlabel "No of incoming flows" rotate parallel offset 1,0
set ylabel "Time (ms)"
set xlabel "Receiver rank"
set ytics 0, 20, 160
set view 40,30
set size 1,1.1
set xrange [0:{params['conns']}]
set xyplane 0
unset colorbox
set palette defined ( 0 "blue", 1 "orange", 2 "magenta", 3 "red")
splot "{color_file}" using 2:($1/1000):3:4 w i lw 1 lc palette notitle
'''
    
    script_filename = os.path.join(output_dir, f"incast_{params['nodes']}_{params['conns']}_{params['strategy']}_{params['cwnd']}iw_{params['parallel']}par.gp")
    with open(script_filename, "w") as f:
        f.write(script_content)
    
    return script_filename

def main():
    parser = argparse.ArgumentParser(description="Plot all-to-all experiment results from .out and .cm files")
    parser.add_argument("out_file", help="Simulation output file (.out)")
    parser.add_argument("cm_file", help="Connection matrix file (.cm)")
    parser.add_argument("--parallel", type=int, default=1, help="Parallel connections (default: 1)")
    parser.add_argument("--cwnd", type=int, help="Initial window size (override auto-detection)")
    parser.add_argument("--strategy", help="Spray strategy (override auto-detection)")
    parser.add_argument("--flow-size", type=float, help="Flow size in MB (override auto-detection)")
    parser.add_argument("-o", "--output-dir", default="output", help="Output directory (default: output)")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.out_file):
        print(f"Error: Output file {args.out_file} not found")
        return 1
    
    if not os.path.exists(args.cm_file):
        print(f"Error: Connection matrix file {args.cm_file} not found")
        return 1
    
    # Step 1: Extract parameters from .out file
    print("Extracting parameters from simulation output...")
    params = extract_parameters_from_out(args.out_file)
    
    if not params or params['nodes'] is None or params['conns'] is None:
        print("Error: Could not extract required parameters from out file")
        return 1
    
    # Override auto-detected parameters if provided
    if args.parallel:
        params['parallel'] = args.parallel
    if args.cwnd:
        params['cwnd'] = args.cwnd
    if args.strategy:
        params['strategy'] = args.strategy
    
    print(f"Detected parameters: nodes={params['nodes']}, conns={params['conns']}, "
          f"strategy={params['strategy']}, cwnd={params['cwnd']}, parallel={params['parallel']}")
    
    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Step 2: Process simulation output to generate overlap data
    print("Processing simulation output...")
    if not plot_overlap_from_out(args.out_file, args.cm_file, params, args.output_dir):
        return 1
    
    # Step 3: Add color coding
    print("Adding color coding...")
    input_file = os.path.join(args.output_dir, f"incast_{params['nodes']}_{params['conns']}_{params['strategy']}_{params['cwnd']}iw_{params['parallel']}par.tmp")
    color_file = process_incast_color(input_file, params['parallel'], args.output_dir)
    
    if not color_file:
        return 1
    
    # Step 4: Generate gnuplot script
    print("Generating gnuplot script...")
    script_file = generate_gnuplot_script(params, args.flow_size, args.output_dir)
    
    # Step 5: Automatically run gnuplot to generate the SVG
    print("Generating SVG plot...")
    try:
        import subprocess
        result = subprocess.run(['gnuplot', script_file], capture_output=True, text=True)
        if result.returncode == 0:
            svg_file = os.path.join(args.output_dir, f'incast_{params["nodes"]}_{params["conns"]}_{params["strategy"]}_{params["cwnd"]}iw_{params["parallel"]}par.svg')
            print(f"Plotting complete! SVG generated: {svg_file}")
        else:
            print(f"Gnuplot execution failed: {result.stderr}")
            return 1
    except Exception as e:
        print(f"Error running gnuplot: {e}")
        print(f"Please manually run: gnuplot {script_file}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
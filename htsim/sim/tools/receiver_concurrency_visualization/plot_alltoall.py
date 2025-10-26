#!/usr/bin/env python3
"""
Modular plotting module for all-to-all experiment results
Input: simulation output files and parameters
Output: generates visualization plots
"""

import sys
import os
import argparse

def plot_overlap(nodes, conns, parallel, cwnd, strategy="perm", output_dir="."):
    """Process simulation output to generate overlap data"""
    filename = f"a2a-{nodes}-{conns}-{parallel}.cm"
    
    if not os.path.exists(filename):
        print(f"Error: Connection matrix file {filename} not found")
        return False
    
    # Read connection matrix to build flow information
    triggers = {}  # map of trigger id to flow id
    starts = {}    # map of flow id to trigger
    srcs = {}      # flow id to src
    dsts = {}      # flow id to dst
    dstcounts = {} # dsts to refcount
    srclist = []
    srcset = set()
    
    with open(filename, "r") as file:
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
    
    # Process simulation output
    input_filename = f"out_{nodes}_{conns}_{strategy}_{cwnd}iw_{parallel}par.tmp"
    output_filename = os.path.join(output_dir, f"incast_{nodes}_{conns}_{strategy}_{cwnd}iw_{parallel}par.tmp")
    
    if not os.path.exists(input_filename):
        print(f"Error: Simulation output file {input_filename} not found")
        return False
    
    with open(input_filename, "r") as infile, open(output_filename, "w") as outfile:
        prevtime = -4000
        count = 0
        
        for line in infile:
            if "startflow" in line:
                parts = line.split()
                flowid = parts[1]
                p2 = flowid.split('_')
                assert p2[0] == "ndp"
                dst = p2[2]
                dstcounts[dst] += 1
                
            if "finished" in line:
                parts = line.split()
                flow_id = parts[3]
                t = float(parts[6])
                dst = dsts[flow_id]
                dstcounts[dst] -= 1
                
                count += 1
                if t - prevtime > 4000:
                    count = 0
                    prevtime = t
                    for j, node in enumerate(srclist, 1):
                        print(t, j, dstcounts[node], file=outfile)
    
    return True

def process_incast_color(input_file, target_parallel, output_dir="."):
    """Add color coding based on concurrency levels"""
    if not os.path.exists(input_file):
        print(f"Error: Input file {input_file} not found")
        return None
    
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

def generate_gnuplot_script(nodes, conns, strategy, cwnd, parallel, flow_size_mb=1, output_dir="."):
    """Generate gnuplot script for visualization"""
    script_content = f'''set terminal pdf color
set output "incast_{nodes}_{conns}_{strategy}_{cwnd}iw_{parallel}par.pdf"
set title "{conns} node sequential all-to-all, {nodes} fat tree, {strategy} strategy, {cwnd} pkt IW, {flow_size_mb}MB flow size" offset 0,-3
set zlabel "No of incoming flows" rotate parallel offset 1,0
set ylabel "Time (ms)"
set xlabel "Receiver rank"
set ytics 0, 20, 160
set view 40,30
set size 1,1.1
set xrange [0:{conns}]
set xyplane 0
unset colorbox
set palette defined ( 0 "blue", 1 "orange", 2 "magenta", 3 "red")
splot "incast_{nodes}_{conns}_{strategy}_{cwnd}iw_{parallel}par.color.tmp" using 2:($1/1000):3:4 w i lw 1 lc palette notitle
'''
    
    script_filename = os.path.join(output_dir, f"incast_{nodes}_{conns}_{strategy}_{cwnd}iw_{parallel}par.gp")
    with open(script_filename, "w") as f:
        f.write(script_content)
    
    return script_filename

def main():
    parser = argparse.ArgumentParser(description="Plot all-to-all experiment results")
    parser.add_argument("--nodes", type=int, required=True, help="Number of nodes")
    parser.add_argument("--conns", type=int, required=True, help="Number of connections")
    parser.add_argument("--parallel", type=int, required=True, help="Parallel connections")
    parser.add_argument("--cwnd", type=int, required=True, help="Initial window size")
    parser.add_argument("--strategy", default="perm", help="Spray strategy")
    parser.add_argument("--flow-size", type=float, default=1.0, help="Flow size in MB")
    parser.add_argument("-o", "--output-dir", default="output", help="Output directory (default: output)")
    
    args = parser.parse_args()
    
    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Step 1: Process simulation output to generate overlap data
    print("Processing simulation output...")
    if not plot_overlap(args.nodes, args.conns, args.parallel, args.cwnd, args.strategy, args.output_dir):
        return 1
    
    # Step 2: Add color coding
    print("Adding color coding...")
    input_file = os.path.join(args.output_dir, f"incast_{args.nodes}_{args.conns}_{args.strategy}_{args.cwnd}iw_{args.parallel}par.tmp")
    color_file = process_incast_color(input_file, args.parallel, args.output_dir)
    
    if not color_file:
        return 1
    
    # Step 3: Generate gnuplot script
    print("Generating gnuplot script...")
    script_file = generate_gnuplot_script(
        args.nodes, args.conns, args.strategy, args.cwnd, args.parallel, args.flow_size, args.output_dir
    )
    
    print(f"Plotting module complete. Run: gnuplot {script_file}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
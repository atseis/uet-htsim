#!/bin/bash
# Modular plotting script for all-to-all experiment results

# Configuration parameters
NODES=1024
CONNS=512
PARALLEL=1
CWND=50
STRATEGY="perm"
FLOW_SIZE=1.0
OUTPUT_DIR="output"

# Path to plotting module
PLOT_MODULE="./plot_alltoall.py"

# Check if plotting module exists
if [ ! -f "$PLOT_MODULE" ]; then
    echo "Error: Plotting module $PLOT_MODULE not found"
    exit 1
fi

# Run the plotting module
echo "Running modular plotting for all-to-all experiment..."
echo "Parameters: nodes=$NODES, conns=$CONNS, parallel=$PARALLEL, cwnd=$CWND, strategy=$STRATEGY, output_dir=$OUTPUT_DIR"

python3 "$PLOT_MODULE" \
    --nodes "$NODES" \
    --conns "$CONNS" \
    --parallel "$PARALLEL" \
    --cwnd "$CWND" \
    --strategy "$STRATEGY" \
    --flow-size "$FLOW_SIZE" \
    -o "$OUTPUT_DIR"

# Check if plotting was successful
if [ $? -eq 0 ]; then
    echo "Plotting completed successfully!"
    echo "Generated files:"
    ls -la "$OUTPUT_DIR"/incast_*.tmp "$OUTPUT_DIR"/incast_*.gp 2>/dev/null || echo "No plot files found"
    
    # Generate the final plot
    GP_SCRIPT="$OUTPUT_DIR/incast_${NODES}_${CONNS}_${STRATEGY}_${CWND}iw_${PARALLEL}par.gp"
    if [ -f "$GP_SCRIPT" ]; then
        echo "Generating final plot with gnuplot..."
        gnuplot "$GP_SCRIPT"
        if [ $? -eq 0 ]; then
            echo "Plot generated: $OUTPUT_DIR/incast_${NODES}_${CONNS}_${STRATEGY}_${CWND}iw_${PARALLEL}par.pdf"
        else
            echo "Error: gnuplot failed"
        fi
    fi
else
    echo "Error: Plotting module failed"
    exit 1
fi
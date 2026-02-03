import sys
import os
import yaml
import math
import itertools
from typing import Dict, Any, List, Optional

# Try to import rich for beautiful output
try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    from rich.text import Text

    console = Console()
except ImportError:
    print("Please install rich: pip install rich")
    sys.exit(1)

# Ensure local imports work
sys.path.append(os.path.dirname(__file__))
# Try to import NetworkCalculator if available, or redefine minimal version
try:
    from analysis.utils.calculator import NetworkCalculator
except ImportError:
    # Minimal Fallback if utils not found
    class NetworkCalculator:
        def __init__(
            self,
            linkspeed_gbps=100.0,
            mtu_bytes=4150,
            base_rtt_us=14.0,
            queue_factor=1.0,
        ):
            self.linkspeed = linkspeed_gbps
            self.mtu = mtu_bytes
            self.rtt = base_rtt_us
            self.q_factor = queue_factor
            self.bdp_bytes = (linkspeed_gbps * 1e9 * (base_rtt_us * 1e-6)) / 8
            self.bdp_pkts = math.ceil(self.bdp_bytes / mtu_bytes)
            self.queue_size_pkts = int(self.bdp_pkts * queue_factor)
            self.queue_size_bytes = self.queue_size_pkts * mtu_bytes

        def convert_ecn(self, val, input_unit="pkts"):
            # ... simplified logic ...
            pass


def load_yaml(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class ConfigInspector:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.raw_config = load_yaml(config_path)
        self.variants = self._generate_variants()

    def _generate_variants(self) -> List[Dict[str, Any]]:
        """
        Flatten 'common' and 'experiments' into a list of full configurations.
        Identical to how ExperimentManager expands them usually.
        """
        common = self.raw_config.get("common", {}).get("simulation", {})
        common_traffic = self.raw_config.get("common", {}).get("traffic", {})

        experiments = self.raw_config.get("experiments", [])

        flat_variants = []

        for exp in experiments:
            exp_name = exp.get("name", "unnamed")
            exp_sim = exp.get("simulation", {})
            exp_traffic = exp.get("traffic", {})

            # Merge: Common Sim <- Exp Sim
            merged_sim = common.copy()
            merged_sim.update(exp_sim)

            # Merge: Common Traffic <- Exp Traffic
            merged_traffic = common_traffic.copy()
            merged_traffic.update(exp_traffic)

            # Cartesian Product Expansion
            # Find list-values in merged_sim and merged_traffic
            # Sim Params
            sim_keys, sim_vals = self._extract_lists(merged_sim)
            # Traffic Param (ignored for Physics context usually, but included for completeness)
            # Actually, we should handle traffic separately or just focus on SIM for Physics.
            # Let's expand SIM params primarily for "Physical Variants"

            sim_product = list(itertools.product(*sim_vals))

            for p_tuple in sim_product:
                variant_sim = merged_sim.copy()
                # Apply permutation
                ctx_str = []
                for k, v in zip(sim_keys, p_tuple):
                    variant_sim[k] = v
                    ctx_str.append(f"{k}={v}")

                # Create a variant object
                variant = {
                    "name": exp_name,
                    "sim": variant_sim,
                    "diff_str": ", ".join(ctx_str) if ctx_str else "base",
                }
                flat_variants.append(variant)

        return flat_variants

    def _extract_lists(self, d: Dict) -> (List[str], List[List[Any]]):
        keys = []
        vals = []
        for k, v in d.items():
            if isinstance(v, list):
                keys.append(k)
                vals.append(v)
        return keys, vals

    def group_by_physics(self):
        """
        Group variants by physical parameters (Linkspeed, MTU, RTT-related, QueueFactor).
        Returns unique PhysicalContexts.
        """
        # Key parameters affecting calc
        PHYS_KEYS = [
            "linkspeed",
            "mtu",
            "tiers",
            "hop_latency",
            "queue_size_bdp_factor",
        ]

        grouped = {}

        for v in self.variants:
            sim = v["sim"]
            # Extract key
            key_tuple = tuple(str(sim.get(k, "default")) for k in PHYS_KEYS)

            if key_tuple not in grouped:
                grouped[key_tuple] = {
                    "params": {k: sim.get(k) for k in PHYS_KEYS},
                    "ecn_configs": [],  # Store (ecn_raw_val, variant_name)
                    "variants": [],
                }

            grouped[key_tuple]["variants"].append(v["name"])

            # Check for ECN in this variant
            if "ecn" in sim:
                e = sim["ecn"]
                # Handle "20p 80p" string split if it comes as string
                if isinstance(e, str):
                    # It might be "20p 80p" -> this is actually ONE config setting low=20, high=80
                    # Or a list of strings ["20p", "80p"]?
                    # In yaml: ecn: "20p 80p". This is 1 value string.
                    grouped[key_tuple]["ecn_configs"].append((e, v["name"]))
                else:
                    grouped[key_tuple]["ecn_configs"].append((e, v["name"]))

        return grouped

    def analyze(self):
        groups = self.group_by_physics()

        for i, (key, g) in enumerate(groups.items(), 1):
            self._print_variant_table(i, g)

    def _print_variant_table(self, idx, group_data):
        params = group_data["params"]

        # 1. Determine Physics Values (Defaults from main_uec.cpp if missing)
        # Defaults
        D_LINKSPEED = 100000  # Mbps
        D_MTU = 4150
        D_TIERS = 3
        D_HOP = 1.0  # us
        D_Q_FACTOR = 1.0  # Default Trimming? Or 0?
        # User YAML said 8. Use param if set.

        p_linkspeed = (
            self._parse_linkspeed(params.get("linkspeed")) or D_LINKSPEED
        )  # Mbps
        p_mtu = int(params.get("mtu") or D_MTU)
        p_tiers = int(params.get("tiers") or D_TIERS)
        p_hop = float(params.get("hop_latency") or D_HOP)
        p_qfactor = float(params.get("queue_size_bdp_factor") or D_Q_FACTOR)

        # Initialize Calculator
        # Calc expects Gbps
        calc = NetworkCalculator(
            linkspeed_gbps=p_linkspeed / 1000.0,
            mtu_bytes=p_mtu,
            base_rtt_us=self._est_rtt(p_tiers, p_hop, p_mtu, p_linkspeed),
            queue_factor=p_qfactor,
        )

        # 2. Build Table
        table = Table(title=f"Variant #{idx} (Physical Context)", box=box.ROUNDED)
        table.add_column("Parameter", style="cyan")
        table.add_column("Value", style="magenta")
        table.add_column("Physical Context / Derivation", style="green")

        # Basic Phys
        table.add_row(
            "Linkspeed", f"{p_linkspeed / 1000.0} Gbps", f"Raw: {p_linkspeed} Mbps"
        )
        table.add_row("MTU", f"{p_mtu} Bytes", "")
        table.add_row("Base RTT", f"{calc.rtt:.2f} us", f"{p_tiers}-Tier FatTree Est.")
        table.add_row(
            "BDP", f"{calc.bdp_bytes / 1000:.1f} KB", f"{calc.bdp_pkts} Packets"
        )
        table.add_row(
            "Queue Size",
            f"{calc.queue_size_bytes / 1000:.1f} KB",
            f"{calc.queue_size_pkts} Packets ({p_qfactor}x BDP)",
        )

        # Separation
        table.add_section()

        # ECN Analysis
        # Unique ECN configs in this group
        unique_ecns = set(x[0] for x in group_data["ecn_configs"])

        if not unique_ecns:
            table.add_row("ECN", "N/A", "Not specified in config")
        else:
            for e_val in unique_ecns:
                # e_val might be "20p 80p"
                parsed = self._parse_ecn_str(e_val, calc)
                # Parsed is list of dicts
                desc_str = ""
                for p_idx, res in enumerate(parsed):
                    label = "Low" if p_idx == 0 else "High"
                    desc_str += f"[{label}]\n"
                    desc_str += f"  • {res['Packets']} Pkts (Int)\n"
                    desc_str += f"  • {res['KB']:.1f} KB\n"
                    desc_str += f"  • {res['Ratio (Queue)']} of Queue\n"
                    desc_str += f"  • {res['Ratio (BDP)']} of BDP\n"

                table.add_row(f"ECN Config\n'{e_val}'", "", desc_str)

        # Show affected experiments
        # table.add_section()
        # variants_str = "\n".join(group_data['variants'][:3])
        # if len(group_data['variants']) > 3: variants_str += "\n..."
        # table.add_row("Experiments", variants_str, "")

        console.print(table)
        console.print("\n")

    def _parse_linkspeed(self, v):
        if not v:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v)
        if "Gbps" in s:
            return float(s.replace("Gbps", "")) * 1000.0
        if "Mbps" in s:
            return float(s.replace("Mbps", ""))
        return float(s)

    def _est_rtt(self, tiers, hop, mtu, linkspeed_mbps):
        # Match main_uec.cpp logic
        hops = 6 if tiers == 3 else 4
        prop = hops * hop
        serialization = (hops * mtu * 8) / (linkspeed_mbps * 1e6) * 1e6
        return prop + serialization + 2.0  # +2 safety

    def _parse_ecn_str(self, val, calc: NetworkCalculator):
        # Handle list case (e.g. from yaml list) if it ever happens, though strictly yaml should be string "20p 80p"
        if isinstance(val, list):
            # Flatten
            results = []
            for item in val:
                results.extend(self._parse_ecn_str(item, calc))
            return results

        # "20p 80p" -> ["20p", "80p"]
        # "50%"
        parts = str(val).split()
        results = []
        for p in parts:
            results.append(self._parse_single_ecn_val(p, calc))
        return results

    def _parse_single_ecn_val(self, p, calc: NetworkCalculator):
        # p is string part like "20p", "0.5", "100"
        unit = "pkts"
        num = 0.0

        # Check standard suffixes
        if "p" in p and "%" not in p:  # 20p
            unit = "pkts"
            num = float(p.replace("p", ""))
        elif "%" in p:  # 50%
            unit = "ratio_queue"  # Assumption: % is of Queue
            num = float(p.replace("%", "")) / 100.0
        elif "KB" in p or "kb" in p:
            unit = "kb"
            # Normalize case
            s = p.replace("KB", "").replace("kb", "")
            num = float(s)
        else:
            # Pure number string. Analyze format.
            try:
                f_val = float(p)
                # Heuristic:
                # If it looks like an int (100, 20.0), treat as Packets IF > 1.0 (Safety)
                # If it is small float (0 < x <= 1.0), treat as Ratio of Queue
                # If exactly 0? treat as 0 packets.

                if f_val == 0.0:
                    unit = "pkts"
                    num = 0
                elif 0 < f_val <= 1.0:
                    # User likely means Ratio 0.2 -> 20%
                    unit = "ratio_queue"
                    num = f_val
                else:
                    # > 1.0, e.g. 20, 100
                    unit = "pkts"
                    num = f_val
            except ValueError:
                # Fallback
                unit = "pkts"
                num = 0

        return calc.convert_ecn(num, unit)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inspect_config.py <yaml_file>")
    else:
        ConfigInspector(sys.argv[1]).analyze()

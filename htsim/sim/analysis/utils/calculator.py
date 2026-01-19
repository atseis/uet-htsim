
import math

class NetworkCalculator:
    """
    [Utility] 网络仿真参数计算器。
    用于在不同单位 (Bytes, Packets, Ratio) 之间转换 ECN 阈值等参数，
    确保与 C++ 仿真器的物理逻辑一致。
    """
    
    def __init__(self, 
                 linkspeed_gbps: float = 100, 
                 mtu_bytes: int = 4150, 
                 base_rtt_us: float = 14,
                 queue_factor: float = 8):
        """
        :param linkspeed_gbps: 链路带宽 (Gbps)
        :param mtu_bytes: 最大传输单元 (Bytes)
        :param base_rtt_us: 基础往返时延 (us). htsim 默认 K=12 FatTree 约为 14us.
        :param queue_factor: 队列大小倍数 (QueueSize = BDP * Factor)
        """
        self.linkspeed = linkspeed_gbps
        self.mtu = mtu_bytes
        self.rtt = base_rtt_us
        self.q_factor = queue_factor
        
        # --- 核心物理量计算 ---
        # 1. BDP in Bytes = Bandwidth (bits/sec) * RTT (sec) / 8
        self.bdp_bytes = (linkspeed_gbps * 1e9 * (base_rtt_us * 1e-6)) / 8
        
        # 2. BDP in Packets = ceil(BDP_Bytes / MTU)
        self.bdp_pkts = math.ceil(self.bdp_bytes / mtu_bytes)
        
        # 3. Queue Size in Packets
        self.queue_size_pkts = int(self.bdp_pkts * queue_factor)
        
        # 4. Queue Size in Bytes
        self.queue_size_bytes = self.queue_size_pkts * mtu_bytes

    def get_summary(self):
        """返回当前物理环境摘要"""
        return {
            "Linkspeed": f"{self.linkspeed} Gbps",
            "RTT": f"{self.rtt} us",
            "BDP": f"{self.bdp_bytes/1000:.1f} KB ({self.bdp_pkts} pkts)",
            "Queue Size": f"{self.queue_size_bytes/1000:.1f} KB ({self.queue_size_pkts} pkts) [Factor={self.q_factor}x BDP]"
        }

    def convert_ecn(self, val, input_unit="ratio_bdp"):
        """
        转换 ECN 阈值到所有形式，返回 Packets, KB, Ratio 等详细信息。
        :param val: 输入值
        :param input_unit: 'ratio_bdp' (0.2), 'ratio_queue' (0.2), 'pkts' (20), 'kb' (30)
        """
        target_pkts = 0
        
        if input_unit == "ratio_bdp":
            target_pkts = round(self.bdp_pkts * val)
        elif input_unit == "ratio_queue":
            target_pkts = round(self.queue_size_pkts * val)
        elif input_unit == "pkts":
            target_pkts = int(val)
        elif input_unit == "kb":
            # For KB, typically we want to cover the bytes, so ceil is safer?
            # But let's stick to round for consistency if user inputs "30.0KB" (~7.5 pkts -> 8)
            # Actually ceil is better for KB to guarantee capacity.
            # But for Ratio (which comes from division), round is better.
            target_pkts = math.ceil((val * 1000) / self.mtu)
        else:
            raise ValueError(f"Unknown unit: {input_unit}")
            
        # 统一输出
        return {
            "Packets": target_pkts,
            "KB": (target_pkts * self.mtu) / 1000.0,
            "Ratio (Queue)": f"{target_pkts / self.queue_size_pkts:.2%}",
            "Ratio (BDP)": f"{target_pkts / self.bdp_pkts:.2%}",
            "Latency Impact (us)": f"{(target_pkts * self.mtu * 8) / (self.linkspeed * 1000):.2f} us"
        }

    @classmethod
    def from_simulation_params(cls, sim_params: dict, profile="uec"):
        """
        工厂方法：根据仿真参数字典自动估算 RTT 并初始化计算器。
        
        Ref: main_uec.cpp calculate_rtt()
        RTT = 2 * diameter_latency + serialization_delay * diameter
        Diameter (Hops) ≈ 2 * Tiers (Host-ToR-Agg-Core-Agg-ToR-Host is 6 hops for 3 tiers)
        """
        # [Defaults] Aligned with main_uec.cpp defaults
        # HOST_NIC typically 100Gbps in High-Speed Sim
        DEFAULTS = {
            "uec": {
                "linkspeed": 100000, # Mbps
                "mtu": 4150,
                "tiers": 3,
                "hop_latency": 1,    # us
                "queue_size_bdp_factor": 8
            },
            "roce": { # Future proofing
                "linkspeed": 100000,
                "mtu": 1000,         # RoCE often uses 1KB MTU
                "tiers": 3,
                "hop_latency": 1,
                "queue_size_bdp_factor": 8   
            }
        }
        
        defaults = DEFAULTS.get(profile, DEFAULTS["uec"])
        
        # Helper to get with default fallback
        def get_p(key, dtype=float):
            val = sim_params.get(key)
            if val is None:
                return dtype(defaults[key])
            try:
                return dtype(val)
            except:
                return dtype(defaults[key])

        linkspeed = get_p("linkspeed", float) / 1000.0 # Mbps -> Gbps
        mtu = get_p("mtu", int)
        tiers = get_p("tiers", int)
        hop_latency = get_p("hop_latency", float)
        q_factor = get_p("queue_size_bdp_factor", float)
        
        # Topology Diameter Estimation
        # 3 Tiers FatTree: Host -> ToR -> Agg -> Core -> Agg -> ToR -> Host (6 hops)
        # 2 Tiers FatTree: Host -> ToR -> Agg -> ToR -> Host (4 hops)
        hops = 6 if tiers == 3 else 4
        
        # 1. Propagation Delay (2 * diameter_latency)
        prop_delay = hops * hop_latency 
        
        # 2. Serialization Delay
        serialization_per_hop = (mtu * 8) / (linkspeed * 1e9) * 1e6 # us
        total_serialization = serialization_per_hop * hops
        
        # Base RTT (us)
        # We assume some additional processing delay or overhead as in main_uec.cpp
        base_rtt = prop_delay + total_serialization + 2.0 # +2us safety margin/ACKs estimate
        
        return cls(linkspeed, mtu, base_rtt, q_factor)

# 使用示例
if __name__ == "__main__":
    calc = NetworkCalculator(linkspeed_gbps=100, mtu_bytes=4150)
    print("--- Physics Summary ---")
    print(calc.get_summary())
    
    print("\n--- ECN Conversion (Input: 20 packets) ---")
    print(calc.convert_ecn(20, "pkts"))
    
    print("\n--- ECN Conversion (Input: 30 KB) ---")
    print(calc.convert_ecn(30, "kb"))

    print("\n--- ECN Conversion (Input: 0.2 BDP) ---")
    print(calc.convert_ecn(0.2, "ratio_bdp"))

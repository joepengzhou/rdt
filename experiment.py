"""
comprehensive experiment.py for RDT Protocol Testing

Scenarios:
A: 0% loss, 50ms RTT, window size 4
B: 10% loss, 100ms RTT, window size 8
C: 20% loss, 300ms RTT, window size 4
D: 5% loss, 500ms RTT, window size 16

This script will:
- run all scenarios
- measure throughput, latency, retransmissions
- generate comparison plots and reports
"""
from __future__ import annotations
import argparse
import time
import random
import json
import os
from typing import Tuple, Dict, List
from collections import defaultdict

from channel import UnreliableChannel, UnreliableLink
from gbn import GBNEndpoint
from sr import SREndpoint
from tcp_like import TCPishEndpoint

import matplotlib.pyplot as plt
import numpy as np

# Create necessary directories
os.makedirs("plots", exist_ok=True)
os.makedirs("report", exist_ok=True)
os.makedirs("results", exist_ok=True)


def run_experiment(protocol_class, loss, rtt_ms, window_size, bytes_to_send, packet_size=100, timeout_ms=None):
    """
    Run a single experiment for a protocol.
    
    Returns: (elapsed_time, throughput_bps, bytes_received, retransmissions)
    """
    if timeout_ms is None:
        timeout_ms = max(200, int(rtt_ms * 2))
    
    # Create endpoints with different signatures
    if protocol_class == TCPishEndpoint:
        endpoint_a = protocol_class(f"{protocol_class.__name__}-A", init_rto_ms=timeout_ms)
        endpoint_b = protocol_class(f"{protocol_class.__name__}-B", init_rto_ms=timeout_ms)
        endpoint_a.window = window_size
        endpoint_b.window = window_size
    else:
        endpoint_a = protocol_class(f"{protocol_class.__name__}-A", window=window_size, timeout_ms=timeout_ms)
        endpoint_b = protocol_class(f"{protocol_class.__name__}-B", window=window_size, timeout_ms=timeout_ms)
    
    # Create channel
    link = UnreliableLink(
        loss=loss, 
        delay_mean_ms=rtt_ms/2.0, 
        delay_jitter_ms=rtt_ms*0.1, 
        reorder_prob=0.05
    )
    channel = UnreliableChannel(endpoint_a, endpoint_b, ab_link=link, ba_link=link)
    
    # Track metrics
    bytes_received = 0
    retransmissions = 0
    
    payload = b'X' * packet_size
    total_chunks = bytes_to_send // len(payload)
    
    start_time = time.time()
    sent = 0
    
    while sent < total_chunks:
        # Try to send one chunk
        if endpoint_a.send_data(payload):
            sent += 1
        
        # Small delay to yield to timers
        time.sleep(0.001)
        
        # Drain receiver
        data = endpoint_b.recv_app_data()
        if data:
            bytes_received += len(data)
    
    # Wait for all packets to be acknowledged
    deadline = time.time() + 120.0  # Increased timeout
    max_wait = 0
    while time.time() < deadline and hasattr(endpoint_a, 'base') and hasattr(endpoint_a, 'nextseq') and endpoint_a.base < endpoint_a.nextseq:
        time.sleep(0.01)
        max_wait += 1
        if max_wait % 100 == 0:
            # Print progress every 1 second
            print(f"  Waiting for ACKs... base={endpoint_a.base}, nextseq={endpoint_a.nextseq}")
            time.sleep(0.01)  # Allow some time for network events
    
    end_time = time.time()
    elapsed = end_time - start_time
    
    # Calculate throughput in bits per second
    throughput_bps = (bytes_received * 8) / elapsed if elapsed > 0 else 0
    
    # Get retransmission count
    if hasattr(endpoint_a, 'retransmissions'):
        retransmissions = endpoint_a.retransmissions
    elif hasattr(channel, 'get_statistics'):
        stats = channel.get_statistics()
        retransmissions = stats.get('ab_link', {}).get('packets_lost', 0)
    
    return elapsed, throughput_bps, bytes_received, retransmissions


def run_scenario(scenario_name: str, loss: float, rtt_ms: float, window_size: int, 
                 bytes_to_send: int = 50000, runs: int = 3):
    """
    Run a scenario for all protocols and return results.
    """
    print(f"\n{'='*60}")
    print(f"Running Scenario {scenario_name}")
    print(f"Parameters: loss={loss:.1%}, rtt={rtt_ms}ms, window={window_size}, bytes={bytes_to_send}")
    print(f"{'='*60}")
    
    results = {}
    protocols = [
        ("GBN", GBNEndpoint),
        ("SR", SREndpoint),
        ("TCP-like", TCPishEndpoint)
    ]
    
    for protocol_name, protocol_class in protocols:
        print(f"\nTesting {protocol_name}...")
        all_results = []
        
        for run in range(runs):
            elapsed, throughput, bytes_recv, retrans = run_experiment(
                protocol_class, loss, rtt_ms, window_size, bytes_to_send
            )
            all_results.append({
                'elapsed': elapsed,
                'throughput': throughput,
                'bytes_received': bytes_recv,
                'retransmissions': retrans
            })
            print(f"  Run {run+1}: {elapsed:.3f}s, {throughput:.0f} bps, {retrans} retrans")
        
        # Average results
        avg_elapsed = sum(r['elapsed'] for r in all_results) / len(all_results)
        avg_throughput = sum(r['throughput'] for r in all_results) / len(all_results)
        avg_bytes = sum(r['bytes_received'] for r in all_results) / len(all_results)
        avg_retrans = sum(r['retransmissions'] for r in all_results) / len(all_results)
        
        results[protocol_name] = {
            'avg_elapsed': avg_elapsed,
            'avg_throughput': avg_throughput,
            'avg_bytes_received': avg_bytes,
            'avg_retransmissions': avg_retrans,
            'all_runs': all_results
        }
    
    return results


def plot_scenario_results(scenario_name: str, results: Dict):
    """
    Generate plots for a scenario.
    """
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    protocols = list(results.keys())
    
    # Plot 1: Throughput comparison
    ax1 = axes[0]
    throughputs = [results[p]['avg_throughput'] for p in protocols]
    colors = ['#3498db', '#2ecc71', '#e74c3c']
    bars = ax1.bar(protocols, throughputs, color=colors, alpha=0.7, edgecolor='black')
    ax1.set_ylabel('Throughput (bps)', fontsize=12)
    ax1.set_title(f'Scenario {scenario_name}: Throughput Comparison', fontsize=14, fontweight='bold')
    ax1.grid(axis='y', alpha=0.3)
    
    # Add value labels on bars
    for bar, val in zip(bars, throughputs):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'{val:.0f}',
                ha='center', va='bottom', fontsize=10)
    
    # Plot 2: Elapsed time
    ax2 = axes[1]
    elapsed = [results[p]['avg_elapsed'] for p in protocols]
    bars2 = ax2.bar(protocols, elapsed, color=colors, alpha=0.7, edgecolor='black')
    ax2.set_ylabel('Elapsed Time (s)', fontsize=12)
    ax2.set_title(f'Scenario {scenario_name}: Elapsed Time', fontsize=14, fontweight='bold')
    ax2.grid(axis='y', alpha=0.3)
    
    # Add value labels
    for bar, val in zip(bars2, elapsed):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{val:.3f}',
                ha='center', va='bottom', fontsize=10)
    
    # Plot 3: Retransmissions
    ax3 = axes[2]
    retrans = [results[p]['avg_retransmissions'] for p in protocols]
    bars3 = ax3.bar(protocols, retrans, color=colors, alpha=0.7, edgecolor='black')
    ax3.set_ylabel('Retransmissions', fontsize=12)
    ax3.set_title(f'Scenario {scenario_name}: Retransmissions', fontsize=14, fontweight='bold')
    ax3.grid(axis='y', alpha=0.3)
    
    # Add value labels
    for bar, val in zip(bars3, retrans):
        height = bar.get_height()
        ax3.text(bar.get_x() + bar.get_width()/2., height,
                f'{val:.1f}',
                ha='center', va='bottom', fontsize=10)
    
    plt.tight_layout()
    plt.savefig(f"plots/scenario_{scenario_name}.png", dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"Saved plot: plots/scenario_{scenario_name}.png")


def generate_combined_report(all_results: Dict[str, Dict], filename="report/comprehensive_report.txt"):
    """
    Generate a comprehensive text report.
    """
    with open(filename, 'w') as f:
        f.write("="*80 + "\n")
        f.write("RDT PROTOCOL COMPARISON REPORT\n")
        f.write("="*80 + "\n\n")
        
        for scenario, results in all_results.items():
            f.write(f"\n{scenario} Results:\n")
            f.write("-"*80 + "\n")
            f.write(f"{'Protocol':<15} {'Time(s)':<12} {'Throughput(bps)':<18} {'Retransmissions':<15}\n")
            f.write("-"*80 + "\n")
            
            for protocol, data in results.items():
                f.write(f"{protocol:<15} {data['avg_elapsed']:<12.3f} {data['avg_throughput']:<18.0f} {data['avg_retransmissions']:<15.1f}\n")
            
            f.write("\n")
        
        # Summary analysis
        f.write("\n" + "="*80 + "\n")
        f.write("ANALYSIS SUMMARY\n")
        f.write("="*80 + "\n\n")
        
        f.write("Scenario A (0% loss, 50ms RTT, window 4):\n")
        f.write("- All protocols should perform similarly with no packet loss\n")
        f.write("- Small window size limits throughput\n\n")
        
        f.write("Scenario B (10% loss, 100ms RTT, window 8):\n")
        f.write("- Selective Repeat should outperform Go-Back-N\n")
        f.write("- TCP-like should adapt to conditions\n\n")
        
        f.write("Scenario C (20% loss, 300ms RTT, window 4):\n")
        f.write("- Higher loss and RTT should show protocol robustness differences\n")
        f.write("- Small window with high loss can cause significant retransmissions\n\n")
        
        f.write("Scenario D (5% loss, 500ms RTT, window 16):\n")
        f.write("- Large window with high delay tests timeout handling\n")
        f.write("- Should reveal protocol efficiency under delay\n\n")


def plot_comparison(all_results: Dict[str, Dict], filename="plots/comprehensive_comparison.png"):
    """
    Generate a comprehensive comparison plot across all scenarios.
    """
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle('Comprehensive RDT Protocol Comparison Across All Scenarios', 
                 fontsize=16, fontweight='bold')
    
    scenarios = ['A', 'B', 'C', 'D']
    protocols = ['GBN', 'SR', 'TCP-like']
    colors = ['#3498db', '#2ecc71', '#e74c3c']
    
    # Throughput across scenarios
    for i, scenario in enumerate(scenarios):
        ax = axes[i // 2, i % 2]
        if scenario in all_results:
            results = all_results[scenario]
            throughputs = [results[p]['avg_throughput'] for p in protocols]
            x = np.arange(len(protocols))
            bars = ax.bar(x, throughputs, color=colors, alpha=0.7, edgecolor='black')
            
            ax.set_xlabel('Protocol', fontsize=11)
            ax.set_ylabel('Throughput (bps)', fontsize=11)
            ax.set_title(f'Scenario {scenario}', fontsize=12, fontweight='bold')
            ax.set_xticks(x)
            ax.set_xticklabels(protocols)
            ax.grid(axis='y', alpha=0.3)
            
            # Add value labels
            for bar, val in zip(bars, throughputs):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{val:.0f}',
                       ha='center', va='bottom', fontsize=9)
    
    plt.tight_layout()
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"Saved comprehensive plot: {filename}")


def main():
    parser = argparse.ArgumentParser(description='RDT Protocol Experiments')
    parser.add_argument('--scenario', type=str, default='all', 
                       choices=['A', 'B', 'C', 'D', 'all'],
                       help='Scenario to run (A, B, C, D, or all)')
    parser.add_argument('--bytes', type=int, default=20000,
                       help='Total bytes to send')
    parser.add_argument('--runs', type=int, default=2,
                       help='Number of runs per scenario')
    args = parser.parse_args()
    
    # Define scenarios
    scenarios = {
        'A': {'loss': 0.0, 'rtt_ms': 50, 'window': 4},
        'B': {'loss': 0.1, 'rtt_ms': 100, 'window': 8},
        'C': {'loss': 0.2, 'rtt_ms': 300, 'window': 4},
        'D': {'loss': 0.05, 'rtt_ms': 500, 'window': 16},
    }
    
    # Run scenarios
    all_results = {}
    
    if args.scenario == 'all':
        scenarios_to_run = list(scenarios.keys())
    else:
        scenarios_to_run = [args.scenario]
    
    for scenario_name in scenarios_to_run:
        params = scenarios[scenario_name]
        results = run_scenario(
            scenario_name,
            params['loss'],
            params['rtt_ms'],
            params['window'],
            args.bytes,
            args.runs
        )
        all_results[scenario_name] = results
        
        # Generate individual plots
        plot_scenario_results(scenario_name, results)
        
        # Save JSON results
        with open(f"results/scenario_{scenario_name}.json", 'w') as f:
            json.dump(results, f, indent=2)
    
    # Generate comprehensive report
    if len(all_results) > 1:
        generate_combined_report(all_results)
        plot_comparison(all_results)
    
    print("\n" + "="*60)
    print("Experiments Complete!")
    print(f"Results saved in: results/")
    print(f"Plots saved in: plots/")
    print(f"Report saved in: report/")
    print("="*60)


if __name__ == "__main__":
    main()


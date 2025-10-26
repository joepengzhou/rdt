"""
experiment.py
Run simple comparisons across GBN, SR, and TCP-like endpoints using the UnreliableChannel.

Usage examples:
    python3 experiment.py --loss 0.1 --rtt 200 --window 8 --bytes 20000
This script will:
- set up two endpoints for each protocol
- push a fixed number of bytes
- measure completion time and retransmissions (approximate)
- save a simple throughput bar chart in ./plots/
"""
from __future__ import annotations
import argparse
import time
import random
from typing import Tuple

from channel import UnreliableChannel, UnreliableLink
from gbn import GBNEndpoint
from sr import SREndpoint
from tcp_like import TCPishEndpoint

import matplotlib.pyplot as plt  # do not set styles/colors

def run_pair(endpoint_a, endpoint_b, loss, rtt_ms, bytes_to_send, window):
    link = UnreliableLink(loss=loss, delay_mean_ms=rtt_ms/2.0, delay_jitter_ms=rtt_ms*0.1, reorder_prob=0.05)
    ch = UnreliableChannel(endpoint_a, endpoint_b, ab_link=link, ba_link=link)

    payload = b'X' * 100  # chunk
    total_chunks = bytes_to_send // len(payload)

    start = time.time()
    sent = 0
    while sent < total_chunks:
        # try to send one chunk each loop
        ok = endpoint_a.send_data(payload)
        if ok:
            sent += 1
        time.sleep(0.001)  # yield to timers

        # drain receiver (not used, but simulates app consuming data)
        while endpoint_b.recv_app_data():
            pass

    # wait until all acked
    deadline = time.time() + 30.0
    while time.time() < deadline and endpoint_a.base < endpoint_a.nextseq:
        time.sleep(0.01)

    end = time.time()
    elapsed = end - start
    throughput = (bytes_to_send * 8) / elapsed  # bits per second
    return elapsed, throughput

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--loss", type=float, default=0.0, help="packet loss probability [0..1]")
    p.add_argument("--rtt", type=float, default=100.0, help="average RTT in ms")
    p.add_argument("--window", type=int, default=8, help="sender window size")
    p.add_argument("--bytes", type=int, default=50000, help="total bytes to send")
    args = p.parse_args()

    results = {}

    # GBN
    gbnA, gbnB = GBNEndpoint("GBN-A", window=args.window), GBNEndpoint("GBN-B", window=args.window)
    elapsed, tput = run_pair(gbnA, gbnB, args.loss, args.rtt, args.bytes, args.window)
    results["GBN"] = (elapsed, tput)

    # SR
    srA, srB = SREndpoint("SR-A", window=args.window), SREndpoint("SR-B", window=args.window)
    elapsed, tput = run_pair(srA, srB, args.loss, args.rtt, args.bytes, args.window)
    results["SR"] = (elapsed, tput)

    # TCP-like
    tcpA, tcpB = TCPishEndpoint("TCP-A"), TCPishEndpoint("TCP-B")
    tcpA.window = args.window
    tcpB.window = args.window
    elapsed, tput = run_pair(tcpA, tcpB, args.loss, args.rtt, args.bytes, args.window)
    results["TCP-like"] = (elapsed, tput)

    # Print table
    print("Protocol\tElapsed(s)\tThroughput(bps)")
    for k, (e, t) in results.items():
        print(f"{k}\t{e:.3f}\t{t:.0f}")

    # Plot throughput bar chart
    labels = list(results.keys())
    values = [results[k][1] for k in labels]
    plt.figure()
    plt.bar(labels, values)
    plt.ylabel("Throughput (bps)")
    plt.title("Protocol Throughput Comparison")
    plt.tight_layout()
    plt.savefig("plots/throughput.png", dpi=150)

if __name__ == "__main__":
    main()

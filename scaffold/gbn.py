"""
gbn.py
A minimal, educational Go-Back-N (GBN) sender/receiver pair.

This is a *reference scaffold* with a working baseline:
- Fixed-size window
- Cumulative ACKs
- Single retransmission timer for the oldest unacked packet

You are encouraged to extend:
- Configurable timeout/RTO
- Packetization/segmentation
- Loss stats and logging hooks
"""
from __future__ import annotations
import time
import threading
from typing import Any, Dict, Optional, Deque
from collections import deque

Packet = Dict[str, Any]

class GBNEndpoint:
    def __init__(self, name: str, window: int=8, timeout_ms: int=200):
        self.name = name
        self.window = window
        self.timeout_ms = timeout_ms
        self.base = 0
        self.nextseq = 0
        self.expected = 0  # receiver side
        self.buffer: Dict[int, bytes] = {}
        self.sent: Dict[int, Packet] = {}
        self.timer: Optional[threading.Timer] = None
        self.app_rx: Deque[bytes] = deque()
        self.lock = threading.Lock()
        self._channel_send = None  # injected by UnreliableChannel

    # --------------- Sender ---------------
    def send_data(self, data: bytes):
        with self.lock:
            if self.nextseq < self.base + self.window:
                pkt = {"type": "DATA", "seq": self.nextseq, "payload": data}
                self.sent[self.nextseq] = pkt
                self._channel_send(pkt)
                if self.base == self.nextseq:
                    self._start_timer()
                self.nextseq += 1
                return True
            else:
                return False  # window full

    def _start_timer(self):
        self._cancel_timer()
        self.timer = threading.Timer(self.timeout_ms/1000.0, self._timeout)
        self.timer.daemon = True
        self.timer.start()

    def _cancel_timer(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def _timeout(self):
        with self.lock:
            # Retransmit all unacked packets
            for s in range(self.base, self.nextseq):
                self._channel_send(self.sent[s])
            self._start_timer()

    # --------------- Receiver + Both ---------------
    def on_receive(self, pkt: Packet, direction: str):
        with self.lock:
            if pkt["type"] == "DATA":
                if pkt["seq"] == self.expected:
                    self.app_rx.append(pkt["payload"])
                    self.expected += 1
                # Cumulative ACK for the last in-order seq
                ack = self.expected - 1
                self._channel_send({"type": "ACK", "ack": ack})
            elif pkt["type"] == "ACK":
                ack = pkt["ack"]
                if ack >= self.base:
                    self.base = ack + 1
                    if self.base == self.nextseq:
                        self._cancel_timer()
                    else:
                        self._start_timer()

    # Utility to drain received data
    def recv_app_data(self) -> Optional[bytes]:
        return self.app_rx.popleft() if self.app_rx else None

"""
Selective Repeat (SR) Protocol Implementation
"""
from __future__ import annotations
import threading
from typing import Any, Dict, Optional, Deque
from collections import deque

Packet = Dict[str, Any]


class SREndpoint:
    def __init__(self, name: str, window: int=8, timeout_ms: int=200):
        self.name = name
        self.window = window
        self.timeout_ms = timeout_ms
        self.base = 0
        self.nextseq = 0
        self.recv_base = 0
        self.recv_buf: Dict[int, bytes] = {}
        self.sent: Dict[int, Packet] = {}
        self.timers: Dict[int, threading.Timer] = {}
        self.app_rx: Deque[bytes] = deque()
        self.lock = threading.Lock()
        self._channel_send = None  # injected
        self.retransmissions = 0  # Track retransmissions

    # --------------- Sender ---------------
    def send_data(self, data: bytes) -> bool:
        with self.lock:
            if self.nextseq < self.base + self.window:
                seq = self.nextseq
                pkt = {"type": "DATA", "seq": seq, "payload": data}
                self.sent[seq] = pkt
                self._channel_send(pkt)
                self._start_timer(seq)
                self.nextseq += 1
                return True
            return False

    def _start_timer(self, seq: int):
        self._cancel_timer(seq)
        t = threading.Timer(self.timeout_ms/1000.0, self._timeout, args=(seq,))
        t.daemon = True
        self.timers[seq] = t
        t.start()

    def _cancel_timer(self, seq: int):
        if seq in self.timers:
            self.timers[seq].cancel()
            del self.timers[seq]

    def _timeout(self, seq: int):
        with self.lock:
            if seq in self.sent and seq >= self.base:
                self._channel_send(self.sent[seq])
                self.retransmissions += 1
                self._start_timer(seq)

    # --------------- Receiver + Both ---------------
    def on_receive(self, pkt: Packet, direction: str):
        with self.lock:
            if pkt["type"] == "DATA":
                seq = pkt["seq"]
                # Accept within window
                if self.recv_base <= seq < self.recv_base + self.window:
                    self.recv_buf[seq] = pkt["payload"]
                    # Deliver in-order prefix
                    while self.recv_base in self.recv_buf:
                        self.app_rx.append(self.recv_buf.pop(self.recv_base))
                        self.recv_base += 1
                    # Send individual ACK
                    self._channel_send({"type": "ACK", "ack": seq})
                elif seq < self.recv_base:
                    # Already delivered, re-ACK to help sender
                    self._channel_send({"type": "ACK", "ack": seq})
            elif pkt["type"] == "ACK":
                ack = pkt["ack"]
                if ack in self.sent:
                    self._cancel_timer(ack)
                    del self.sent[ack]
                    if ack == self.base:
                        # Slide base forward
                        while self.base not in self.sent and self.base < self.nextseq:
                            self.base += 1

    def recv_app_data(self):
        return self.app_rx.popleft() if self.app_rx else None

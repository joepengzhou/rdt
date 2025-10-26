"""
tcp_like.py
A simplified TCP-like endpoint:
- Cumulative ACKs
- RTT estimation using EWMA (alpha=0.125)
- RTO = SRTT + 4*RTTVAR (very simplified variant)
- Fast retransmit on 3 duplicate ACKs (optional)

This is *not* a full TCP; it's for educational comparison.
"""
from __future__ import annotations
import time
import threading
from typing import Any, Dict, Optional, Deque
from collections import deque

Packet = Dict[str, Any]

ALPHA = 0.125
BETA = 0.25

class TCPishEndpoint:
    def __init__(self, name: str, init_rto_ms: int=200):
        self.name = name
        self.nextseq = 0
        self.base = 0
        self.window = 8  # static window unless congestion control added
        self.sent: Dict[int, Packet] = {}
        self.sent_ts: Dict[int, float] = {}
        self.app_rx: Deque[bytes] = deque()
        self._channel_send = None

        # RTO estimation
        self.srtt: Optional[float] = None
        self.rttvar: Optional[float] = None
        self.rto_ms = init_rto_ms

        # timers
        self.timer: Optional[threading.Timer] = None

        # dup ack tracking
        self.last_acked = -1
        self.dup_count = 0

        self.lock = threading.Lock()

    def _set_timer(self):
        self._cancel_timer()
        self.timer = threading.Timer(self.rto_ms/1000.0, self._timeout)
        self.timer.daemon = True
        self.timer.start()

    def _cancel_timer(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def send_data(self, data: bytes):
        with self.lock:
            if self.nextseq < self.base + self.window:
                seq = self.nextseq
                pkt = {"type": "DATA", "seq": seq, "payload": data}
                self.sent[seq] = pkt
                self.sent_ts[seq] = time.time()
                self._channel_send(pkt)
                if self.base == seq:
                    self._set_timer()
                self.nextseq += 1
                return True
            return False

    def _timeout(self):
        with self.lock:
            # Retransmit oldest unacked
            if self.base in self.sent:
                self._channel_send(self.sent[self.base])
                self.sent_ts[self.base] = time.time()
                # Optional: backoff
                self.rto_ms = min(60000, int(self.rto_ms * 2))
                self._set_timer()

    def on_receive(self, pkt: Packet, direction: str):
        with self.lock:
            if pkt["type"] == "DATA":
                # deliver in-order only (cumulative ACK model)
                if pkt["seq"] == self.last_acked + 1:
                    self.app_rx.append(pkt["payload"])
                    self.last_acked += 1
                # always send cumulative ACK
                self._channel_send({"type": "ACK", "ack": self.last_acked})
            elif pkt["type"] == "ACK":
                ack = pkt["ack"]
                if ack >= self.base:
                    # RTT measure for newly acked packets only
                    if ack in self.sent_ts:
                        sample = max(0.0, time.time() - self.sent_ts[ack])
                        # EWMA SRTT/RTTVAR (very simplified)
                        if self.srtt is None:
                            self.srtt = sample
                            self.rttvar = sample / 2.0
                        else:
                            self.rttvar = (1 - BETA) * self.rttvar + BETA * abs(self.srtt - sample)
                            self.srtt = (1 - ALPHA) * self.srtt + ALPHA * sample
                        # Jacobson/Karels style (rough)
                        self.rto_ms = int(1000 * (self.srtt + 4 * self.rttvar))
                        self.rto_ms = max(100, min(self.rto_ms, 60000))

                    # slide window
                    self.base = ack + 1
                    if self.base == self.nextseq:
                        self._cancel_timer()
                    else:
                        self._set_timer()

                    # reset dup ack tracking
                    self.dup_count = 0
                else:
                    # duplicate ack
                    if ack == self.last_acked:
                        self.dup_count += 1
                        if self.dup_count >= 3 and self.base in self.sent:
                            # fast retransmit
                            self._channel_send(self.sent[self.base])
                            self.sent_ts[self.base] = time.time()
                            self._set_timer()

    def recv_app_data(self):
        return self.app_rx.popleft() if self.app_rx else None

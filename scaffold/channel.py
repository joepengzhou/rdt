"""
channel.py
Simulate an unreliable network channel between two endpoints.

Key features:
- Packet loss, delay, and optional reordering
- Duplex links (A<->B) with independent characteristics
- Simple callback interface: endpoint.on_receive(packet, direction)

This is intentionally lightweight and educational.
You can replace timing with a discrete-event simulator if desired.
"""
from __future__ import annotations
import threading
import random
import time
from typing import Callable, Any, Dict, Optional

Packet = Dict[str, Any]  # e.g., {"type": "DATA"|"ACK", "seq": int, "ack": int, "payload": bytes}

class UnreliableLink:
    def __init__(self, loss: float=0.0, delay_mean_ms: float=50.0, delay_jitter_ms: float=10.0, reorder_prob: float=0.0):
        self.loss = loss
        self.delay_mean_ms = delay_mean_ms
        self.delay_jitter_ms = delay_jitter_ms
        self.reorder_prob = reorder_prob
        self._reorder_buffer = None  # type: Optional[Packet]

    def _sample_delay(self) -> float:
        jitter = random.uniform(-self.delay_jitter_ms, self.delay_jitter_ms)
        return max(0.0, (self.delay_mean_ms + jitter) / 1000.0)

    def maybe_drop(self) -> bool:
        return random.random() < self.loss

    def maybe_reorder(self, pkt: Packet) -> Optional[Packet]:
        """
        Either hold this packet for reordering, or release a previously held one.
        Returns a packet to actually send now (which could be the held packet) or None (meaning delay send).
        """
        if self.reorder_prob <= 0.0:
            return pkt

        if self._reorder_buffer is None and random.random() < self.reorder_prob:
            # hold this packet, return nothing now
            self._reorder_buffer = pkt
            return None
        elif self._reorder_buffer is not None:
            # release held packet; keep current one for potential future reorder
            out = self._reorder_buffer
            self._reorder_buffer = pkt if random.random() < self.reorder_prob else None
            return out
        else:
            return pkt

class UnreliableChannel:
    """
    Connects endpoint A and endpoint B with two UnreliableLink instances (A->B and B->A).
    Endpoints must implement: on_receive(packet: Packet, direction: str) where direction is "A" or "B".
    """
    def __init__(self,
                 endpoint_A: Any,
                 endpoint_B: Any,
                 ab_link: UnreliableLink = None,
                 ba_link: UnreliableLink = None,
                 ):
        self.endpoint_A = endpoint_A
        self.endpoint_B = endpoint_B
        self.ab = ab_link or UnreliableLink()
        self.ba = ba_link or UnreliableLink()
        # Inject backrefs so endpoints can send() easily
        endpoint_A._channel_send = lambda pkt: self.send_from_A(pkt)
        endpoint_B._channel_send = lambda pkt: self.send_from_B(pkt)

    def send_from_A(self, pkt: Packet):
        self._send(pkt, direction="A")

    def send_from_B(self, pkt: Packet):
        self._send(pkt, direction="B")

    def _send(self, pkt: Packet, direction: str):
        link = self.ab if direction == "A" else self.ba
        if link.maybe_drop():
            return  # dropped

        # Reordering handling (could return None to delay send)
        maybe_pkt = link.maybe_reorder(pkt)
        if maybe_pkt is None:
            # No immediate send; maybe later something will release
            return

        delay = link._sample_delay()
        def deliver():
            if direction == "A":
                self.endpoint_B.on_receive(maybe_pkt, direction="A")
            else:
                self.endpoint_A.on_receive(maybe_pkt, direction="B")
        t = threading.Timer(delay, deliver)
        t.daemon = True
        t.start()

"""
Simulate an unreliable network channel between two endpoints.
"""
from __future__ import annotations
import threading
import random
import time
import json
from typing import Callable, Any, Dict, Optional

Packet = Dict[str, Any]  # e.g., {"type": "DATA"|"ACK", "seq": int, "ack": int, "payload": bytes, "checksum": int}

def calculate_checksum(pkt: Packet) -> int:
    """Calculate simple checksum for packet"""
    checksum = 0
    # Include type, seq/ack, and payload in checksum
    if pkt.get("type"):
        for char in pkt["type"]:
            checksum ^= ord(char)
    if pkt.get("seq") is not None:
        checksum ^= pkt["seq"]
    if pkt.get("ack") is not None:
        checksum ^= pkt["ack"]
    if pkt.get("payload"):
        for byte in pkt["payload"]:
            checksum ^= byte
    return checksum & 0xFFFF  # 16-bit checksum

def verify_checksum(pkt: Packet) -> bool:
    """Verify packet checksum"""
    if "checksum" not in pkt:
        return True  # No checksum to verify
    return pkt["checksum"] == calculate_checksum(pkt)

def add_checksum(pkt: Packet) -> Packet:
    """Add checksum to packet"""
    pkt["checksum"] = calculate_checksum(pkt)
    return pkt


class UnreliableLink:
    def __init__(self, loss: float=0.0, delay_mean_ms: float=50.0, delay_jitter_ms: float=10.0, reorder_prob: float=0.0, corruption_prob: float=0.0):
        self.loss = loss
        self.delay_mean_ms = delay_mean_ms
        self.delay_jitter_ms = delay_jitter_ms
        self.reorder_prob = reorder_prob
        self.corruption_prob = corruption_prob
        self._reorder_buffer = None  # type: Optional[Packet]
        
        # Statistics
        self.packets_sent = 0
        self.packets_lost = 0
        self.packets_corrupted = 0
        self.packets_reordered = 0

    def _sample_delay(self) -> float:
        jitter = random.uniform(-self.delay_jitter_ms, self.delay_jitter_ms)
        return max(0.0, (self.delay_mean_ms + jitter) / 1000.0)

    def maybe_drop(self) -> bool:
        return random.random() < self.loss

    def maybe_corrupt(self, pkt: Packet) -> Packet:
        """Corrupt packet with given probability"""
        if random.random() < self.corruption_prob and pkt.get("payload"):
            # Corrupt one random byte in payload
            payload = bytearray(pkt["payload"])
            if payload:
                corrupt_index = random.randint(0, len(payload) - 1)
                payload[corrupt_index] = (payload[corrupt_index] + 1) % 256
                pkt["payload"] = bytes(payload)
                pkt["corrupted"] = True
                self.packets_corrupted += 1
        return pkt

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
            self.packets_reordered += 1
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
    with comprehensive logging and statistics.
    """
    def __init__(self,
                 endpoint_A: Any,
                 endpoint_B: Any,
                 ab_link: UnreliableLink = None,
                 ba_link: UnreliableLink = None,
                 enable_logging: bool = True
                 ):
        self.endpoint_A = endpoint_A
        self.endpoint_B = endpoint_B
        self.ab = ab_link or UnreliableLink()
        self.ba = ba_link or UnreliableLink()
        self.enable_logging = enable_logging
        
        # Logging system
        self.log_events = []
        self.start_time = time.time()
        
        # Inject backrefs so endpoints can send() easily
        endpoint_A._channel_send = lambda pkt: self.send_from_A(pkt)
        endpoint_B._channel_send = lambda pkt: self.send_from_B(pkt)

    def _log_event(self, event_type: str, data: Dict[str, Any]):
        """Log channel events for debugging and analysis"""
        if not self.enable_logging:
            return
            
        event = {
            'timestamp': time.time() - self.start_time,
            'event_type': event_type,
            'data': data
        }
        self.log_events.append(event)
        
        # Keep only last 10000 events to prevent memory issues
        if len(self.log_events) > 10000:
            self.log_events = self.log_events[-10000:]

    def send_from_A(self, pkt: Packet):
        self._send(pkt, direction="A")

    def send_from_B(self, pkt: Packet):
        self._send(pkt, direction="B")

    def _send(self, pkt: Packet, direction: str):
        link = self.ab if direction == "A" else self.ba
        link.packets_sent += 1
        
        # Add checksum before sending
        pkt = add_checksum(pkt)
        
        # Log send event
        self._log_event("PACKET_SENT", {
            'direction': direction,
            'packet_type': pkt.get('type', 'UNKNOWN'),
            'seq': pkt.get('seq', pkt.get('ack', -1)),
            'payload_size': len(pkt.get('payload', b'')),
            'checksum': pkt.get('checksum', 0)
        })
        
        if link.maybe_drop():
            link.packets_lost += 1
            self._log_event("PACKET_DROPPED", {
                'direction': direction,
                'packet_type': pkt.get('type', 'UNKNOWN'),
                'seq': pkt.get('seq', pkt.get('ack', -1))
            })
            return  # dropped

        # Apply corruption
        pkt = link.maybe_corrupt(pkt)
        if pkt.get('corrupted'):
            self._log_event("PACKET_CORRUPTED", {
                'direction': direction,
                'packet_type': pkt.get('type', 'UNKNOWN'),
                'seq': pkt.get('seq', pkt.get('ack', -1))
            })

        # Reordering handling (could return None to delay send)
        maybe_pkt = link.maybe_reorder(pkt)
        if maybe_pkt is None:
            # No immediate send; maybe later something will release
            return

        delay = link._sample_delay()
        def deliver():
            # Verify checksum before delivery
            checksum_valid = verify_checksum(maybe_pkt)
            if not checksum_valid:
                self._log_event("CHECKSUM_ERROR", {
                    'direction': direction,
                    'packet_type': maybe_pkt.get('type', 'UNKNOWN'),
                    'seq': maybe_pkt.get('seq', maybe_pkt.get('ack', -1))
                })
                return  # Drop corrupted packet
            
            self._log_event("PACKET_DELIVERED", {
                'direction': direction,
                'packet_type': maybe_pkt.get('type', 'UNKNOWN'),
                'seq': maybe_pkt.get('seq', maybe_pkt.get('ack', -1)),
                'delay': delay * 1000,  # Convert to ms
                'checksum_valid': checksum_valid
            })
            
            if direction == "A":
                self.endpoint_B.on_receive(maybe_pkt, direction="A")
            else:
                self.endpoint_A.on_receive(maybe_pkt, direction="B")
        t = threading.Timer(delay, deliver)
        t.daemon = True
        t.start()

    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive channel statistics"""
        return {
            'total_events': len(self.log_events),
            'ab_link': {
                'packets_sent': self.ab.packets_sent,
                'packets_lost': self.ab.packets_lost,
                'packets_corrupted': self.ab.packets_corrupted,
                'packets_reordered': self.ab.packets_reordered,
                'loss_rate': self.ab.packets_lost / max(1, self.ab.packets_sent)
            },
            'ba_link': {
                'packets_sent': self.ba.packets_sent,
                'packets_lost': self.ba.packets_lost,
                'packets_corrupted': self.ba.packets_corrupted,
                'packets_reordered': self.ba.packets_reordered,
                'loss_rate': self.ba.packets_lost / max(1, self.ba.packets_sent)
            },
            'configuration': {
                'ab_loss': self.ab.loss,
                'ab_delay_ms': self.ab.delay_mean_ms,
                'ab_reorder_prob': self.ab.reorder_prob,
                'ab_corruption_prob': self.ab.corruption_prob,
                'ba_loss': self.ba.loss,
                'ba_delay_ms': self.ba.delay_mean_ms,
                'ba_reorder_prob': self.ba.reorder_prob,
                'ba_corruption_prob': self.ba.corruption_prob
            }
        }

    def save_logs(self, filename: str):
        """Save channel logs to file"""
        with open(filename, 'w') as f:
            json.dump({
                'events': self.log_events,
                'statistics': self.get_statistics()
            }, f, indent=2)

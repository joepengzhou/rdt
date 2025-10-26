"""
TCP-like Protocol Implementation        
"""
from __future__ import annotations
import time
import threading
import json
from typing import Any, Dict, Optional, Deque
from collections import deque

Packet = Dict[str, Any]

# Default RTT estimation parameters (configurable)
DEFAULT_ALPHA = 0.125  # EWMA parameter for RTT
DEFAULT_BETA = 0.25    # EWMA parameter for RTT variance
DEFAULT_K = 4          # RTO = SRTT + K*RTTVAR

# Default congestion control parameters
DEFAULT_SSTHRESH_INIT = 65535  # Initial slow start threshold
DEFAULT_CWND_INIT = 1          # Initial congestion window
DEFAULT_AI_FACTOR = 1          # Additive increase factor
DEFAULT_MD_FACTOR = 0.5        # Multiplicative decrease factor


class TCPishEndpoint:
    def __init__(self, name: str, init_rto_ms: int=200, 
                 alpha: float=DEFAULT_ALPHA, beta: float=DEFAULT_BETA, k: float=DEFAULT_K,
                 enable_congestion_control: bool=True,
                 ssthresh_init: int=DEFAULT_SSTHRESH_INIT, cwnd_init: int=DEFAULT_CWND_INIT,
                 ai_factor: float=DEFAULT_AI_FACTOR, md_factor: float=DEFAULT_MD_FACTOR):
        self.name = name
        self.nextseq = 0
        self.base = 0
        self.window = 8  # static window unless congestion control added
        self.sent: Dict[int, Packet] = {}
        self.sent_ts: Dict[int, float] = {}
        self.app_rx: Deque[bytes] = deque()
        self._channel_send = None

        # Configurable RTT estimation parameters
        self.alpha = alpha
        self.beta = beta
        self.k = k

        # RTO estimation
        self.srtt: Optional[float] = None
        self.rttvar: Optional[float] = None
        self.rto_ms = init_rto_ms

        # timers
        self.timer: Optional[threading.Timer] = None

        # dup ack tracking
        self.last_acked = -1
        self.dup_count = 0

        # Congestion control (AIMD)
        self.enable_congestion_control = enable_congestion_control
        self.ssthresh = ssthresh_init
        self.cwnd = cwnd_init
        self.ai_factor = ai_factor
        self.md_factor = md_factor
        
        # Statistics and logging
        self.log_events = []
        self.start_time = time.time()
        self.packets_sent = 0
        self.packets_received = 0
        self.retransmissions = 0
        self.timeouts = 0
        self.fast_retransmits = 0
        self.rtt_samples = []

        self.lock = threading.Lock()

    def _log_event(self, event_type: str, data: Dict[str, Any]):
        """Log protocol events for debugging and analysis"""
        event = {
            'timestamp': time.time() - self.start_time,
            'event_type': event_type,
            'data': data
        }
        self.log_events.append(event)
        
        # Keep only last 10000 events
        if len(self.log_events) > 10000:
            self.log_events = self.log_events[-10000:]

    def _set_timer(self):
        self._cancel_timer()
        self.timer = threading.Timer(self.rto_ms/1000.0, self._timeout)
        self.timer.daemon = True
        self.timer.start()
        
        self._log_event("TIMER_STARTED", {
            'rto_ms': self.rto_ms,
            'base': self.base
        })

    def _cancel_timer(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
            
            self._log_event("TIMER_CANCELLED", {'base': self.base})

    def send_data(self, data: bytes):
        with self.lock:
            # Use congestion window if enabled, otherwise use static window
            effective_window = self.cwnd if self.enable_congestion_control else self.window
            
            if self.nextseq < self.base + effective_window:
                seq = self.nextseq
                pkt = {"type": "DATA", "seq": seq, "payload": data}
                self.sent[seq] = pkt
                self.sent_ts[seq] = time.time()
                self._channel_send(pkt)
                self.packets_sent += 1
                
                self._log_event("PACKET_SENT", {
                    'seq': seq,
                    'payload_size': len(data),
                    'cwnd': self.cwnd,
                    'ssthresh': self.ssthresh,
                    'effective_window': effective_window
                })
                
                if self.base == seq:
                    self._set_timer()
                self.nextseq += 1
                return True
            return False

    def _timeout(self):
        with self.lock:
            self.timeouts += 1
            
            self._log_event("TIMEOUT", {
                'base': self.base,
                'timeout_count': self.timeouts,
                'rto_ms': self.rto_ms
            })
            
            # Retransmit oldest unacked
            if self.base in self.sent:
                self._channel_send(self.sent[self.base])
                self.sent_ts[self.base] = time.time()
                self.retransmissions += 1
                
                # Congestion control: multiplicative decrease
                if self.enable_congestion_control:
                    self.ssthresh = max(2, int(self.cwnd * self.md_factor))
                    self.cwnd = 1  # Slow start
                    
                    self._log_event("CONGESTION_CONTROL_MD", {
                        'old_cwnd': self.cwnd,
                        'new_cwnd': 1,
                        'new_ssthresh': self.ssthresh
                    })
                
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
                    self.packets_received += 1
                    
                    self._log_event("PACKET_RECEIVED", {
                        'seq': pkt["seq"],
                        'payload_size': len(pkt["payload"])
                    })
                    
                    # Congestion control: additive increase
                    if self.enable_congestion_control and self.cwnd < self.ssthresh:
                        # Slow start phase
                        self.cwnd += 1
                        self._log_event("CONGESTION_CONTROL_SS", {
                            'old_cwnd': self.cwnd - 1,
                            'new_cwnd': self.cwnd,
                            'phase': 'slow_start'
                        })
                    elif self.enable_congestion_control:
                        # Congestion avoidance phase
                        self.cwnd += self.ai_factor / self.cwnd
                        self._log_event("CONGESTION_CONTROL_CA", {
                            'old_cwnd': self.cwnd - self.ai_factor / self.cwnd,
                            'new_cwnd': self.cwnd,
                            'phase': 'congestion_avoidance'
                        })
                
                # always send cumulative ACK
                self._channel_send({"type": "ACK", "ack": self.last_acked})
                
                self._log_event("ACK_SENT", {
                    'ack': self.last_acked,
                    'cumulative': True
                })
                
            elif pkt["type"] == "ACK":
                ack = pkt["ack"]
                if ack >= self.base:
                    # RTT measure for newly acked packets only
                    if ack in self.sent_ts:
                        sample = max(0.0, time.time() - self.sent_ts[ack])
                        self.rtt_samples.append(sample * 1000)  # Convert to ms
                        
                        # EWMA SRTT/RTTVAR (configurable parameters)
                        if self.srtt is None:
                            self.srtt = sample
                            self.rttvar = sample / 2.0
                        else:
                            self.rttvar = (1 - self.beta) * self.rttvar + self.beta * abs(self.srtt - sample)
                            self.srtt = (1 - self.alpha) * self.srtt + self.alpha * sample
                        
                        # Jacobson/Karels style (configurable K)
                        self.rto_ms = int(1000 * (self.srtt + self.k * self.rttvar))
                        self.rto_ms = max(100, min(self.rto_ms, 60000))
                        
                        self._log_event("RTT_UPDATE", {
                            'sample_ms': sample * 1000,
                            'srtt_ms': self.srtt * 1000,
                            'rttvar_ms': self.rttvar * 1000,
                            'rto_ms': self.rto_ms,
                            'alpha': self.alpha,
                            'beta': self.beta,
                            'k': self.k
                        })

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
                        
                        self._log_event("DUPLICATE_ACK", {
                            'ack': ack,
                            'dup_count': self.dup_count
                        })
                        
                        if self.dup_count >= 3 and self.base in self.sent:
                            # fast retransmit
                            self.fast_retransmits += 1
                            self._channel_send(self.sent[self.base])
                            self.sent_ts[self.base] = time.time()
                            self.retransmissions += 1
                            
                            # Congestion control: multiplicative decrease
                            if self.enable_congestion_control:
                                self.ssthresh = max(2, int(self.cwnd * self.md_factor))
                                self.cwnd = self.ssthresh  # Fast recovery
                                
                                self._log_event("FAST_RETRANSMIT", {
                                    'seq': self.base,
                                    'old_cwnd': self.cwnd,
                                    'new_cwnd': self.ssthresh,
                                    'new_ssthresh': self.ssthresh
                                })
                            
                            self._set_timer()

    def recv_app_data(self):
        return self.app_rx.popleft() if self.app_rx else None

    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive protocol statistics"""
        total_time = time.time() - self.start_time
        avg_rtt = sum(self.rtt_samples) / len(self.rtt_samples) if self.rtt_samples else 0
        
        return {
            'protocol': 'TCP-like',
            'name': self.name,
            'packets_sent': self.packets_sent,
            'packets_received': self.packets_received,
            'retransmissions': self.retransmissions,
            'timeouts': self.timeouts,
            'fast_retransmits': self.fast_retransmits,
            'total_time': total_time,
            'throughput_bps': self.packets_received / total_time if total_time > 0 else 0,
            'success_rate': self.packets_received / max(1, self.packets_sent),
            'retransmission_rate': self.retransmissions / max(1, self.packets_sent),
            'rtt_stats': {
                'avg_rtt_ms': avg_rtt,
                'srtt_ms': self.srtt * 1000 if self.srtt else 0,
                'rttvar_ms': self.rttvar * 1000 if self.rttvar else 0,
                'rto_ms': self.rto_ms,
                'samples': len(self.rtt_samples)
            },
            'congestion_control': {
                'enabled': self.enable_congestion_control,
                'cwnd': self.cwnd,
                'ssthresh': self.ssthresh,
                'ai_factor': self.ai_factor,
                'md_factor': self.md_factor
            },
            'rtt_parameters': {
                'alpha': self.alpha,
                'beta': self.beta,
                'k': self.k
            },
            'current_state': {
                'base': self.base,
                'nextseq': self.nextseq,
                'last_acked': self.last_acked,
                'dup_count': self.dup_count
            }
        }

    def save_logs(self, filename: str):
        """Save protocol logs to file"""
        with open(filename, 'w') as f:
            json.dump({
                'events': self.log_events,
                'statistics': self.get_statistics()
            }, f, indent=2)

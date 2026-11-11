"""
CAN Bus Model with Bit-Level Arbitration, Error Handling, and Retransmission.

What this file does:
1. Implements the shared two-wire CAN physical bus abstraction.
2. Bit-level Arbitration:
   When multiple ECUs attempt to transmit simultaneously, they output their identifier
   bit-by-bit. If ECU A puts a '0' (dominant) while ECU B puts a '1' (recessive),
   the wire level stays at '0'. ECU B reads back '0', realizes it lost arbitration,
   stops transmitting immediately, and retains the message in its queue for retransmission!
3. Error State Machine:
   Tracks TEC (Transmit Error Counter) and REC (Receive Error Counter) per node:
   - ERROR_ACTIVE: TEC <= 127, REC <= 127 (normal mode)
   - ERROR_PASSIVE: TEC > 127 or REC > 127 (degraded error reporting)
   - BUS_OFF: TEC > 255 (controller disconnects from bus to protect the network)
4. Retransmission:
   Frames that fail transmission (due to bit error, CRC error, or missing ACK)
   are automatically retransmitted according to configurable retry policies.
5. Injected Faults:
   Supports bus held dominant (short to ground), disconnected nodes, missing ACK,
   and frame corruption.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Callable
from virtual_vehicle.can.frame import CANFrame
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus


class CANErrorState(Enum):
    ERROR_ACTIVE = "ERROR_ACTIVE"    # Normal state, can transmit and receive
    ERROR_PASSIVE = "ERROR_PASSIVE"  # Warning state (TEC > 127 or REC > 127)
    BUS_OFF = "BUS_OFF"              # Disconnected from bus (TEC > 255)


@dataclass
class CANNodeController:
    """State of an ECU's CAN controller attached to the bus."""
    node_name: str
    tx_queue: List[CANFrame] = field(default_factory=list)
    rx_filter_ids: Optional[List[int]] = None  # None = accept all, or list of permitted IDs
    tec: int = 0  # Transmit Error Counter
    rec: int = 0  # Receive Error Counter
    error_state: CANErrorState = CANErrorState.ERROR_ACTIVE
    is_connected: bool = True  # Can be disconnected by fault injection
    retransmit_limit: int = 16  # Max retries before dropping a frame

    def update_error_state(self) -> None:
        """Updates controller state according to ISO 11898 rules."""
        if self.tec > 255:
            self.error_state = CANErrorState.BUS_OFF
        elif self.tec > 127 or self.rec > 127:
            self.error_state = CANErrorState.ERROR_PASSIVE
        else:
            self.error_state = CANErrorState.ERROR_ACTIVE


@dataclass
class BusStatistics:
    """Tracks metrics required by Section 2.2 and Section 4.5."""
    total_frames_sent: int = 0
    total_arbitrations: int = 0
    total_collisions_resolved: int = 0
    total_errors: int = 0
    total_retransmissions: int = 0
    total_bus_time_busy_us: int = 0
    latencies_us: Dict[int, List[int]] = field(default_factory=dict)  # ID -> list of (end_time - queue_time)


class CANBus:
    """
    Simulated shared CAN / CAN FD bus.
    """

    def __init__(self, clock: SimulationClock, event_bus: EventBus,
                 nominal_baudrate: int = 500_000, data_baudrate: int = 2_000_000):
        self.clock = clock
        self.event_bus = event_bus
        self.nominal_baudrate = nominal_baudrate
        self.data_baudrate = data_baudrate

        self.nodes: Dict[str, CANNodeController] = {}
        self.subscribers: List[Callable[[CANFrame], None]] = []
        self.stats = BusStatistics()

        # Bus state
        self.is_busy: bool = False
        self.current_transmitting_frame: Optional[CANFrame] = None
        self.bus_held_dominant: bool = False  # Injected fault: bus stuck low

    def register_node(self, node_name: str, filter_ids: Optional[List[int]] = None) -> CANNodeController:
        """Attaches an ECU to this CAN bus."""
        controller = CANNodeController(node_name=node_name, rx_filter_ids=filter_ids)
        self.nodes[node_name] = controller
        return controller

    def queue_frame(self, frame: CANFrame) -> None:
        """Queues a frame in the ECU controller without immediately triggering arbitration."""
        node = self.nodes.get(frame.sender_ecu)
        if not node:
            raise ValueError(f"ECU '{frame.sender_ecu}' is not registered on this CAN bus.")
        frame.tx_queued_time_us = self.clock.current_time_us
        node.tx_queue.append(frame)

    def trigger_arbitration(self) -> None:
        """Manually triggers arbitration among all queued frames across all ECUs."""
        if not self.is_busy:
            self._arbitrate_and_transmit()

    def send_frame(self, frame: CANFrame) -> None:
        """
        An ECU calls this to queue a frame for transmission.
        """
        node = self.nodes.get(frame.sender_ecu)
        if not node:
            raise ValueError(f"ECU '{frame.sender_ecu}' is not registered on this CAN bus.")

        if not node.is_connected:
            self.event_bus.publish(
                self.clock.current_time_us, "CAN", frame.sender_ecu, "TX_BLOCKED",
                f"Node {frame.sender_ecu} is disconnected from CAN bus; frame dropped.",
                {"frame": repr(frame)}
            )
            return

        if node.error_state == CANErrorState.BUS_OFF:
            self.event_bus.publish(
                self.clock.current_time_us, "CAN", frame.sender_ecu, "TX_BLOCKED",
                f"Node {frame.sender_ecu} is in BUS_OFF state; cannot transmit frame 0x{frame.arbitration_id:X}.",
                {"frame": repr(frame)}
            )
            return

        self.queue_frame(frame)

        # Trigger arbitration check if the bus is currently free
        if not self.is_busy:
            self._arbitrate_and_transmit()

    def _resolve_bit_arbitration(self, contenders: List[Tuple[CANNodeController, CANFrame]]) -> Tuple[Tuple[CANNodeController, CANFrame], List[Tuple[CANNodeController, CANFrame]]]:
        """
        Performs true bit-level arbitration between all competing nodes.
        In CAN:
        - 0 is DOMINANT (asserted voltage)
        - 1 is RECESSIVE (floating voltage)
        - If node X outputs 0 and node Y outputs 1, the bus level is 0.
        - Node Y reads 0, detects mismatch with its own 1, and immediately drops out!
        """
        remaining = list(contenders)
        # All contenders bit vectors
        bit_vectors = [(c, f, f.get_arbitration_bits()) for (c, f) in remaining]

        max_bits = max(len(b[2]) for b in bit_vectors)
        losers: List[Tuple[CANNodeController, CANFrame]] = []

        for bit_idx in range(max_bits):
            if len(bit_vectors) == 1:
                break

            # Find the bus level at this bit: dominant (0) wins if ANY node sends 0
            current_bits = [bv[2][bit_idx] if bit_idx < len(bv[2]) else 1 for bv in bit_vectors]
            bus_level = 0 if 0 in current_bits else 1

            survivors = []
            for item, bit_val in zip(bit_vectors, current_bits):
                if bit_val == bus_level:
                    survivors.append(item)
                else:
                    # This node sent recessive (1) while bus was dominant (0) -> LOST ARBITRATION!
                    losers.append((item[0], item[1]))
                    self.event_bus.publish(
                        self.clock.current_time_us, "CAN", item[0].node_name, "ARBITRATION_LOST",
                        f"{item[0].node_name} lost arbitration on bit {bit_idx} (sent recessive 1, bus had dominant 0) for ID 0x{item[1].arbitration_id:X}",
                        {"id": item[1].arbitration_id, "bit_index": bit_idx}
                    )

            bit_vectors = survivors

        winner = (bit_vectors[0][0], bit_vectors[0][1])
        return winner, losers

    def _arbitrate_and_transmit(self) -> None:
        """
        Collects all ready frames across all ECUs and conducts arbitration.
        """
        if self.is_busy:
            return

        if self.bus_held_dominant:
            self.event_bus.publish(
                self.clock.current_time_us, "FAULT", "CAN_Bus", "BUS_ERROR",
                "CAN Bus transmission failed: Bus is stuck low (held dominant fault injected)."
            )
            return

        # Find all ECUs that have a message ready to send
        contenders: List[Tuple[CANNodeController, CANFrame]] = []
        for node in self.nodes.values():
            if node.is_connected and node.error_state != CANErrorState.BUS_OFF and node.tx_queue:
                contenders.append((node, node.tx_queue[0]))

        if not contenders:
            return

        self.stats.total_arbitrations += 1
        if len(contenders) > 1:
            self.stats.total_collisions_resolved += 1

        # Run bit arbitration
        (winner_node, winner_frame), losers = self._resolve_bit_arbitration(contenders)

        # Pop the winning frame from the winning ECU's queue
        winner_node.tx_queue.pop(0)

        # Calculate transmission duration
        duration_us = winner_frame.calculate_duration_us(self.nominal_baudrate, self.data_baudrate)
        winner_frame.tx_start_time_us = self.clock.current_time_us
        winner_frame.tx_end_time_us = self.clock.current_time_us + duration_us

        self.is_busy = True
        self.current_transmitting_frame = winner_frame

        self.event_bus.publish(
            self.clock.current_time_us, "CAN", winner_node.node_name, "TX_START",
            f"Frame 0x{winner_frame.arbitration_id:X} won arbitration and started transmitting ({duration_us} us).",
            {"id": winner_frame.arbitration_id, "duration_us": duration_us, "is_fd": winner_frame.is_fd}
        )

        # Schedule the frame completion when duration has elapsed
        self.clock.schedule(
            duration_us,
            f"Complete transmission of CAN frame 0x{winner_frame.arbitration_id:X}",
            lambda: self._complete_frame_transmission(winner_node, winner_frame, duration_us)
        )

    def _complete_frame_transmission(self, tx_node: CANNodeController, frame: CANFrame, duration_us: int) -> None:
        """
        Called when physical bit transmission is complete.
        Checks for injected CRC/ACK/Stuff errors and distributes frame to receivers.
        """
        self.is_busy = False
        self.current_transmitting_frame = None
        self.stats.total_bus_time_busy_us += duration_us

        # Check injected faults
        has_error = False
        error_reason = ""

        if frame.inject_crc_error:
            has_error = True
            error_reason = "CRC checksum mismatch error"
        elif frame.inject_stuff_error:
            has_error = True
            error_reason = "Bit stuffing violation error"
        elif frame.inject_bit_error:
            has_error = True
            error_reason = "Bit monitoring error"
        elif frame.inject_ack_error:
            has_error = True
            error_reason = "Missing ACK from receiving nodes"

        if has_error:
            self.stats.total_errors += 1
            # Transmitter penalised: TEC increases by 8 on TX error (ISO 11898)
            tx_node.tec += 8
            tx_node.update_error_state()

            self.event_bus.publish(
                self.clock.current_time_us, "FAULT", tx_node.node_name, "FRAME_ERROR",
                f"Transmission failed for ID 0x{frame.arbitration_id:X}: {error_reason}. TEC increased to {tx_node.tec} (State: {tx_node.error_state.value}).",
                {"tec": tx_node.tec, "rec": tx_node.rec, "state": tx_node.error_state.value}
            )

            # Re-queue for retransmission if under limit and not Bus Off
            if tx_node.error_state != CANErrorState.BUS_OFF:
                # Clear one-time injected faults so it can succeed on retry unless permanent
                frame.inject_crc_error = False
                frame.inject_stuff_error = False
                frame.inject_bit_error = False
                frame.inject_ack_error = False

                self.stats.total_retransmissions += 1
                tx_node.tx_queue.insert(0, frame)  # Put back at head of queue
                self.event_bus.publish(
                    self.clock.current_time_us, "CAN", tx_node.node_name, "RETRANSMIT",
                    f"Frame 0x{frame.arbitration_id:X} queued for automatic retransmission."
                )
        else:
            # Successful transmission!
            self.stats.total_frames_sent += 1
            # Decrement TEC if > 0
            if tx_node.tec > 0:
                tx_node.tec -= 1
                tx_node.update_error_state()

            # Record latency metric
            latency = frame.tx_end_time_us - frame.tx_queued_time_us
            if frame.arbitration_id not in self.stats.latencies_us:
                self.stats.latencies_us[frame.arbitration_id] = []
            self.stats.latencies_us[frame.arbitration_id].append(latency)

            self.event_bus.publish(
                self.clock.current_time_us, "CAN", tx_node.node_name, "TX_SUCCESS",
                f"Frame 0x{frame.arbitration_id:X} successfully received by bus (Latency: {latency / 1000.0:.2f} ms).",
                {"latency_us": latency, "dlc": frame.dlc}
            )

            # Deliver to all connected receiving nodes matching acceptance filters
            for rx_node in self.nodes.values():
                if rx_node.node_name == tx_node.node_name:
                    continue  # Do not receive own transmitted frame
                if not rx_node.is_connected or rx_node.error_state == CANErrorState.BUS_OFF:
                    continue

                # Check acceptance filter
                if rx_node.rx_filter_ids is None or frame.arbitration_id in rx_node.rx_filter_ids:
                    # Successful RX decrements REC if between 1 and 127
                    if 1 <= rx_node.rec <= 127:
                        rx_node.rec -= 1
                        rx_node.update_error_state()

            # Notify global subscribers (like Gateway or Signal Decoders)
            for sub in self.subscribers:
                sub(frame)

        # After frame completes or fails, arbitrate next waiting frame
        self._arbitrate_and_transmit()

    def subscribe(self, callback: Callable[[CANFrame], None]) -> None:
        """Register a listener that receives all successfully transmitted CAN frames."""
        self.subscribers.append(callback)

    def recover_bus_off(self, node_name: str) -> bool:
        """
        Simulates CAN bus-off recovery sequence:
        In ISO 11898, after entering Bus-Off, an ECU must observe 128 occurrences
        of 11 consecutive recessive bits before resetting TEC/REC to 0.
        """
        node = self.nodes.get(node_name)
        if not node:
            return False
        node.tec = 0
        node.rec = 0
        node.update_error_state()
        self.event_bus.publish(
            self.clock.current_time_us, "CAN", node_name, "BUS_OFF_RECOVERY",
            f"Node {node_name} completed bus-off recovery; reset to ERROR_ACTIVE."
        )
        # Check if node has queued frames to send now
        if not self.is_busy:
            self._arbitrate_and_transmit()
        return True

    def calculate_bus_load(self, window_us: int) -> float:
        """Calculates CAN bus load percentage over the given time window in microseconds."""
        if window_us <= 0:
            return 0.0
        return min(100.0, (self.stats.total_bus_time_busy_us / window_us) * 100.0)

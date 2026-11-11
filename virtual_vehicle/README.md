# Virtual Vehicle Platform (Software-in-the-Loop)

> **Hardware-independent test environment for CAN/CAN FD, Automotive Ethernet, ECU Behavior, and Secure Over-The-Air (OTA) Updates.**  
> Strictly designed according to the **Virtual Vehicle Platform System Design Report**.

---

## 1. Overview for Beginners

Modern vehicles are complex distributed computer networks on wheels. Instead of needing thousands of dollars worth of physical microcontrollers, wires, and oscilloscopes, this platform provides a **pure Python, zero-hardware Software-in-the-Loop (SiL) simulator**.

It allows you to:
1. **Watch CAN Bus Arbitration**: Observe how ECUs resolve bus conflicts bit-by-bit (lower numerical ID wins dominant bits).
2. **Observe Automotive Ethernet & Gateway**: See how a Central Gateway filters CAN messages and converts authorized signals into SOME/IP events on Ethernet.
3. **Experience Safety-Critical Fallbacks**: Watch the Brake ECU automatically switch to `DEGRADED` mode and log a Diagnostic Trouble Code (`DTC C0031`) when sensor data times out.
4. **Execute Secure Over-The-Air (OTA) Updates**: Run the complete 10-step secure update sequence with dual-slot (A/B) partitions and automatic rollback.

---

## 2. System Architecture (5 Layers)

The platform is strictly organized into the 5 layers specified in Section 1.5 of the design report:

| Layer | Folder | What it Models |
|---|---|---|
| **1. Scenario & Control Plane** | `core/clock.py` | Discrete-event simulation clock coordinating exact microsecond event schedules. |
| **2. Network Plane** | `can/`, `ethernet/`, `gateway/` | CAN/CAN FD shared bus, bit arbitration, error counters (TEC/REC), Ethernet switch, 802.1Q VLANs, and Security Gateway whitelist router. |
| **3. ECU Plane** | `ecu/` | The 5 Reference ECUs: Powertrain, Brake, Body, Gateway, and Telematics with power state machines (`OFF`, `BOOTING`, `OPERATIONAL`, `DEGRADED`, `PROGRAMMING`, `RECOVERY`). |
| **4. Security & Update Plane** | `can/secoc.py`, `ota/` | AUTOSAR SecOC freshness/MAC verification, device TLS certificates, dual-slot (A/B) firmware manager, anti-downgrade counters, and 10-step OTA orchestrator. |
| **5. Observability Plane** | `core/event_bus.py`, `core/logger.py` | Real-time event timeline, colorized console logger, and machine-readable JSON & CSV test report exporters. |

---

## 3. Quick Start (How to Run)

The platform requires **only standard Python 3.8+** (no third-party dependencies required).

### Option A: Run the Master Test Suite (Validation Matrix)
To run all 22 automated acceptance tests covering Suites A through E:
```bash
python run_all_tests.py
```
*This automatically generates `reports/validation_matrix_results.json` and `reports/validation_matrix_results.csv`.*

---

### Option B: Run Interactive Demonstration Scenarios
You can launch an interactive menu:
```bash
python run_simulation.py
```
Or run any of the 6 pre-built scenarios directly using the `--scenario` flag:

#### Scenario 1: Normal Driving & Cross-Network Telemetry
```bash
python run_simulation.py --scenario 1
```
*Shows Powertrain broadcasting speed (0x100) and wheel speed (0x250) on CAN, while the Gateway checks its security whitelist, translates whitelisted signals into SOME/IP notifications, and transmits them on Ethernet.*

#### Scenario 2: CAN Bit-Level Arbitration
```bash
python run_simulation.py --scenario 2
```
*Demonstrates simultaneous transmission of 0x100 (Powertrain) and 0x200 (Body). 0x100 wins arbitration bit-by-bit because lower IDs transmit dominant bits (0s) that override recessive bits (1s).*

#### Scenario 3: Safety Fault Injection (Timeout -> Degraded State)
```bash
python run_simulation.py --scenario 3
```
*Demonstrates ECU safety monitoring. When the wheel speed sensor message stops for >60ms, the Brake ECU detects the timeout, logs Diagnostic Trouble Code `DTC C0031`, and switches from `OPERATIONAL` to `DEGRADED` safe mode.*

#### Scenario 4: Cybersecurity Protection & Gateway Policy
```bash
python run_simulation.py --scenario 4
```
*Demonstrates cyberattack defenses: (1) An attacker injecting unauthorized CAN ID 0x666 is blocked by the Gateway whitelist; (2) A bus flooding attack exceeding 100 Hz is blocked by Gateway rate limiting.*

#### Scenario 5: Complete 10-Step Secure OTA Update
```bash
python run_simulation.py --scenario 5
```
*Walks through the complete secure update sequence:*
1. Mutual TLS authentication
2. Vehicle inventory check
3. Safe precondition check (stationary & parked)
4. Chunked package download & SHA-256 chunk verification
5. Digital signature verification against OEM root key
6. Inactive partition staging & anti-downgrade check
7. Vehicle switches into `PROGRAMMING` state
8. Candidate image activation & secure boot
9. Post-install smoke tests
10. Campaign `CONFIRMED` on Slot B

#### Scenario 6: OTA Failure & Automatic Rollback
```bash
python run_simulation.py --scenario 6
```
*Simulates flashing a defective firmware build. When post-install health checks fail at Step 9, the bootloader automatically reverts the active partition back to last-known-good Slot A (`v1.0.0`), protecting vehicle availability.*

---

### Option C: Inspect Synchronized Timeline & Export Standard Traces
You can view events in real time or filter by time window and node:
```bash
# View timeline between 10ms and 50ms for CAN domain
python view_timeline.py --from-ms 10 --to-ms 50 --category CAN

# Filter only events from Brake_ECU
python view_timeline.py --node Brake_ECU

# Export standard Vector CANoe/CANalyzer trace (.asc) and multi-protocol log (.log)
python view_timeline.py --export-traces
```
*Generates `reports/can_bus_traffic.asc` and `reports/synchronized_timeline.log`.*

---

## 4. Key Concepts Simplified

### Why Does Dominant 0 Win in CAN?
In CAN bus electrical wiring, a `0` is driven by applying voltage across the wires (Dominant), while a `1` is left floating (Recessive). If Node A drives `0` and Node B leaves `1`, the wire reads `0`. Node B reads `0`, realizes someone else has a higher priority message, and immediately backs off.

### What is AUTOSAR SecOC?
Classical CAN does not authenticate who sent a message. SecOC (Secure Onboard Communication) appends:
1. **Freshness Counter**: Increments with every message to stop hackers from recording and replaying old messages.
2. **MAC (Message Authentication Code)**: A cryptographic signature proving the message came from an authentic ECU.

### What is A/B Partitioning?
An ECU has two storage banks: **Slot A** and **Slot B**.
While the car is driving using Slot A, the update downloads and writes to Slot B in the background. If Slot B fails to boot or fails its health check, the ECU instantly reboots back into Slot A with zero downtime or bricking risk.


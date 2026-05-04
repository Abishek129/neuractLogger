"""
Modbus TCP Simulator — realistic 3-phase MFM power meter.

Registers (holding registers, float32 big-endian, 2 regs each):
  0-1:   Voltage L1-N (V)     ~230V ±3%
  2-3:   Voltage L2-N (V)     ~229V ±3%
  4-5:   Voltage L3-N (V)     ~231V ±3%
  6-7:   Current L1 (A)       ~45A ±10%
  8-9:   Current L2 (A)       ~44A ±10%
  10-11: Current L3 (A)       ~46A ±10%
  12-13: Active Power (kW)    computed
  14-15: Reactive Power (kVAR) computed
  16-17: Power Factor          ~0.87 ±0.05
  18-19: Frequency (Hz)       ~50.0 ±0.05

Run: python modbus_simulator.py [--port 5020] [--unit-ids 1,2,3]
"""
import argparse
import asyncio
import math
import random
import struct
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SIM] %(message)s")
log = logging.getLogger("modbus_sim")

# Global register store: {unit_id: [100 x uint16]}
REGISTERS = {}


def float32_to_regs(value: float) -> tuple:
    packed = struct.pack(">f", value)
    hi, lo = struct.unpack(">HH", packed)
    return hi, lo


def set_float(unit_id, addr, val):
    hi, lo = float32_to_regs(val)
    REGISTERS[unit_id][addr] = hi
    REGISTERS[unit_id][addr + 1] = lo


async def update_loop(unit_ids):
    """Update register values every second with realistic fluctuation."""
    t = 0
    while True:
        await asyncio.sleep(1)
        t += 1
        for uid in unit_ids:
            random.seed(uid * 10000 + t)
            v_base = 230.0 + uid * 0.3
            v1 = v_base + 3 * math.sin(t * 0.01) + random.gauss(0, 0.5)
            v2 = v_base - 1 + 3 * math.sin(t * 0.01 + 2.09) + random.gauss(0, 0.5)
            v3 = v_base + 1 + 3 * math.sin(t * 0.01 + 4.19) + random.gauss(0, 0.5)
            load = 0.7 + 0.3 * math.sin(t * 0.002)
            i1 = (45.0 + uid * 2) * load + random.gauss(0, 1.0)
            i2 = (44.0 + uid * 2) * load + random.gauss(0, 1.0)
            i3 = (46.0 + uid * 2) * load + random.gauss(0, 1.0)
            pf = max(-1, min(1, 0.87 + random.gauss(0, 0.02)))
            hz = 50.0 + random.gauss(0, 0.02)
            v_avg = (v1 + v2 + v3) / 3
            i_avg = (abs(i1) + abs(i2) + abs(i3)) / 3
            kw = v_avg * i_avg * abs(pf) * math.sqrt(3) / 1000
            kvar = kw * math.tan(math.acos(min(abs(pf), 0.999))) if abs(pf) < 0.999 else 0

            set_float(uid, 0, v1)
            set_float(uid, 2, v2)
            set_float(uid, 4, v3)
            set_float(uid, 6, max(0, i1))
            set_float(uid, 8, max(0, i2))
            set_float(uid, 10, max(0, i3))
            set_float(uid, 12, max(0, kw))
            set_float(uid, 14, max(0, kvar))
            set_float(uid, 16, pf)
            set_float(uid, 18, hz)

        if t % 30 == 0:
            log.info(f"Tick {t}: V1={v1:.1f}V I1={i1:.1f}A PF={pf:.3f} kW={kw:.1f} Hz={hz:.3f}")


class ModbusRequestHandler(asyncio.Protocol):
    """Minimal Modbus TCP protocol handler."""

    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data):
        if len(data) < 12:
            return
        # MBAP header: transaction_id(2) + protocol_id(2) + length(2) + unit_id(1)
        tid = struct.unpack(">H", data[0:2])[0]
        uid = data[6]
        func = data[7]

        if func == 3:  # Read Holding Registers
            start = struct.unpack(">H", data[8:10])[0]
            count = struct.unpack(">H", data[10:12])[0]
            regs = REGISTERS.get(uid)
            if regs is None:
                # Exception: illegal function
                resp = struct.pack(">HHHBBB", tid, 0, 3, uid, func | 0x80, 2)
                self.transport.write(resp)
                return
            values = []
            for i in range(count):
                addr = start + i
                if 0 <= addr < len(regs):
                    values.append(regs[addr])
                else:
                    values.append(0)
            byte_count = count * 2
            resp_data = struct.pack(">HHHBBB", tid, 0, 3 + byte_count, uid, func, byte_count)
            for v in values:
                resp_data += struct.pack(">H", v)
            self.transport.write(resp_data)
        else:
            # Unsupported function
            resp = struct.pack(">HHHBBB", tid, 0, 3, uid, func | 0x80, 1)
            self.transport.write(resp)


async def main():
    parser = argparse.ArgumentParser(description="Modbus TCP MFM Simulator")
    parser.add_argument("--port", type=int, default=5020)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--unit-ids", default="1,2,3")
    args = parser.parse_args()

    unit_ids = [int(x.strip()) for x in args.unit_ids.split(",")]

    # Initialize registers
    for uid in unit_ids:
        REGISTERS[uid] = [0] * 100

    log.info(f"Starting Modbus TCP simulator on {args.host}:{args.port}")
    log.info(f"Unit IDs: {unit_ids}")
    log.info(f"10 float32 params: V_L1-L3, I_L1-L3, kW, kVAR, PF, Hz")

    # Start updater
    asyncio.create_task(update_loop(unit_ids))

    # Start TCP server
    loop = asyncio.get_event_loop()
    server = await loop.create_server(ModbusRequestHandler, args.host, args.port)
    log.info(f"Listening on {args.host}:{args.port}")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())

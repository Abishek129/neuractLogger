"""
Modbus TCP Test Server

This server mimics the structure of opc_server2.py but for Modbus protocol.
Creates 10 logical "devices" with auto-updating temperature values for baseline testing.

Usage:
    python modbus_server.py

Server endpoint: 127.0.0.1:5502 (Modbus TCP)

Register Layout:
- 40001-40010: Device1 (holding registers)
- 40011-40020: Device2
- ...
- 40091-40100: Device10

Each device block (10 registers):
  - Registers 0-1: Temperature (float, ABCD byte order, 20-100°C)
  - Register 2: Pressure (int, 0-1000 PSI)
  - Register 3: FlowRate (int, 0-500 L/min)
  - Register 4: Status (int, 0-3)
  - Registers 5-9: Reserved

Additional registers:
- 10001-10010: Coils for Device1-10 AlarmActive (boolean)
- 10011: FlipBit trigger (toggles every 1-20 seconds)
- 30001-30010: Input registers for Device1-10 (read-only counters)
"""

import struct
import time
import random
import asyncio
import logging
from datetime import datetime
from pymodbus.server import StartAsyncTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def _encode_float(value: float, byte_order: str = "ABCD") -> tuple[int, int]:
    """
    Encode a float value to two 16-bit register values.

    Args:
        value: Float value to encode
        byte_order: Byte order - "ABCD" (big-endian), "DCBA" (little-endian),
                   "BADC" (mid-big), "CDAB" (mid-little)

    Returns:
        Tuple of (reg1, reg2) as 16-bit unsigned integers
    """
    if byte_order == "ABCD":  # Big-endian
        bytes_data = struct.pack('>f', value)
    elif byte_order == "DCBA":  # Little-endian
        bytes_data = struct.pack('<f', value)
    elif byte_order == "BADC":  # Mid-big endian
        bytes_data = struct.pack('>f', value)
        bytes_data = bytes_data[2:4] + bytes_data[0:2]
    elif byte_order == "CDAB":  # Mid-little endian
        bytes_data = struct.pack('<f', value)
        bytes_data = bytes_data[2:4] + bytes_data[0:2]
    else:
        raise ValueError(f"Unknown byte_order: {byte_order}")

    # Unpack as two 16-bit unsigned integers (big-endian)
    reg1, reg2 = struct.unpack('>HH', bytes_data)
    return reg1, reg2


def _decode_float(reg1: int, reg2: int, byte_order: str = "ABCD") -> float:
    """
    Decode a float value from two 16-bit register values.

    Args:
        reg1: First 16-bit register
        reg2: Second 16-bit register
        byte_order: Byte order (same as _encode_float)

    Returns:
        Decoded float value
    """
    bytes_data = struct.pack('>HH', reg1, reg2)

    if byte_order == "ABCD":
        return struct.unpack('>f', bytes_data)[0]
    elif byte_order == "DCBA":
        return struct.unpack('<f', bytes_data[::-1])[0]
    elif byte_order == "BADC":
        swapped = bytes_data[2:4] + bytes_data[0:2]
        return struct.unpack('>f', swapped)[0]
    elif byte_order == "CDAB":
        swapped = bytes_data[2:4] + bytes_data[0:2]
        return struct.unpack('<f', swapped)[0]
    else:
        raise ValueError(f"Unknown byte_order: {byte_order}")


class ModbusTestServer:
    """Modbus test server with auto-updating values"""

    def __init__(self):
        # Initialize data blocks
        self.holding_registers = ModbusSequentialDataBlock(0, [0] * 100)
        self.input_registers = ModbusSequentialDataBlock(0, [0] * 100)
        self.coils = ModbusSequentialDataBlock(0, [False] * 100)
        self.discrete_inputs = ModbusSequentialDataBlock(0, [False] * 100)

        # Device temperature states (random walk)
        self.device_temps = [random.uniform(40.0, 80.0) for _ in range(10)]

        # FlipBit state
        self.flip_bit_state = False
        self.next_flip_at = time.monotonic() + self._random_delay()

        # Initialize register values
        self._initialize_registers()

    def _random_delay(self) -> int:
        """Random delay between 1-20 seconds for FlipBit"""
        return random.randint(1, 20)

    def _initialize_registers(self):
        """Initialize all registers with starting values"""
        for i in range(10):
            # Device temperature (float at registers 0-1, 10-11, etc.)
            base_offset = i * 10
            temp = self.device_temps[i]
            reg1, reg2 = _encode_float(temp, "ABCD")
            self.holding_registers.setValues(base_offset, [reg1, reg2])

            # Pressure (int at register 2, 12, etc.)
            pressure = random.randint(100, 800)
            self.holding_registers.setValues(base_offset + 2, [pressure])

            # FlowRate (int at register 3, 13, etc.)
            flow = random.randint(50, 400)
            self.holding_registers.setValues(base_offset + 3, [flow])

            # Status (int at register 4, 14, etc.) - 0=stopped, 1=starting, 2=running, 3=error
            status = 2  # running
            self.holding_registers.setValues(base_offset + 4, [status])

            # Input register counter (offset 0-9)
            self.input_registers.setValues(i, [0])

            # Coil AlarmActive (offset 0-9)
            self.coils.setValues(i, [random.choice([True, False])])

        # FlipBit coil (offset 10)
        self.coils.setValues(10, [self.flip_bit_state])

    async def update_values(self):
        """Background task to update register values every second"""
        while True:
            try:
                await asyncio.sleep(1)

                # Update all device temperatures (random walk)
                for i in range(10):
                    base_offset = i * 10

                    # Temperature random walk
                    self.device_temps[i] += random.uniform(-2.0, 2.0)
                    self.device_temps[i] = max(20.0, min(100.0, self.device_temps[i]))

                    reg1, reg2 = _encode_float(self.device_temps[i], "ABCD")
                    self.holding_registers.setValues(base_offset, [reg1, reg2])

                    # Update pressure (random)
                    pressure = random.randint(100, 800)
                    self.holding_registers.setValues(base_offset + 2, [pressure])

                    # Update flow rate (random)
                    flow = random.randint(50, 400)
                    self.holding_registers.setValues(base_offset + 3, [flow])

                    # Cycle status: 0 → 1 → 2 → 3 → 0
                    current_status = self.holding_registers.getValues(base_offset + 4, 1)[0]
                    new_status = (current_status + 1) % 4
                    self.holding_registers.setValues(base_offset + 4, [new_status])

                    # Increment input register counter
                    counter = self.input_registers.getValues(i, 1)[0]
                    self.input_registers.setValues(i, [(counter + 1) % 65536])

                # Update FlipBit coil
                now = time.monotonic()
                if now >= self.next_flip_at:
                    self.flip_bit_state = not self.flip_bit_state
                    self.coils.setValues(10, [self.flip_bit_state])
                    delay = self._random_delay()
                    self.next_flip_at = now + delay
                    log.info(f"[{datetime.now().strftime('%H:%M:%S')}] FlipBit toggled to {int(self.flip_bit_state)}; next flip in {delay}s.")

                # Randomly toggle AlarmActive coils every 5 seconds
                if int(now) % 5 == 0:
                    for i in range(10):
                        if random.random() < 0.2:  # 20% chance to toggle
                            current = self.coils.getValues(i, 1)[0]
                            self.coils.setValues(i, [not current])

                log.info(f"[{datetime.now().strftime('%H:%M:%S')}] Updated all device values.")

            except Exception as e:
                log.error(f"Error updating values: {e}")

    def get_context(self):
        """Get ModbusServerContext for the server"""
        return ModbusServerContext(
            devices={
                1: {  # Unit ID 1
                    'di': self.discrete_inputs,
                    'co': self.coils,
                    'hr': self.holding_registers,
                    'ir': self.input_registers
                }
            },
            single=False
        )


async def start_modbus_server():
    """Main entry point - start Modbus server"""
    log.info("Starting Modbus TCP Test Server...")

    # Create test server instance
    test_server = ModbusTestServer()
    context = test_server.get_context()

    # Print startup banner
    print("=" * 60)
    print("Modbus TCP Server running at 127.0.0.1:5502")
    print("=" * 60)
    print("Serving 10 devices with auto-updating values:")
    print("   - Temperature (float): 40001-40002, 40011-40012, ..., 40091-40092")
    print("   - Pressure (int): 40003, 40013, ..., 40093")
    print("   - FlowRate (int): 40004, 40014, ..., 40094")
    print("   - Status (int): 40005, 40015, ..., 40095")
    print("   - AlarmActive (coil): 10001-10010")
    print("   - FlipBit (coil): 10011")
    print("   - Counters (input): 30001-30010")
    print()
    print("Unit ID: 1")
    print("Press Ctrl+C to stop.")
    print("=" * 60)
    print()

    # Start background update task
    asyncio.create_task(test_server.update_values())

    # Start server (this blocks)
    await StartAsyncTcpServer(
        context=context,
        address=("127.0.0.1", 5502)
    )


if __name__ == "__main__":
    try:
        asyncio.run(start_modbus_server())
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        log.info("Server stopped.")

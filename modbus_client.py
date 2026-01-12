"""
Simple Modbus TCP Test Client

Connects to modbus_server.py and reads values from all 10 devices.
Useful for quick validation that the server is running correctly.

Usage:
    python modbus_client.py [--host HOST] [--port PORT]
"""

import sys
import struct
import argparse
from pymodbus.client import ModbusTcpClient


def _decode_float(reg1: int, reg2: int, byte_order: str = "ABCD") -> float:
    """Decode float from two 16-bit registers"""
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


def main(host="127.0.0.1", port=5502):
    """Connect to Modbus server and read all device values"""
    print("=" * 60)
    print(f"Connecting to Modbus server at {host}:{port}...")
    print("=" * 60)

    client = ModbusTcpClient(host=host, port=port, timeout=3)

    if not client.connect():
        print(f"✗ Failed to connect to {host}:{port}")
        print("  Make sure modbus_server.py is running")
        return False

    print("✓ Connected successfully!\n")

    try:
        # Read all 10 device temperatures
        print("Device Temperatures:")
        print("-" * 60)
        for i in range(1, 11):
            # Calculate register offset (Device1=0, Device2=10, etc.)
            offset = (i - 1) * 10

            # Read temperature (2 registers)
            result = client.read_holding_registers(offset, count=2, device_id=1)
            if not result.isError():
                reg1, reg2 = result.registers
                temp = _decode_float(reg1, reg2, "ABCD")
                print(f"  Device{i:2d}: {temp:6.2f}°C (registers {40001 + offset}-{40002 + offset})")
            else:
                print(f"  Device{i:2d}: ERROR reading temperature")

        # Read pressure and flow from Device1
        print("\nDevice1 Additional Values:")
        print("-" * 60)
        result = client.read_holding_registers(2, count=3, device_id=1)
        if not result.isError():
            pressure, flow, status = result.registers
            status_names = ["stopped", "starting", "running", "error"]
            print(f"  Pressure: {pressure} PSI (register 40003)")
            print(f"  FlowRate: {flow} L/min (register 40004)")
            print(f"  Status: {status_names[status]} (register 40005)")

        # Read FlipBit coil
        print("\nTrigger Values:")
        print("-" * 60)
        result = client.read_coils(10, count=1, device_id=1)
        if not result.isError():
            flip_bit = result.bits[0]
            print(f"  FlipBit: {flip_bit} (coil 10011)")

        # Read AlarmActive coils
        print("\nAlarm Status:")
        print("-" * 60)
        result = client.read_coils(0, count=10, device_id=1)
        if not result.isError():
            for i, alarm in enumerate(result.bits[:10], 1):
                print(f"  Device{i:2d} Alarm: {'ACTIVE' if alarm else 'inactive'} (coil {10000 + i})")

        # Read input register counters
        print("\nInput Register Counters:")
        print("-" * 60)
        result = client.read_input_registers(0, count=10, device_id=1)
        if not result.isError():
            for i, counter in enumerate(result.registers, 1):
                print(f"  Device{i:2d} Counter: {counter} (input register {30000 + i})")

        print("\n" + "=" * 60)
        print("✓ All reads successful!")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n✗ Error reading from server: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple Modbus TCP test client")
    parser.add_argument("--host", default="127.0.0.1", help="Modbus server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5502, help="Modbus server port (default: 5502)")
    args = parser.parse_args()

    try:
        success = main(args.host, args.port)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)

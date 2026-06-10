#!/home/rohith/.pyenv/versions/3.11.9/bin/python3
"""
Minimal Modbus TCP simulator for testing derived parameters.
Serves MFM-style float32 registers on unit_id=9, port=5020.

Derived field under test:
  apparent_power_check = sqrt(active_power_total_kw^2 + reactive_power_total_kvar^2)
"""

import math
import random
import struct
import time
import threading
from pymodbus.server import StartTcpServer
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusDeviceContext,
    ModbusServerContext,
)

PORT = 5020
UNIT_ID = 9
BLOCK_SIZE = 130

BASE_VALUES = {
    0: 120.5,    # current_r
    2: 118.3,    # current_y
    4: 121.7,    # current_b
    6: 120.17,   # current_avg
    8: 415.2,    # voltage_ry
    10: 414.8,   # voltage_yb
    12: 415.5,   # voltage_br
    14: 415.17,  # voltage_ll_avg
    16: 239.8,   # voltage_r_n
    18: 240.1,   # voltage_y_n
    20: 239.5,   # voltage_b_n
    22: 239.8,   # voltage_ln_avg
    24: 0.92,    # power_factor_r
    26: 0.91,    # power_factor_y
    28: 0.93,    # power_factor_b
    30: 0.92,    # power_factor_total
    32: 50.01,   # frequency_hz
    34: 250.0,   # active_power_r_kw
    36: 245.0,   # active_power_y_kw
    38: 249.7,   # active_power_b_kw
    40: 744.7,   # active_power_total_kw
    42: 90.0,    # reactive_power_r_kvar
    44: 92.5,    # reactive_power_y_kvar
    46: 95.1,    # reactive_power_b_kvar
    48: 277.6,   # reactive_power_total_kvar
    50: 265.0,   # apparent_power_r_kva
    52: 262.0,   # apparent_power_y_kva
    54: 267.0,   # apparent_power_b_kva
    56: 794.0,   # apparent_power_total_kva
    58: 2.1,     # thd_voltage_r_pct
    60: 2.3,     # thd_voltage_y_pct
    62: 2.0,     # thd_voltage_b_pct
    64: 5.5,     # thd_current_r_pct
    66: 5.8,     # thd_current_y_pct
    68: 5.3,     # thd_current_b_pct
    70: 15234.5, # active_energy_import_kwh
    72: 120.3,   # active_energy_export_kwh
    74: 4521.2,  # reactive_energy_import_kvarh
    76: 45.8,    # reactive_energy_export_kvarh
}


def float32_to_regs(val):
    raw = struct.pack(">f", val)
    hi = struct.unpack(">H", raw[0:2])[0]
    lo = struct.unpack(">H", raw[2:4])[0]
    return hi, lo


def write_values(slave, values):
    for addr, val in values.items():
        hi, lo = float32_to_regs(val)
        slave.setValues(3, addr, [hi, lo])


def update_loop(context):
    while True:
        time.sleep(1)
        slave = context[UNIT_ID]
        current = {}
        for addr, base in BASE_VALUES.items():
            jitter = base * random.uniform(-0.02, 0.02)
            current[addr] = base + jitter
        write_values(slave, current)

        kw = current[40]
        kvar = current[48]
        expected = math.sqrt(kw**2 + kvar**2)
        print(f"[SIM] kW={kw:.2f} kVAR={kvar:.2f} expected_derived={expected:.4f}", flush=True)


def main():
    slave = ModbusDeviceContext(
        hr=ModbusSequentialDataBlock(0, [0] * BLOCK_SIZE),
        ir=ModbusSequentialDataBlock(0, [0] * BLOCK_SIZE),
        co=ModbusSequentialDataBlock(0, [0] * BLOCK_SIZE),
        di=ModbusSequentialDataBlock(0, [0] * BLOCK_SIZE),
    )
    context = ModbusServerContext(devices={UNIT_ID: slave}, single=False)

    # Write initial values
    write_values(slave, BASE_VALUES)

    updater = threading.Thread(target=update_loop, args=(context,), daemon=True)
    updater.start()

    print(f"Modbus TCP simulator running on 0.0.0.0:{PORT}, unit_id={UNIT_ID}")
    print(f"Serving {len(BASE_VALUES)} float32 fields")
    print(f"Derived test: apparent_power_check = sqrt(kW^2 + kVAR^2)")
    StartTcpServer(context=context, address=("0.0.0.0", PORT))


if __name__ == "__main__":
    main()

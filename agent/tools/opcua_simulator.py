"""Minimal OPC UA server for tests: a few float nodes that change every second.

    python tools/opcua_simulator.py --port 48400

Nodes (namespace index 2, string ids):
    ns=2;s=Voltage_L1   ~230 V
    ns=2;s=Current_L1   ~10 A
    ns=2;s=Frequency    ~50 Hz
    ns=2;s=Counter      int, +1 per second
"""
from __future__ import annotations

import argparse
import math
import time

from opcua import Server, ua


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=48400)
    args = ap.parse_args()

    server = Server()
    server.set_endpoint(f"opc.tcp://127.0.0.1:{args.port}/neuract/sim/")
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
    idx = server.register_namespace("urn:neuract:sim")
    assert idx == 2, idx
    obj = server.get_objects_node().add_object(ua.NodeId("Meter", idx), "Meter")

    def var(name: str, value, vtype):
        return obj.add_variable(ua.NodeId(name, idx), name, ua.Variant(value, vtype))

    volts = var("Voltage_L1", 230.0, ua.VariantType.Double)
    amps = var("Current_L1", 10.0, ua.VariantType.Float)
    freq = var("Frequency", 50.0, ua.VariantType.Double)
    count = var("Counter", 0, ua.VariantType.Int32)

    server.start()
    print(f"opcua simulator on opc.tcp://127.0.0.1:{args.port}/neuract/sim/", flush=True)
    try:
        n = 0
        while True:
            n += 1
            volts.set_value(ua.Variant(230.0 + 5.0 * math.sin(n / 5.0), ua.VariantType.Double))
            amps.set_value(ua.Variant(10.0 + math.cos(n / 3.0), ua.VariantType.Float))
            freq.set_value(ua.Variant(50.0 + 0.05 * math.sin(n), ua.VariantType.Double))
            count.set_value(ua.Variant(n, ua.VariantType.Int32))
            time.sleep(1.0)
    finally:
        server.stop()


if __name__ == "__main__":
    main()

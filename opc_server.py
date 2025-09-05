from opcua import Server, ua
import time
import random
from datetime import datetime

# Set up the OPC UA server
server = Server()
server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")
uri = "http://example.com/opcua/dummynodes/"
idx = server.register_namespace(uri)

# Get root Objects node
objects_node = server.get_objects_node()

# Create 10 object nodes (e.g., Device1 to Device10)
devices = []
for i in range(1, 11):
    device_name = f"Device{i}"

    device = objects_node.add_object(
        nodeid=ua.NodeId(device_name, idx),
        bname=device_name
    )

    temp_var = device.add_variable(
        nodeid=ua.NodeId(f"{device_name}.Temperature", idx),
        bname="Temperature",
        val=0.0,
        varianttype=ua.VariantType.Float
    )

    temp_var.set_writable()
    devices.append((device, temp_var))

# Start the server
server.start()
print("✅ OPC UA Server running at opc.tcp://localhost:4840/freeopcua/server/")
print("📡 Serving 10 object nodes with random temperature updates...\nPress Ctrl+C to stop.")

try:
    while True:
        for device, var in devices:
            value = round(random.uniform(20.0, 100.0), 2)
            var.set_value(value)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Updated all device temperatures.")
        time.sleep(1)
except KeyboardInterrupt:
    print("\n🛑 Stopping server...")
finally:
    server.stop()

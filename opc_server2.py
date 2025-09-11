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

# Create 10 object nodes (Device1..Device10) with Temperature variables
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
    temp_var.set_writable()  # optional; keeps parity with your original
    devices.append((device, temp_var))

# --- NEW: A "bit" tag that flips 0/1 every 1..20 seconds ---
triggers_obj = objects_node.add_object(
    nodeid=ua.NodeId("Triggers", idx),
    bname="Triggers"
)

# Boolean FlipBit (toggles True/False → 0/1)
flip_bit = triggers_obj.add_variable(
    nodeid=ua.NodeId("Triggers.FlipBit", idx),
    bname="FlipBit",
    val=False,
    varianttype=ua.VariantType.Boolean
)
flip_bit.set_writable()  # optional

# If you prefer a numeric 0/1 instead of Boolean, use this instead:
# flip_bit = triggers_obj.add_variable(
#     nodeid=ua.NodeId("Triggers.FlipBit", idx),
#     bname="FlipBit",
#     val=0,
#     varianttype=ua.VariantType.Int16
# )

# Scheduler for random flips
def next_delay():
    return random.randint(1, 20)

next_flip_at = time.monotonic() + next_delay()

# Start the server
server.start()
print("✅ OPC UA Server running at opc.tcp://localhost:4840/freeopcua/server/")
print("📡 Serving 10 devices with Temperature and a random FlipBit.")
print(f"🔖 FlipBit NodeId: ns={idx};s=Triggers.FlipBit (Boolean)")
print("   Browse path: Objects → Triggers → FlipBit")
print("Press Ctrl+C to stop.\n")

try:
    while True:
        # Update all device temperatures every second
        for device, var in devices:
            value = round(random.uniform(20.0, 100.0), 2)
            var.set_value(value)

        # Flip the bit when its random timer elapses
        now = time.monotonic()
        if now >= next_flip_at:
            # For Boolean:
            curr = flip_bit.get_value()
            new_val = not curr
            flip_bit.set_value(new_val)
            # If using Int16 numeric 0/1, do:
            # curr = flip_bit.get_value()
            # new_val = 0 if curr == 1 else 1
            # flip_bit.set_value(new_val)

            delay = next_delay()
            next_flip_at = now + delay
            print(f"[{datetime.now().strftime('%H:%M:%S')}] FlipBit toggled to {int(bool(new_val))}; next flip in {delay}s.")

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Updated all device temperatures.")
        time.sleep(1)

except KeyboardInterrupt:
    print("\n🛑 Stopping server...")
finally:
    server.stop()

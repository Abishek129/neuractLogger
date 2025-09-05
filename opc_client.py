from opcua import Client, ua

client = Client("opc.tcp://localhost:4840/freeopcua/server/")
client.connect()

try:
    for i in range(1, 11):
        nodeid = f"ns=2;s=Device{i}.Temperature"
        node = client.get_node(nodeid)
        value = node.get_value()
        print(f"Device{i} Temperature: {value}")
finally:
    client.disconnect()
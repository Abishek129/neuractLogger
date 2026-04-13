# ESP32 Industrial Modbus Gateway — Agent Context

This is the master context file. Give this to a Claude Code agent along with the other files in this directory to build the firmware step by step.

---

## What we're building

An ESP32-based Modbus RTU gateway that:
1. Polls 10-12 MFM (Multifunction Meter) power meters over RS-485
2. Stores readings in a central in-memory data structure
3. Publishes data to cloud via MQTT over Ethernet
4. Serves a local HTTP REST API + web dashboard
5. Acts as a Modbus TCP server so local SCADA systems can read all meter data from one IP

## Hardware (final, confirmed)

| Component | Module | Interface | Purpose |
|-----------|--------|-----------|---------|
| MCU | ESP32-WROOM-32 DevKit | — | Main controller |
| RS-485 | MAX3485 (or SP3485) | UART2 | Modbus RTU to meters |
| Ethernet | W5500 SPI module | SPI | Network (MQTT, HTTP, Modbus TCP server) |

**No GSM/4G modem for now.** Will be added later.
**No second RS-485 bus for now.** Single bus, single MAX3485.
**No SPI flash (W25Q128) for now.** Data buffering added later.

## Pin Assignments (final)

```
ESP32 UART0 (default):  USB serial debug/programming (do not touch)

ESP32 UART2:
  GPIO17 (TX) → MAX3485 DI (Data In / driver input)
  GPIO16 (RX) ← MAX3485 RO (Receive Out)
  GPIO4        → MAX3485 DE + RE (tied together, direction control)

ESP32 SPI:
  GPIO18 (SCK)  → W5500 SCLK
  GPIO23 (MOSI) → W5500 MOSI
  GPIO19 (MISO) ← W5500 MISO
  GPIO5  (CS)   → W5500 SCS (chip select)

Power:
  ESP32 3.3V → MAX3485 VCC, W5500 VCC (if 3.3V variant)
  ESP32 GND  → MAX3485 GND, W5500 GND (common ground)
```

**IMPORTANT:** UART1 default pins (GPIO9/GPIO10) conflict with internal flash. Do NOT use UART1 with default pins. UART1 is reserved for future use (GSM modem) and will be remapped to GPIO33/GPIO32 when needed.

## Deployment Context

- 26 gateways total across the factory, each handling 10-12 meters
- 260 MFM panels total
- Meters are on RS-485 bus, daisy-chained, each with a unique Modbus slave address (1-247)
- Polling interval target: 1 second (1 Hz)
- Baud rate: 9600 default (most MFMs), configurable up to 115200
- Network: factory LAN via Ethernet, static IP per gateway

## Development Environment

- **IDE**: VS Code + PlatformIO extension
- **Framework**: Arduino (not ESP-IDF)
- **Board**: esp32dev (ESP32-WROOM-32)
- **Upload**: USB cable to DevKit
- **Monitor**: Serial at 115200 baud

## PlatformIO Configuration

```ini
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
lib_deps =
    knolleary/PubSubClient@^2.8
    bblanchon/ArduinoJson@^7
```

Note: W5500 Ethernet library is included in the ESP32 Arduino core — no extra lib_deps needed. Use `#include <Ethernet.h>` with the standard Arduino Ethernet library, OR use the ESP32-specific `ETH.h` approach. Recommend standard `Ethernet.h` library with W5500 for maximum portability.

Actually, for W5500 on SPI (not the ESP32's built-in EMAC), use:
```ini
lib_deps =
    arduino-libraries/Ethernet@^2.0.2
    knolleary/PubSubClient@^2.8
    bblanchon/ArduinoJson@^7
```

## Build Phases

Build and test each phase completely before moving to the next. Each phase has clear "done" criteria.

### Phase 1: Blink + Serial (verify dev environment)
- Flash a blink sketch to ESP32
- Print "Hello World" to Serial Monitor
- **Done when:** LED blinks, serial output visible at 115200 baud

### Phase 2: RS-485 Loopback (verify MAX3485 wiring)
- Initialize UART2 on GPIO17(TX)/GPIO16(RX) at 9600 baud
- Toggle GPIO4 (DE/RE) HIGH to transmit, LOW to receive
- Send known bytes, receive them on a USB-to-RS485 adapter on a PC
- **Test tool:** Use a USB-to-RS485 adapter + terminal program (or Modbus slave simulator like ModRSsim2/diagslave) on a PC
- **Done when:** ESP32 sends bytes → PC receives them; PC sends bytes → ESP32 receives them

### Phase 3: Modbus RTU Master (poll one meter)
- Implement Modbus RTU request frame builder
- Implement CRC-16/Modbus calculation (lookup table method)
- Implement DE/RE pin timing (flush + 200µs delay before switching to RX)
- Implement response parser with CRC verification
- Implement register decoding (uint16, float32 big-endian)
- Poll one meter (address 1) for registers 0-19, every 1 second
- Print decoded values to Serial Monitor
- **Test tool:** diagslave or ModRSsim2 on PC via USB-to-RS485 adapter, simulating a meter at address 1
- **Done when:** ESP32 correctly reads and decodes register values from simulated meter

### Phase 4: W5500 Ethernet (verify network)
- Initialize SPI and W5500 with static IP
- Print IP address to Serial Monitor
- Respond to ping
- **Test:** `ping <gateway-ip>` from any PC on the same LAN
- **Done when:** Ping succeeds, Ethernet link LED is on

### Phase 5: MQTT Publishing (data to cloud)
- Connect to MQTT broker over Ethernet (use test.mosquitto.org or local broker)
- Publish meter data as JSON every 5 seconds
- JSON format: `{"gateway":"GW-01","ts":1709913841,"meters":{"MFM_001":{"V_RN":230.1,"I_R":4.5}}}`
- **Test:** `mosquitto_sub -h broker -t "factory/GW-01/#"` on a PC
- **Done when:** JSON messages appear in subscriber with correct meter values

### Phase 6: Multi-Device Polling (10 meters)
- Configure 10 meter entries (addresses 1-10, configurable register ranges)
- Poll sequentially on single RS-485 bus
- Store results in central `meters[]` array
- Track per-meter success/error counts
- Measure and print total poll cycle time
- **Done when:** 10 simulated meters polled every 1 second, all values correct, cycle time printed

### Phase 7: HTTP REST API + Dashboard
- Serve `/api/meters` → JSON array of all meter data
- Serve `/api/meters/{index}` → single meter JSON
- Serve `/` → simple HTML dashboard with auto-refresh (JavaScript fetch every 2s)
- **Test:** Open browser to `http://<gateway-ip>/` and see live data
- **Done when:** Dashboard shows live updating meter values

### Phase 8: Modbus TCP Server (for SCADA)
- Listen on TCP port 502
- Virtual register mapping: Meter N → registers (N×20) to (N×20+19)
- Respond to Function 03 (Read Holding Registers) requests
- **Test:** Use QModMaster or pymodbus on a PC to read registers from gateway IP
- **Done when:** External Modbus TCP client reads correct meter values from gateway

## Key Design Principles

1. **Static allocation only** — no malloc in the main loop, no String class (use char arrays). ESP32 RAM fragments easily.
2. **Shared data store** — all tasks read/write the `meters[]` array. Polling tasks write, output tasks read. Use a mutex if using FreeRTOS tasks.
3. **Fail gracefully** — if a meter doesn't respond, log the error, skip it, move to the next. Never block the loop waiting for one dead meter.
4. **Configurable** — baud rate, meter addresses, register ranges, polling interval, IP addresses should all be configurable (initially as `#define` constants, later via web config page).
5. **Watchdog** — enable ESP32 hardware watchdog. If the main loop hangs for >10 seconds, auto-reboot.

## File Structure (recommended)

```
gateway-firmware/
├── platformio.ini
├── src/
│   ├── main.cpp              ← setup() + loop(), task creation
│   ├── config.h              ← all #define constants (pins, IPs, baud rates)
│   ├── modbus_rtu.h/.cpp     ← Modbus RTU master (frame build, CRC, parse)
│   ├── datastore.h/.cpp      ← MeterData struct, meters[] array, mutex
│   ├── ethernet_setup.h/.cpp ← W5500 init, IP config
│   ├── mqtt_client.h/.cpp    ← MQTT connect, publish, reconnect
│   ├── http_server.h/.cpp    ← REST API + dashboard HTML
│   └── modbus_tcp_server.h/.cpp ← Modbus TCP server (virtual register map)
├── docs/
│   ├── AGENT_CONTEXT.md      ← this file
│   ├── WIRING_GUIDE.md       ← physical wiring reference
│   ├── MODBUS_REFERENCE.md   ← protocol details
│   └── FIRMWARE_ARCHITECTURE.md ← code structure details
└── test/                      ← PlatformIO test directory
```

## References

- ESP32-WROOM-32 Datasheet: https://www.espressif.com/en/products/socs/esp32
- MAX3485 Datasheet: search "MAX3485 datasheet" (Maxim Integrated)
- W5500 Datasheet: search "W5500 datasheet" (WIZnet)
- Modbus RTU Specification: https://modbus.org/specs.php
- PlatformIO ESP32: https://docs.platformio.org/en/stable/boards/espressif32/esp32dev.html

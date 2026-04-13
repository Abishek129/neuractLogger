# Firmware Architecture — ESP32 Gateway

---

## Core Data Structure

All polling tasks write to this. All output tasks read from it. This is the central hub.

```cpp
// config.h

#define MAX_DEVICES       64
#define MAX_REGS_PER_DEV  40    // 20 float32 values = 40 registers
#define MAX_LABEL_LEN     16

// Bus type enum
enum BusType : uint8_t {
    BUS_RTU_1 = 0,   // RS-485 bus 1 (UART2)
    BUS_TCP   = 2     // Modbus TCP (Ethernet)
};

struct MeterConfig {
    bool      active;
    BusType   busType;
    uint8_t   slaveAddress;       // 1-247 for RTU
    IPAddress tcpAddress;          // for TCP meters (future)
    uint16_t  tcpPort;             // default 502
    uint16_t  startRegister;       // first register to read
    uint16_t  numRegisters;        // how many registers to read (max 125)
    char      label[MAX_LABEL_LEN]; // human-readable name, e.g. "MFM_001"
};

struct MeterData {
    MeterConfig config;
    uint16_t    registers[MAX_REGS_PER_DEV]; // raw register values from last poll
    uint32_t    lastPollTime;                 // millis() of last successful poll
    bool        lastPollSuccess;
    uint32_t    successCount;
    uint32_t    errorCount;
};
```

### Shared data store

```cpp
// datastore.h

#include "config.h"

extern MeterData meters[MAX_DEVICES];
extern uint8_t   meterCount;          // how many meters are configured
extern SemaphoreHandle_t metersMutex; // FreeRTOS mutex for thread safety

void datastore_init();
void datastore_lock();
void datastore_unlock();

// Helper to decode a float32 from two consecutive registers
float getFloat32(uint8_t meterIdx, uint8_t regOffset);
```

**Why a mutex?**
If the polling task is writing register values at the same time the MQTT task is reading them, you get torn reads (half old data, half new). The mutex ensures only one task accesses meters[] at a time. Lock before read/write, unlock after.

In practice, the lock is held for microseconds (just copying a few bytes), so no task is ever blocked for long.

---

## Task Structure

### Option A: Single-threaded (Arduino loop — simplest, start here)

```cpp
void loop() {
    // 1. Poll all meters sequentially
    unsigned long pollStart = millis();
    for (int i = 0; i < meterCount; i++) {
        if (!meters[i].config.active) continue;
        pollMeter(i);  // sends request, waits for response, stores in meters[i]
    }
    unsigned long pollTime = millis() - pollStart;

    // 2. Publish to MQTT (if connected)
    if (mqttClient.connected()) {
        publishMeterData();
    } else {
        mqttReconnect();
    }

    // 3. Handle HTTP requests
    handleHttpClients();

    // 4. Handle Modbus TCP server requests
    handleModbusTcpClients();

    // 5. Sleep remaining time
    unsigned long elapsed = millis() - pollStart;
    if (elapsed < POLL_INTERVAL_MS) {
        delay(POLL_INTERVAL_MS - elapsed);
    } else {
        // Overrun! Log it.
        Serial.printf("OVERRUN: loop took %lu ms\n", elapsed);
    }
}
```

This is fine for 10-12 meters at 9600 baud (~800ms poll cycle). It's simple and easy to debug. Use this for Phases 1-7.

### Option B: FreeRTOS tasks (for Phase 8 and beyond, when you need concurrency)

```cpp
void setup() {
    // ... init hardware ...

    xSemaphoreCreateMutex(&metersMutex);

    // Polling task on Core 1 (application core)
    xTaskCreatePinnedToCore(pollingTask, "poll", 4096, NULL, 2, NULL, 1);

    // MQTT task on Core 0 (protocol core)
    xTaskCreatePinnedToCore(mqttTask, "mqtt", 4096, NULL, 1, NULL, 0);

    // HTTP server task on Core 0
    xTaskCreatePinnedToCore(httpTask, "http", 4096, NULL, 1, NULL, 0);
}

void pollingTask(void *param) {
    while (true) {
        unsigned long start = millis();
        datastore_lock();
        for (int i = 0; i < meterCount; i++) {
            if (!meters[i].config.active) continue;
            pollMeter(i);
        }
        datastore_unlock();
        unsigned long elapsed = millis() - start;
        if (elapsed < POLL_INTERVAL_MS) {
            vTaskDelay(pdMS_TO_TICKS(POLL_INTERVAL_MS - elapsed));
        }
    }
}
```

ESP32 has 2 cores:
- **Core 0**: WiFi/BLE stack runs here by default. Good for network tasks (MQTT, HTTP).
- **Core 1**: Application core. Good for time-sensitive tasks (Modbus polling).

---

## Module Breakdown

### modbus_rtu.h / .cpp

```cpp
// Public API
void modbus_rtu_init(uint8_t uartNum, uint8_t txPin, uint8_t rxPin,
                     uint8_t dePin, uint32_t baudRate);

// Poll a single meter. Returns true if successful.
// On success, registers[] in meters[meterIdx] is updated.
bool modbus_rtu_poll(uint8_t meterIdx);

// Internal (but documented for understanding)
void     buildReadRequest(uint8_t slaveAddr, uint16_t startReg,
                          uint16_t regCount, uint8_t *frame);
uint16_t modbusCRC(const uint8_t *data, uint16_t length);
bool     sendAndReceive(const uint8_t *request, uint8_t reqLen,
                        uint8_t *response, uint16_t *respLen,
                        uint16_t timeoutMs);
bool     parseReadResponse(const uint8_t *response, uint16_t respLen,
                           uint8_t expectedAddr, uint16_t expectedRegs,
                           uint16_t *outRegisters);
```

### ethernet_setup.h / .cpp

```cpp
void ethernet_init();           // SPI.begin, Ethernet.begin with static IP
bool ethernet_isLinked();       // check W5500 link status
void ethernet_maintain();       // call in loop for DHCP renewal if using DHCP
IPAddress ethernet_localIP();   // get current IP
```

### mqtt_client.h / .cpp

```cpp
void mqtt_init(const char *broker, uint16_t port, const char *clientId);
bool mqtt_connected();
void mqtt_reconnect();          // non-blocking reconnect attempt
void mqtt_loop();               // must call every loop iteration (PubSubClient requirement)
void mqtt_publishMeters();      // serialize meters[] to JSON, publish
```

### http_server.h / .cpp

```cpp
void http_init();               // start server on port 80
void http_handle();             // call in loop to process requests

// Endpoints:
// GET /              → HTML dashboard
// GET /api/meters    → JSON array of all meters
// GET /api/status    → JSON with uptime, poll cycle time, error counts
```

### modbus_tcp_server.h / .cpp (Phase 8)

```cpp
void modbus_tcp_server_init();  // listen on port 502
void modbus_tcp_server_handle(); // call in loop

// Virtual register map:
// Meter 0 → registers 0 to (numRegs-1)
// Meter 1 → registers MAX_REGS_PER_DEV to (MAX_REGS_PER_DEV + numRegs - 1)
// Meter N → registers (N × MAX_REGS_PER_DEV) to (N × MAX_REGS_PER_DEV + numRegs - 1)
```

---

## Configuration Constants (config.h)

```cpp
// ── Pin Assignments ──
#define RS485_TX_PIN      17    // UART2 TX → MAX3485 DI
#define RS485_RX_PIN      16    // UART2 RX ← MAX3485 RO
#define RS485_DE_PIN       4    // Direction control → MAX3485 DE+RE

#define ETH_CS_PIN         5    // W5500 chip select
#define ETH_SCK_PIN       18    // SPI clock (default VSPI)
#define ETH_MOSI_PIN      23    // SPI MOSI (default VSPI)
#define ETH_MISO_PIN      19    // SPI MISO (default VSPI)

// ── RS-485 / Modbus RTU ──
#define MODBUS_BAUD       9600
#define MODBUS_SERIAL_CONFIG SERIAL_8N1
#define MODBUS_TIMEOUT_MS  500  // response timeout per device
#define MODBUS_TURNAROUND_US 200 // DE/RE switch delay (microseconds)

// ── Polling ──
#define POLL_INTERVAL_MS  1000  // 1 second between full poll cycles

// ── Network ──
#define ETH_MAC { 0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x01 }  // unique per gateway
#define ETH_IP      IPAddress(192, 168, 1, 100)
#define ETH_SUBNET  IPAddress(255, 255, 255, 0)
#define ETH_GATEWAY IPAddress(192, 168, 1, 1)
#define ETH_DNS     IPAddress(8, 8, 8, 8)

// ── MQTT ──
#define MQTT_BROKER   "192.168.1.50"   // or cloud broker address
#define MQTT_PORT     1883
#define MQTT_CLIENT   "GW-01"
#define MQTT_TOPIC    "factory/GW-01/meters"
#define MQTT_PUBLISH_INTERVAL_MS 5000  // publish every 5 seconds

// ── HTTP ──
#define HTTP_PORT 80

// ── Modbus TCP Server ──
#define MODBUS_TCP_SERVER_PORT 502
```

---

## JSON Output Format

### MQTT publish payload

```json
{
  "gw": "GW-01",
  "ts": 1709913841,
  "poll_ms": 650,
  "meters": [
    {
      "label": "MFM_001",
      "addr": 1,
      "ok": true,
      "regs": [230.1, 229.8, 230.5, 4.5, 3.2, 4.1, 15.2, 2.1, 0.98, 50.01]
    },
    {
      "label": "MFM_002",
      "addr": 2,
      "ok": true,
      "regs": [228.5, 229.1, 228.8, 5.1, 4.8, 5.3, 18.7, 3.2, 0.97, 50.02]
    }
  ]
}
```

- `ts`: Unix timestamp (from NTP or hardcoded epoch if no NTP)
- `poll_ms`: how long the last poll cycle took (for monitoring)
- `ok`: false if the meter didn't respond or CRC error
- `regs`: decoded float32 values in order (voltage L1, L2, L3, current L1, L2, L3, power, reactive, PF, freq)

### HTTP /api/meters response

Same format as MQTT payload but includes extra fields:

```json
{
  "gw": "GW-01",
  "uptime_sec": 3600,
  "total_polls": 3600,
  "total_errors": 12,
  "meters": [
    {
      "label": "MFM_001",
      "addr": 1,
      "bus": "RTU1",
      "ok": true,
      "success": 3598,
      "errors": 2,
      "last_poll_ms": 1709913841000,
      "values": {
        "V_L1": 230.1,
        "V_L2": 229.8,
        "V_L3": 230.5,
        "I_L1": 4.5,
        "I_L2": 3.2,
        "I_L3": 4.1,
        "kW": 15.2,
        "kVAR": 2.1,
        "PF": 0.98,
        "Hz": 50.01
      }
    }
  ]
}
```

---

## Memory Budget

ESP32-WROOM-32: 520 KB SRAM total. ~300 KB available after Arduino framework + WiFi stack.

| Component | RAM Usage | Notes |
|-----------|-----------|-------|
| meters[64] | ~6 KB | 64 × (config + 80 bytes regs + counters) ≈ 96 bytes each |
| Modbus TX/RX buffers | 512 bytes | 256 bytes each, static |
| JSON buffer | 4 KB | ArduinoJson StaticJsonDocument |
| Ethernet (W5500) | 2 KB | Socket buffers managed by W5500 hardware |
| MQTT (PubSubClient) | 1 KB | Configurable buffer size |
| HTTP response buffer | 2 KB | For HTML dashboard + JSON |
| Stack (main task) | 8 KB | Default Arduino loop task |
| Stack (extra tasks) | 4 KB each | If using FreeRTOS |
| **Total** | **~25 KB** | Well within 300 KB budget |

Plenty of headroom. No need to worry about RAM for this application.

---

## Error Handling Strategy

| Error | Action | Recovery |
|-------|--------|----------|
| Meter timeout | Log, increment error counter, skip to next meter | Retry next poll cycle |
| CRC mismatch | Log, increment error counter, skip | Retry next cycle |
| W5500 link down | Log, keep polling meters (data stored locally in meters[]) | Retry Ethernet init every 10 seconds |
| MQTT disconnect | Log, keep polling, retry connect every 5 seconds | Auto-reconnect |
| MQTT publish fail | Log, discard payload (or buffer if flash available) | Retry next publish interval |
| HTTP client disconnect | Close socket, continue | Accept next client |
| Watchdog timeout | Auto-reboot ESP32 | Hardware reset |

---

## Watchdog

```cpp
#include "esp_task_wdt.h"

void setup() {
    esp_task_wdt_init(10, true);  // 10 second timeout, auto-reboot on trigger
    esp_task_wdt_add(NULL);       // add current task (loop) to watchdog
}

void loop() {
    esp_task_wdt_reset();  // feed the watchdog every loop iteration
    // ... rest of loop ...
}
```

If the main loop hangs (e.g., stuck waiting for a Modbus response due to a bug), the watchdog reboots the ESP32 after 10 seconds. The device comes back up and resumes polling automatically.

# Modbus RTU Protocol Reference — For ESP32 Firmware

This document covers everything needed to implement a Modbus RTU master on ESP32.

---

## Frame Format

### Request (Master → Slave)

Read Holding Registers (Function 0x03):
```
Byte 0:    Slave Address    (1-247, 0 = broadcast)
Byte 1:    Function Code    (0x03)
Byte 2-3:  Start Register   (big-endian, 0-based)
Byte 4-5:  Register Count   (big-endian, 1-125 max)
Byte 6-7:  CRC-16           (little-endian! low byte first)
```

Total: 8 bytes always.

### Response (Slave → Master)

```
Byte 0:    Slave Address    (echoed)
Byte 1:    Function Code    (0x03)
Byte 2:    Byte Count       (= register_count × 2)
Byte 3..N: Register Data    (big-endian, 2 bytes per register)
Last 2:    CRC-16           (little-endian)
```

Total: 5 + (register_count × 2) bytes.

### Error Response

```
Byte 0:    Slave Address
Byte 1:    Function Code + 0x80  (e.g., 0x83 for error on function 0x03)
Byte 2:    Exception Code
Last 2:    CRC-16
```

Exception codes:
- 0x01: Illegal function
- 0x02: Illegal data address (register doesn't exist)
- 0x03: Illegal data value
- 0x04: Slave device failure

---

## CRC-16/Modbus

Polynomial: 0xA001 (reflected representation of 0x8005)
Initial value: 0xFFFF

### Lookup Table Method (recommended — fast)

```cpp
// Compute once at startup, store in RAM (256 × 2 bytes = 512 bytes)
static uint16_t crcTable[256];

void initModbusCRC() {
    for (uint16_t i = 0; i < 256; i++) {
        uint16_t crc = i;
        for (uint8_t j = 0; j < 8; j++) {
            if (crc & 1)
                crc = (crc >> 1) ^ 0xA001;
            else
                crc >>= 1;
        }
        crcTable[i] = crc;
    }
}

uint16_t modbusCRC(const uint8_t *data, uint16_t length) {
    uint16_t crc = 0xFFFF;
    for (uint16_t i = 0; i < length; i++) {
        crc = (crc >> 8) ^ crcTable[(crc ^ data[i]) & 0xFF];
    }
    return crc;
}
```

### CRC is appended little-endian

```cpp
uint16_t crc = modbusCRC(frame, frameLen);
frame[frameLen]     = crc & 0xFF;        // low byte first
frame[frameLen + 1] = (crc >> 8) & 0xFF; // high byte second
```

### Verifying response CRC

Run CRC over the entire response including the CRC bytes. If valid, result = 0x0000.

```cpp
uint16_t check = modbusCRC(response, responseLen); // includes the 2 CRC bytes
if (check != 0x0000) {
    // CRC error — corrupted frame
}
```

---

## Register Data Decoding

Modbus registers are 16-bit (2 bytes), transmitted big-endian (MSB first).

### Common data types in MFM meters

| Type | Registers | Bytes | Decode |
|------|-----------|-------|--------|
| uint16 | 1 | 2 | `(hi << 8) \| lo` |
| int16 | 1 | 2 | `(int16_t)((hi << 8) \| lo)` |
| float32 | 2 | 4 | IEEE 754 big-endian (see below) |
| uint32 | 2 | 4 | `(reg0 << 16) \| reg1` |
| float64 | 4 | 8 | IEEE 754, rare in MFMs |

### Float32 decoding (most common for voltage, current, power)

Registers come in as two 16-bit values. Combine into 4 bytes, interpret as IEEE 754 float.

```cpp
float decodeFloat32(uint16_t reg0, uint16_t reg1) {
    // reg0 = high word, reg1 = low word (big-endian register order)
    uint32_t raw = ((uint32_t)reg0 << 16) | (uint32_t)reg1;
    float result;
    memcpy(&result, &raw, sizeof(float));
    return result;
}
```

**WARNING: Byte order varies by manufacturer!**
- Most meters (Schneider, ABB, Elmeasure): big-endian (AB CD) — reg0 is high word
- Some meters (Siemens, older models): little-endian (CD AB) — reg0 is low word
- Some use byte-swapped (BA DC) or (DC BA)

If you read a voltage register and get garbage (like 1.4e-38 or NaN), try swapping the register order:

```cpp
// Try this if the default order gives wrong values
float decodeFloat32_swapped(uint16_t reg0, uint16_t reg1) {
    uint32_t raw = ((uint32_t)reg1 << 16) | (uint32_t)reg0;  // swapped
    float result;
    memcpy(&result, &raw, sizeof(float));
    return result;
}
```

---

## Timing

### Serial framing (8N1)

Each byte on the wire: 1 start bit + 8 data bits + 1 stop bit = **10 bits per byte**

| Baud Rate | Bit time | Byte time | 3.5 char silence | Max devices at 1Hz (single bus, 20 regs each) |
|-----------|----------|-----------|-------------------|------------------------------------------------|
| 9600 | 104 µs | 1.04 ms | 3.65 ms | ~15-20 |
| 19200 | 52 µs | 0.52 ms | 1.82 ms | ~30-40 |
| 38400 | 26 µs | 0.26 ms | 0.91 ms | ~50-60 |
| 115200 | 8.7 µs | 0.087 ms | 0.30 ms | ~100+ |

### Per-device poll time estimate

```
Time per device = TX time + turnaround + meter processing + RX time + inter-frame gap

At 9600 baud, reading 20 registers:
  TX request:     8 bytes × 1.04ms = 8.3ms
  Turnaround:     DE/RE switch = 0.2ms
  Meter thinking: 5-20ms (varies by meter model)
  RX response:    45 bytes × 1.04ms = 46.9ms  (20 regs × 2 + 5 overhead)
  Inter-frame:    3.65ms
  ─────────────────────────────────────────────
  Total: ~65-80ms per device

At 115200 baud:
  TX: 0.7ms, turnaround: 0.2ms, meter: 5-20ms, RX: 3.9ms, gap: 0.3ms
  Total: ~10-25ms per device
```

### Timeout

If a meter doesn't respond within the timeout, skip it and move to the next.

Recommended timeout values:
- 9600 baud: 500ms (generous) or 200ms (tight)
- 115200 baud: 200ms (generous) or 100ms (tight)

In firmware:
```cpp
#define MODBUS_RESPONSE_TIMEOUT_MS 500
```

---

## DE/RE Pin Timing (critical for MAX3485)

The DE/RE pin controls whether the MAX3485 is transmitting or receiving. Getting the timing wrong is the #1 cause of Modbus communication failures.

### Transmit sequence

```cpp
void sendModbusRequest(const uint8_t *frame, uint16_t len) {
    // 1. Switch to transmit mode
    digitalWrite(RS485_DE_PIN, HIGH);

    // 2. Small delay to let the transceiver settle (optional, 10-50µs is enough)
    delayMicroseconds(50);

    // 3. Send the frame
    Serial2.write(frame, len);

    // 4. Wait for UART TX buffer to drain
    Serial2.flush();  // blocks until all bytes shifted out of TX buffer

    // 5. Wait for the last byte to physically leave the UART shift register
    // At 9600 baud: 1 byte = 1.04ms. Add margin.
    delayMicroseconds(200);  // conservative. At 115200, 100µs is enough.

    // 6. Switch to receive mode
    digitalWrite(RS485_DE_PIN, LOW);
}
```

### Why step 5 matters

`Serial.flush()` returns when the TX buffer (software) is empty, but the last byte may still be in the UART's hardware shift register being clocked out bit by bit. If you switch to receive mode too early, the last few bits of your request get corrupted on the bus, and the meter sees a bad CRC and ignores you.

The 200µs delay is conservative — at 9600 baud one byte takes 1040µs, so the last byte is always done by then. At 115200 baud, one byte is 87µs, so 100µs is safe.

### Receive sequence

```cpp
bool receiveModbusResponse(uint8_t *buffer, uint16_t *len, uint16_t timeout_ms) {
    // DE/RE is already LOW from sendModbusRequest()

    unsigned long start = millis();
    uint16_t idx = 0;

    // Wait for first byte
    while (!Serial2.available()) {
        if (millis() - start > timeout_ms) return false; // timeout, no response
    }

    // Read bytes until inter-frame silence (3.5 char times with no data)
    unsigned long lastByte = micros();
    while (true) {
        if (Serial2.available()) {
            buffer[idx++] = Serial2.read();
            lastByte = micros();
            if (idx >= 256) break; // buffer overflow protection
        } else {
            // Check for inter-frame silence (end of frame)
            // 3.5 chars at 9600 baud = 3646µs. Use 4000µs for margin.
            unsigned long silence = micros() - lastByte;
            if (silence > 4000 && idx > 0) break; // frame complete

            if (millis() - start > timeout_ms) break; // overall timeout
        }
    }

    *len = idx;
    return (idx >= 5); // minimum valid response: addr + func + bytecount + 2 CRC
}
```

---

## Register Bucketing (optimization for future)

The Modbus spec allows reading up to 125 registers in a single request. If a meter has registers at addresses 0-9 and 300-309, you can't read them in one call (gap > 125). Instead, group them into "buckets":

```
Bucket 0: addresses 0-124   → read registers 0-9 in one call
Bucket 1: addresses 250-374 → read registers 300-309 in one call
```

For Phase 3, just read one contiguous block per meter. Add bucketing later if meters have non-contiguous register maps.

---

## Common MFM Register Maps

These are typical — always verify against your specific meter's manual.

### Schneider PM2100 / PM5000 series (common example)
| Register | Type | Description |
|----------|------|-------------|
| 0-1 | float32 | Voltage L1-N (V) |
| 2-3 | float32 | Voltage L2-N (V) |
| 4-5 | float32 | Voltage L3-N (V) |
| 6-7 | float32 | Current L1 (A) |
| 8-9 | float32 | Current L2 (A) |
| 10-11 | float32 | Current L3 (A) |
| 12-13 | float32 | Active Power Total (kW) |
| 14-15 | float32 | Reactive Power Total (kVAR) |
| 16-17 | float32 | Power Factor |
| 18-19 | float32 | Frequency (Hz) |

### Generic test configuration (for simulator)
Use this for testing with diagslave/ModRSsim2:
- 20 holding registers starting at address 0
- Set registers 0-1 to represent float32 230.0 (voltage)
- Set other registers to known values for verification

---

## Error Handling in Firmware

```
On each poll attempt:
  1. Send request
  2. Wait for response (with timeout)
  3. If timeout → increment error count, skip this meter, move to next
  4. If CRC error → increment error count, optionally retry once, then skip
  5. If exception response (func | 0x80) → log exception code, skip
  6. If valid response → decode registers, store in meters[], increment success count
  7. Move to next meter

Never block the entire loop waiting for one meter.
Max retries per meter per cycle: 1 (optional, 0 is fine for 1Hz polling)
```

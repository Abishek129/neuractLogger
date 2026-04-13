# Wiring Guide — ESP32 + MAX3485 + W5500

## Component List

| # | Component | Qty | Notes |
|---|-----------|-----|-------|
| 1 | ESP32-WROOM-32 DevKit V1 | 1 | 38-pin or 30-pin variant |
| 2 | MAX3485 or SP3485 module | 1 | 3.3V TTL RS-485 transceiver |
| 3 | W5500 SPI Ethernet module | 1 | With RJ45 jack, 3.3V or 5V variant |
| 4 | 120Ω resistor | 2 | Bus termination (one at gateway end, one at last meter) |
| 5 | Breadboard + jumper wires | — | For prototyping |
| 6 | USB-to-RS485 adapter | 1 | For testing (connects to your PC) |
| 7 | Ethernet cable (Cat5e/6) | 1 | Gateway to network switch |
| 8 | USB cable (micro-USB) | 1 | ESP32 programming + power |

---

## Wiring Diagram (text)

### ESP32 → MAX3485

```
ESP32 DevKit          MAX3485 Module
────────────          ──────────────
GPIO17 (TX2) ──────► DI   (Driver Input — data TO the bus)
GPIO16 (RX2) ◄────── RO   (Receiver Out — data FROM the bus)
GPIO4        ──┬───► DE   (Driver Enable — HIGH = transmit)
               └───► RE̅   (Receiver Enable, active LOW — tie to DE)
3.3V         ──────► VCC
GND          ──────► GND

MAX3485 Bus Side:
  A ──── twisted pair ──── to meter A terminals
  B ──── twisted pair ──── to meter B terminals
```

**Why DE and RE̅ are tied together:**
- DE HIGH + RE̅ HIGH = transmit mode (driver on, receiver off)
- DE LOW + RE̅ LOW = receive mode (driver off, receiver on)
- One GPIO controls both states. This is standard for half-duplex RS-485.

### ESP32 → W5500

```
ESP32 DevKit          W5500 Module
────────────          ────────────
GPIO18 (SCK)  ──────► SCLK
GPIO23 (MOSI) ──────► MOSI
GPIO19 (MISO) ◄────── MISO
GPIO5         ──────► SCS  (Chip Select, sometimes labeled CS or SS)
3.3V          ──────► 3.3V (if 3.3V module) or VCC
GND           ──────► GND
                      (Some modules also have a RST pin — connect to 3.3V or leave floating)
                      (Some modules have an INT pin — not needed, leave unconnected)
```

**SPI Note:** GPIO18/23/19 are ESP32's default VSPI pins. This is the standard SPI bus. If you later add more SPI devices (like W25Q128 flash), they share the same SCK/MOSI/MISO lines but each gets its own CS pin.

### RS-485 Bus Wiring (to meters)

```
                  120Ω                                    120Ω
Gateway ─────┤├──── Meter 1 ──── Meter 2 ──── ... ──── Meter N ─────┤├────
  A─────────A────────A────────────A──────────────────────A
  B─────────B────────B────────────B──────────────────────B

  ◄─── twisted pair cable, daisy-chain topology ───►
```

**Termination resistors (120Ω):**
- Place one at the gateway end (across A and B on the MAX3485 module)
- Place one at the last meter on the bus (across A and B)
- Do NOT place them at intermediate meters
- Without termination: signal reflections cause CRC errors, especially at higher baud rates (>19200)

**Cable requirements:**
- Twisted pair (Cat5e works fine for short runs)
- For long runs (>100m): use proper RS-485 cable (shielded twisted pair, 120Ω characteristic impedance)
- Maximum bus length: 1200m at 9600 baud, shorter at higher baud rates
- Maximum devices per bus: 32 (standard loads) or 128 (with 1/4 unit load transceivers like MAX3485)

---

## Power Notes

**During development (breadboard):**
- ESP32 powered via USB from laptop
- MAX3485 powered from ESP32's 3.3V pin (draws <1mA)
- W5500 powered from ESP32's 3.3V pin (draws ~130mA typical)
- Total current from USB: ~350-400mA (ESP32 ~200mA WiFi off + W5500 ~130mA + overhead)
- This is within USB 2.0 spec (500mA max) — should work fine

**In production:**
- Use a 5V/2A power supply
- Feed 5V to ESP32's VIN pin (onboard regulator provides 3.3V)
- Or use a 3.3V/1A regulator (AMS1117-3.3) to power everything from 5V/12V input
- MAX3485 and W5500 both run on 3.3V

**Common ground is critical:**
- ESP32 GND, MAX3485 GND, W5500 GND, and RS-485 bus GND must all be connected
- For long RS-485 runs between panels, a separate ground wire alongside the twisted pair helps with noise immunity

---

## Physical Layout Tips

- Keep SPI wires (ESP32 to W5500) short — under 15cm on breadboard. SPI is fast (MHz range) and long wires cause signal integrity issues.
- UART wires (ESP32 to MAX3485) can be a bit longer — UART at 9600-115200 baud is slow enough that 20-30cm is fine.
- Keep the MAX3485 module close to where the RS-485 cable enters the enclosure — minimize the length of 3.3V TTL signals (which are noise-sensitive) and maximize the length of RS-485 differential signals (which are noise-resistant).

---

## Testing the Wiring (before firmware)

### Test MAX3485 with multimeter:
1. Power on ESP32 (USB)
2. Measure MAX3485 VCC to GND: should be ~3.3V
3. Measure GPIO4 with no code running: floating (could be anything)
4. Upload a simple sketch that sets GPIO4 HIGH → measure DE pin: should be ~3.3V
5. Set GPIO4 LOW → measure DE pin: should be ~0V

### Test W5500 with multimeter:
1. Measure W5500 VCC to GND: should be ~3.3V
2. Upload Ethernet example sketch — if W5500 doesn't initialize, check:
   - CS pin wired to GPIO5 (not another pin)
   - SPI pins correct (SCK=18, MOSI=23, MISO=19)
   - W5500 module's onboard voltage regulator (some modules accept 5V and regulate to 3.3V internally — check your specific module)

### Test RS-485 bus with USB-to-RS485 adapter:
1. Connect USB-to-RS485 adapter to your PC
2. Connect adapter's A to MAX3485 A, adapter's B to MAX3485 B
3. Open terminal on PC (e.g., PuTTY, 9600 8N1)
4. Upload test sketch that sends "HELLO" every second via UART2 with GPIO4=HIGH
5. You should see "HELLO" on the PC terminal
6. Type on PC terminal — ESP32 should receive bytes (GPIO4 must be LOW / receive mode)

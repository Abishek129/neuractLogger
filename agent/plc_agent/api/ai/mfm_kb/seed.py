# mypy: ignore-errors
"""
Seed the MFM Knowledge Base with register maps for the 5 most common
Indian industrial MFMs.

Sources:
    1. Schneider PM5110 — PM5100-PM5300_PublicRegisterList, Schneider FAQ FA234017
    2. Schneider PM5300 — same base + THD/displacement PF registers
    3. ABB B23/B24     — ABB Manual 2CMC485003M0201, Section 9.3 pp.86-94
    4. L&T Vega        — L&T Manual Doc 4D060193 Rev L, Appendix 3
    5. Selec MFM376    — Selec OP506-V03, OP2046-V03

Run:
    cd agent && python -m plc_agent.api.ai.mfm_kb.seed
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure parent packages are importable when run as __main__
_root = str(Path(__file__).resolve().parents[4])
if _root not in sys.path:
    sys.path.insert(0, _root)

from plc_agent.api.ai.mfm_kb.models import KBEntry, RegisterEntry, IdentificationBlock
from plc_agent.api.ai.mfm_kb.manager import KBManager


# ===================================================================
# Helper to build a RegisterEntry compactly
# ===================================================================

def R(addr, count, param, dtype, unit="", scale=1.0, rng=None, page=None):
    return RegisterEntry(
        address=addr, count=count, parameter=param,
        data_type=dtype, unit=unit, scale=scale,
        typical_range=rng or [], source_page=page,
    )


# ===================================================================
# 1. Schneider Electric PM5110
# ===================================================================

_PM5110_REGS = [
    # Currents
    R(3000, 2, "current_l1",          "float32", "A", rng=[0, 6000]),
    R(3002, 2, "current_l2",          "float32", "A", rng=[0, 6000]),
    R(3004, 2, "current_l3",          "float32", "A", rng=[0, 6000]),
    R(3006, 2, "current_neutral",     "float32", "A", rng=[0, 6000]),
    R(3010, 2, "current_avg",         "float32", "A"),
    # Voltage L-L
    R(3020, 2, "voltage_l12",         "float32", "V", rng=[0, 690]),
    R(3022, 2, "voltage_l23",         "float32", "V", rng=[0, 690]),
    R(3024, 2, "voltage_l31",         "float32", "V", rng=[0, 690]),
    R(3026, 2, "voltage_ll_avg",      "float32", "V", rng=[380, 440]),
    # Voltage L-N
    R(3028, 2, "voltage_l1n",         "float32", "V", rng=[180, 280]),
    R(3030, 2, "voltage_l2n",         "float32", "V", rng=[180, 280]),
    R(3032, 2, "voltage_l3n",         "float32", "V", rng=[180, 280]),
    R(3036, 2, "voltage_ln_avg",      "float32", "V", rng=[220, 254]),
    # Active power
    R(3054, 2, "active_power_l1",     "float32", "kW"),
    R(3056, 2, "active_power_l2",     "float32", "kW"),
    R(3058, 2, "active_power_l3",     "float32", "kW"),
    R(3060, 2, "active_power_total",  "float32", "kW"),
    # Reactive power
    R(3062, 2, "reactive_power_l1",   "float32", "kVAR"),
    R(3064, 2, "reactive_power_l2",   "float32", "kVAR"),
    R(3066, 2, "reactive_power_l3",   "float32", "kVAR"),
    R(3068, 2, "reactive_power_total","float32", "kVAR"),
    # Apparent power
    R(3070, 2, "apparent_power_l1",   "float32", "kVA"),
    R(3072, 2, "apparent_power_l2",   "float32", "kVA"),
    R(3074, 2, "apparent_power_l3",   "float32", "kVA"),
    R(3076, 2, "apparent_power_total","float32", "kVA"),
    # Power factor
    R(3078, 2, "power_factor_l1",     "float32", "",  rng=[-1, 1]),
    R(3080, 2, "power_factor_l2",     "float32", "",  rng=[-1, 1]),
    R(3082, 2, "power_factor_l3",     "float32", "",  rng=[-1, 1]),
    R(3084, 2, "power_factor_total",  "float32", "",  rng=[-1, 1]),
    # Frequency
    R(3110, 2, "frequency",           "float32", "Hz", rng=[49, 51]),
    # Energy
    R(3204, 2, "energy_active_import","float32", "kWh"),
    R(3206, 2, "energy_active_export","float32", "kWh"),
    R(3220, 2, "energy_reactive_import","float32","kVARh"),
    R(3236, 2, "energy_apparent_import","float32","kVAh"),
]

PM5110 = KBEntry(
    manufacturer="Schneider Electric",
    model="PM5110",
    protocol="modbus_rtu",
    byte_order="big_endian",
    identification=IdentificationBlock(register_address=29, expected_value="PM5110", description="Meter model register (ASCII)"),
    registers=_PM5110_REGS,
    quirks=[
        "PF sign indicates leading/lagging (positive=lagging/inductive), NOT import/export.",
        "Energy registers roll over. Int64 energy counters available at different addresses for higher precision.",
        "Addresses are 0-based. Do NOT add 40001 offset — use raw address with FC 0x03.",
        "PM5100/PM5110/PM5111 share the same register map.",
        "Default: 9600 baud, 8N1, slave address 1.",
    ],
    source_document="schneider_pm5100_register_list.pdf",
    extraction_date="2026-04-13",
    verified_by_engineer=True,
    version=1,
)


# ===================================================================
# 2. Schneider Electric PM5300
# ===================================================================

_PM5300_EXTRA = [
    # Displacement PF (PM5300 only)
    R(3042, 2, "displacement_pf_l1",    "float32", "", rng=[-1, 1]),
    R(3044, 2, "displacement_pf_l2",    "float32", "", rng=[-1, 1]),
    R(3046, 2, "displacement_pf_l3",    "float32", "", rng=[-1, 1]),
    R(3048, 2, "displacement_pf_total", "float32", "", rng=[-1, 1]),
    # Unbalance
    R(3108, 2, "voltage_unbalance_ln",  "float32", "%"),
    R(3112, 2, "voltage_unbalance_ll",  "float32", "%"),
    R(3114, 2, "current_unbalance",     "float32", "%"),
    # THD
    R(21300, 2, "thd_voltage_l1n",      "float32", "%"),
    R(21302, 2, "thd_voltage_l2n",      "float32", "%"),
    R(21304, 2, "thd_voltage_l3n",      "float32", "%"),
    R(21312, 2, "thd_current_l1",       "float32", "%"),
    R(21314, 2, "thd_current_l2",       "float32", "%"),
    R(21316, 2, "thd_current_l3",       "float32", "%"),
]

PM5300 = KBEntry(
    manufacturer="Schneider Electric",
    model="PM5300",
    protocol="modbus_rtu",
    byte_order="big_endian",
    identification=IdentificationBlock(register_address=29, expected_value="PM5300", description="Meter model register (ASCII)"),
    registers=_PM5110_REGS + _PM5300_EXTRA,
    quirks=[
        "Shares the same base register map as PM5110 for all basic parameters.",
        "PM5310 variant has Ethernet — when using Modbus TCP, unit ID = slave address.",
        "THD registers are in address range 21000+ — cannot be read in same contiguous block as basic parameters.",
        "Supports both True PF (3078-3084) and Displacement PF (3042-3048).",
        "Default: 9600 baud, 8N1, slave address 1.",
    ],
    source_document="schneider_pm5300_register_list.pdf",
    extraction_date="2026-04-13",
    verified_by_engineer=True,
    version=1,
)


# ===================================================================
# 3. ABB B23/B24
# ===================================================================

_ABB_B23_REGS = [
    # Voltage L-N (resolution 0.1V — scale=0.1)
    R(23296, 2, "voltage_l1n",          "uint32", "V", scale=0.1, rng=[180, 280]),
    R(23298, 2, "voltage_l2n",          "uint32", "V", scale=0.1, rng=[180, 280]),
    R(23300, 2, "voltage_l3n",          "uint32", "V", scale=0.1, rng=[180, 280]),
    # Voltage L-L
    R(23302, 2, "voltage_l12",          "uint32", "V", scale=0.1, rng=[380, 440]),
    R(23304, 2, "voltage_l23",          "uint32", "V", scale=0.1, rng=[380, 440]),
    R(23306, 2, "voltage_l31",          "uint32", "V", scale=0.1, rng=[380, 440]),
    # Current (resolution 0.01A)
    R(23308, 2, "current_l1",           "uint32", "A", scale=0.01, rng=[0, 6000]),
    R(23310, 2, "current_l2",           "uint32", "A", scale=0.01, rng=[0, 6000]),
    R(23312, 2, "current_l3",           "uint32", "A", scale=0.01, rng=[0, 6000]),
    R(23314, 2, "current_neutral",      "uint32", "A", scale=0.01),
    # Active power (resolution 0.01W — note: Watts not kW!)
    R(23316, 2, "active_power_total",   "int32",  "W", scale=0.01),
    R(23318, 2, "active_power_l1",      "int32",  "W", scale=0.01),
    R(23320, 2, "active_power_l2",      "int32",  "W", scale=0.01),
    R(23322, 2, "active_power_l3",      "int32",  "W", scale=0.01),
    # Reactive power
    R(23324, 2, "reactive_power_total", "int32",  "var", scale=0.01),
    R(23326, 2, "reactive_power_l1",    "int32",  "var", scale=0.01),
    R(23328, 2, "reactive_power_l2",    "int32",  "var", scale=0.01),
    R(23330, 2, "reactive_power_l3",    "int32",  "var", scale=0.01),
    # Apparent power
    R(23332, 2, "apparent_power_total", "int32",  "VA", scale=0.01),
    R(23334, 2, "apparent_power_l1",    "int32",  "VA", scale=0.01),
    R(23336, 2, "apparent_power_l2",    "int32",  "VA", scale=0.01),
    R(23338, 2, "apparent_power_l3",    "int32",  "VA", scale=0.01),
    # Frequency (1 register, resolution 0.01Hz)
    R(23340, 1, "frequency",            "uint16", "Hz", scale=0.01, rng=[49, 51]),
    # Power factor (1 register each, resolution 0.001)
    R(23354, 1, "power_factor_total",   "int16",  "",   scale=0.001, rng=[-1, 1]),
    R(23355, 1, "power_factor_l1",      "int16",  "",   scale=0.001, rng=[-1, 1]),
    R(23356, 1, "power_factor_l2",      "int16",  "",   scale=0.001, rng=[-1, 1]),
    R(23357, 1, "power_factor_l3",      "int16",  "",   scale=0.001, rng=[-1, 1]),
    # Energy (64-bit, 4 registers, resolution 0.01kWh)
    R(20480, 4, "energy_active_import", "uint32", "kWh", scale=0.01),
    R(20484, 4, "energy_active_export", "uint32", "kWh", scale=0.01),
    R(20492, 4, "energy_reactive_import","uint32","kVARh", scale=0.01),
    R(20504, 4, "energy_apparent_import","uint32","kVAh", scale=0.01),
]

ABB_B23 = KBEntry(
    manufacturer="ABB",
    model="B23",
    protocol="modbus_rtu",
    byte_order="big_endian",
    identification=IdentificationBlock(register_address=35168, expected_value="B23", description="Type designation (6 regs ASCII)"),
    registers=_ABB_B23_REGS,
    quirks=[
        "Default baud is 4800, NOT 9600. Default parity is Even.",
        "Uses SCALED INTEGERS, not float32. Apply scale factor to raw register values.",
        "Power is in Watts (W), not kilowatts (kW). Energy is in kWh with 0.01 resolution.",
        "Frequency and PF are single 16-bit registers (count=1), not 32-bit.",
        "Energy accumulators are 64-bit (4 registers). Must read all 4 and combine.",
        "'Steel' variants (B23 112-100) do NOT support reverse/export energy. 'Silver' variants (B23 312-100) do.",
        "B24 model uses external CT (up to 1000A) but has the same register map.",
        "Do NOT add 40001 offset — use raw hex addresses with FC 0x03.",
    ],
    source_document="abb_b23_b24_user_manual_2CMC485003M0201.pdf",
    extraction_date="2026-04-13",
    verified_by_engineer=True,
    version=1,
)


# ===================================================================
# 4. L&T Vega (WM series)
# ===================================================================

# L&T uses 30001-convention for FC 0x04 input registers.
# 30001 = input register address 0, 30003 = address 2, etc.
# We store the RAW address (30001-30000=1 → address 0, etc.)

_LT_VEGA_REGS = [
    # Voltage L-N (resolution 0.01V)
    R(0, 2, "voltage_l1n",           "int32", "V", scale=0.01, rng=[180, 280]),
    R(2, 2, "voltage_l2n",           "int32", "V", scale=0.01, rng=[180, 280]),
    R(4, 2, "voltage_l3n",           "int32", "V", scale=0.01, rng=[180, 280]),
    # Current (resolution 0.001A)
    R(6, 2, "current_l1",            "int32", "A", scale=0.001, rng=[0, 6000]),
    R(8, 2, "current_l2",            "int32", "A", scale=0.001, rng=[0, 6000]),
    R(10, 2, "current_l3",           "int32", "A", scale=0.001, rng=[0, 6000]),
    # Active power per phase (resolution 0.0001kW) + unit registers
    R(12, 2, "active_power_l1",      "int32", "kW", scale=0.0001),
    R(15, 2, "active_power_l2",      "int32", "kW", scale=0.0001),
    R(18, 2, "active_power_l3",      "int32", "kW", scale=0.0001),
    # Reactive power per phase
    R(21, 2, "reactive_power_l1",    "int32", "kVAR", scale=0.0001),
    R(24, 2, "reactive_power_l2",    "int32", "kVAR", scale=0.0001),
    R(27, 2, "reactive_power_l3",    "int32", "kVAR", scale=0.0001),
    # Apparent power per phase
    R(30, 2, "apparent_power_l1",    "int32", "kVA", scale=0.0001),
    R(33, 2, "apparent_power_l2",    "int32", "kVA", scale=0.0001),
    R(36, 2, "apparent_power_l3",    "int32", "kVA", scale=0.0001),
    # Power factor per phase (resolution 0.001)
    R(39, 2, "power_factor_l1",      "int32", "",   scale=0.001, rng=[-1, 1]),
    R(41, 2, "power_factor_l2",      "int32", "",   scale=0.001, rng=[-1, 1]),
    R(43, 2, "power_factor_l3",      "int32", "",   scale=0.001, rng=[-1, 1]),
    # Totals
    R(45, 2, "active_power_total",   "int32", "kW", scale=0.0001),
    R(48, 2, "reactive_power_total", "int32", "kVAR", scale=0.0001),
    R(51, 2, "apparent_power_total", "int32", "kVA", scale=0.0001),
    R(54, 2, "power_factor_total",   "int32", "",   scale=0.001, rng=[-1, 1]),
    # Frequency
    R(56, 2, "frequency",            "int32", "Hz", scale=0.01, rng=[49, 51]),
    # Voltage L-L
    R(58, 2, "voltage_l12",          "int32", "V", scale=0.01, rng=[380, 440]),
    R(60, 2, "voltage_l23",          "int32", "V", scale=0.01, rng=[380, 440]),
    R(62, 2, "voltage_l31",          "int32", "V", scale=0.01, rng=[380, 440]),
    # Averages
    R(64, 2, "voltage_ln_avg",       "int32", "V", scale=0.01, rng=[220, 254]),
    R(66, 2, "current_avg",          "int32", "A", scale=0.001),
    # THD
    R(68, 2, "thd_voltage_l1n",      "int32", "%", scale=0.01),
    R(70, 2, "thd_voltage_l2n",      "int32", "%", scale=0.01),
    R(72, 2, "thd_voltage_l3n",      "int32", "%", scale=0.01),
    # Energy (3-word format: value + unit byte)
    R(111, 3, "energy_active_import","int32", "kWh", scale=0.01),
    R(108, 3, "energy_apparent_import","int32","kVAh", scale=0.01),
]

LT_VEGA = KBEntry(
    manufacturer="Larsen & Toubro",
    model="Vega",
    protocol="modbus_rtu",
    byte_order="big_endian",
    identification=None,  # No model ID register — identify by register response pattern
    registers=_LT_VEGA_REGS,
    quirks=[
        "Uses Function Code 0x04 (Input Registers), NOT 0x03 (Holding Registers) for measurement data.",
        "Address numbering in manual uses 30001-convention: 30001 = input register 0. Subtract 30001 for raw Modbus address.",
        "Each power parameter has a companion 'unit' register (scale indicator: 0=base, 1=kilo, 2=mega). Check unit register for correct interpretation.",
        "Values are 2's complement for negative numbers.",
        "Uses scaled integers, NOT float32. Apply scale factor to raw register values.",
        "L&T uses R/Y/B phase naming: R=Red=L1, Y=Yellow=L2, B=Blue=L3.",
        "No model ID register — identification by register pattern match only.",
        "May be labeled 'WM330' at some sites — same meter, different distributor designation.",
        "Only Models B and C have RS-485 Modbus. Model A has no communications.",
        "Response timeout: recommended 400ms minimum.",
        "Default: 9600 baud, Even parity, slave address 1.",
    ],
    source_document="lt_vega_manual_4D060193.pdf",
    extraction_date="2026-04-13",
    verified_by_engineer=True,
    version=1,
)


# ===================================================================
# 5. Selec MFM376
# ===================================================================

# Selec uses 30000-convention for FC 0x04 input registers.
# 30000 = input register address 0, 30002 = address 2, etc.

_SELEC_MFM376_REGS = [
    # Voltage L-N
    R(0,  2, "voltage_l1n",           "float32", "V", rng=[180, 280]),
    R(2,  2, "voltage_l2n",           "float32", "V", rng=[180, 280]),
    R(4,  2, "voltage_l3n",           "float32", "V", rng=[180, 280]),
    R(6,  2, "voltage_ln_avg",        "float32", "V", rng=[220, 254]),
    # Voltage L-L
    R(8,  2, "voltage_l12",           "float32", "V", rng=[380, 440]),
    R(10, 2, "voltage_l23",           "float32", "V", rng=[380, 440]),
    R(12, 2, "voltage_l31",           "float32", "V", rng=[380, 440]),
    R(14, 2, "voltage_ll_avg",        "float32", "V", rng=[380, 440]),
    # Current
    R(16, 2, "current_l1",            "float32", "A", rng=[0, 6000]),
    R(18, 2, "current_l2",            "float32", "A", rng=[0, 6000]),
    R(20, 2, "current_l3",            "float32", "A", rng=[0, 6000]),
    R(22, 2, "current_avg",           "float32", "A"),
    # Active power
    R(24, 2, "active_power_l1",       "float32", "kW"),
    R(26, 2, "active_power_l2",       "float32", "kW"),
    R(28, 2, "active_power_l3",       "float32", "kW"),
    # Reactive power
    R(30, 2, "reactive_power_l1",     "float32", "kVAR"),
    R(32, 2, "reactive_power_l2",     "float32", "kVAR"),
    R(34, 2, "reactive_power_l3",     "float32", "kVAR"),
    # Apparent power
    R(36, 2, "apparent_power_l1",     "float32", "kVA"),
    R(38, 2, "apparent_power_l2",     "float32", "kVA"),
    R(40, 2, "apparent_power_l3",     "float32", "kVA"),
    # Power factor
    R(42, 2, "power_factor_l1",       "float32", "",  rng=[-1, 1]),
    R(44, 2, "power_factor_l2",       "float32", "",  rng=[-1, 1]),
    R(46, 2, "power_factor_l3",       "float32", "",  rng=[-1, 1]),
    R(48, 2, "power_factor_avg",      "float32", "",  rng=[-1, 1]),
    # Frequency
    R(50, 2, "frequency",             "float32", "Hz", rng=[49, 51]),
    # Totals
    R(52, 2, "active_power_total",    "float32", "kW"),
    R(54, 2, "reactive_power_total",  "float32", "kVAR"),
    R(56, 2, "apparent_power_total",  "float32", "kVA"),
    # Energy
    R(86, 2, "energy_active_import",  "float32", "kWh"),
    R(88, 2, "energy_active_export",  "float32", "kWh"),
    R(90, 2, "energy_active_total",   "float32", "kWh"),
    R(92, 2, "energy_reactive_import","float32", "kVARh"),
    R(94, 2, "energy_reactive_export","float32", "kVARh"),
    R(98, 2, "energy_apparent_total", "float32", "kVAh"),
    # THD
    R(124, 2, "thd_voltage_l1n",      "float32", "%"),
    R(126, 2, "thd_voltage_l2n",      "float32", "%"),
    R(128, 2, "thd_voltage_l3n",      "float32", "%"),
    R(136, 2, "thd_current_l1",       "float32", "%"),
    R(138, 2, "thd_current_l2",       "float32", "%"),
    R(140, 2, "thd_current_l3",       "float32", "%"),
]

SELEC_MFM376 = KBEntry(
    manufacturer="Selec",
    model="MFM376",
    protocol="modbus_rtu",
    byte_order="big_endian",
    identification=IdentificationBlock(register_address=684, expected_value="MFM376", description="Serial number register (input reg 30684)"),
    registers=_SELEC_MFM376_REGS,
    quirks=[
        "Uses Function Code 0x04 (Input Registers), NOT 0x03.",
        "Address uses 30000-convention: 30000 = input register 0. Subtract 30000 for raw Modbus address.",
        "Float32 data, big-endian (ABCD) by default.",
        "MFM376-C-CE model has configurable endianness via holding register 40070 (0=CDAB, 1=ABCD default).",
        "Only -C and -C-CE variants have RS-485 Modbus. Plain MFM376 and -CE have no comms.",
        "Clean contiguous register layout — voltage/current/power/PF/freq can be read in one block.",
        "Default: 9600 baud, 8N1, slave address 1.",
    ],
    source_document="selec_mfm376_op506_v03.pdf",
    extraction_date="2026-04-13",
    verified_by_engineer=True,
    version=1,
)


# ===================================================================
# Seed runner
# ===================================================================

ALL_ENTRIES = [PM5110, PM5300, ABB_B23, LT_VEGA, SELEC_MFM376]


def seed():
    """Write all 5 KB entries via KBManager."""
    mgr = KBManager.instance()

    for entry in ALL_ENTRIES:
        filename = mgr.save_entry(entry)
        print(f"  {entry.manufacturer} {entry.model}: "
              f"{len(entry.registers)} registers → {filename}")

    # Verify
    models = mgr.list_models()
    print(f"\nIndex: {len(models)} models")
    for m in models:
        print(f"  {m.model} (v{m.version}, verified={m.verified})")


if __name__ == "__main__":
    print("Seeding MFM Knowledge Base...")
    seed()
    print("\nDone.")

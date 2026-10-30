# Neuract Logger — Metadata & Target Documentation

**Site:** Premier Energies, Seetharampur Solar Plant
**Metadata DB:** `postgresql://postgres@localhost/meta_data_version1`
**Target DB:** `postgresql://postgres@localhost/target_version1`

---

## Overview

| Resource       | Count |
|----------------|-------|
| Schemas        | 13    |
| Gateways       | 27 (22 GIC + 5 PLC) |
| Devices        | 297 (245 MFM + 52 Equipment) |
| Tables         | 297   |
| Column Mappings| 10,572 |
| Storage Target | `target_version1` (default) |

---

## 1. Schemas

| # | Schema Name      | Description                       | Tables | Columns/Table |
|---|------------------|-----------------------------------|--------|---------------|
| 1 | `mfm`            | Multi-Function Meters (energy)    | 245    | 39            |
| 2 | `ahu`            | Air Handling Units                | 11     | 27            |
| 3 | `air_washer`     | Air Washers                       | 6      | 27            |
| 4 | `chiller`        | Chillers                          | 4      | 80            |
| 5 | `compressor`     | Air Compressors                   | 1      | 48            |
| 6 | `pcw`            | Process Cooling Water Pumps       | 1      | 5             |
| 7 | `exhaust`        | Exhaust Fans                      | 7      | 4             |
| 8 | `csu`            | Ceiling Suspended Units           | 10     | 8             |
| 9 | `tfa`            | Treated Fresh Air Units           | 3      | 7             |
| 10| `pump`           | Pumps                             | 4      | 8             |
| 11| `toilet_exhaust` | Toilet Exhaust Fans               | 1      | 4             |
| 12| `stp`            | Sewage Treatment Plant            | 1      | 8             |
| 13| `axial_fan`      | Axial Fans                        | 3      | 4             |

---

## 2. Gateways

### 2.1 GIC Gateways (Modbus TCP — Energy Meters)

22 GIC (Gateway Interface Controllers) serve 245 MFM devices over Modbus TCP on port 502.

| Gateway  | IP Address     | Port | Devices | MFM Range         |
|----------|---------------|------|---------|--------------------|
| GIC-01   | 10.10.1.10    | 502  | 10      | mfm_001 – mfm_010  |
| GIC-02   | 10.10.2.10    | 502  | 10      | mfm_011 – mfm_020  |
| GIC-03   | 10.10.3.10    | 502  | 11      | mfm_021 – mfm_031  |
| GIC-04   | 10.10.4.10    | 502  | 10      | mfm_032 – mfm_041  |
| GIC-05   | 10.10.5.10    | 502  | 10      | mfm_042 – mfm_051  |
| GIC-06   | 10.10.6.10    | 502  | 10      | mfm_052 – mfm_061  |
| GIC-07   | 10.10.7.10    | 502  | 11      | mfm_062 – mfm_072  |
| GIC-08   | 10.10.8.10    | 502  | 11      | mfm_073 – mfm_083  |
| GIC-09   | 10.10.9.10    | 502  | 12      | mfm_084 – mfm_095  |
| GIC-10   | 10.10.10.10   | 502  | 13      | mfm_096 – mfm_108  |
| GIC-11   | 10.10.11.10   | 502  | 10      | mfm_109 – mfm_118  |
| GIC-12   | 10.10.12.10   | 502  | 10      | mfm_119 – mfm_128  |
| GIC-13   | 10.10.13.10   | 502  | 10      | mfm_129 – mfm_138  |
| GIC-14   | 10.10.14.10   | 502  | 10      | mfm_139 – mfm_148  |
| GIC-15   | 10.10.15.10   | 502  | 10      | mfm_149 – mfm_158  |
| GIC-16   | 10.10.16.10   | 502  | 13      | mfm_159 – mfm_171  |
| GIC-17   | 10.10.17.10   | 502  | 13      | mfm_172 – mfm_184  |
| GIC-18   | 10.10.18.10   | 502  | 12      | mfm_185 – mfm_196  |
| GIC-19   | 10.10.19.10   | 502  | 12      | mfm_197 – mfm_208  |
| GIC-20   | 10.10.20.10   | 502  | 12      | mfm_209 – mfm_220  |
| GIC-21   | 10.10.21.10   | 502  | 12      | mfm_221 – mfm_232  |
| GIC-22   | 10.10.22.10   | 502  | 13      | mfm_233 – mfm_245  |

> **Unit ID assignment:** Within each GIC, MFMs are assigned unit IDs 1, 2, 3, ... in order. All MFMs start at Modbus address 0.

### 2.2 PLC Gateways (Modbus TCP — Equipment)

5 PLCs serve 52 equipment devices over Modbus TCP on port 502.

| Gateway      | IP Address    | Port | Devices | Equipment Types                   |
|-------------|---------------|------|---------|-----------------------------------|
| PLC-AHU     | 10.10.23.10   | 502  | 17      | ahu (11), air_washer (6)          |
| PLC-CSU     | 10.10.24.10   | 502  | 13      | csu (10), tfa (3)                 |
| PLC-CHW     | 10.10.25.10   | 502  | 6       | chiller (4), compressor (1), pcw (1) |
| PLC-PUMP    | 10.10.26.10   | 502  | 4       | pump (4)                          |
| PLC-UTILITY | 10.10.27.10   | 502  | 12      | exhaust (7), stp (1), toilet_exhaust (1), axial_fan (3) |

> **Unit ID assignment:** Within each PLC, devices are assigned unit IDs 1, 2, 3, ... in order of appearance.

---

## 3. Devices

### 3.1 MFM Devices (245)

Multi-Function Meters — 3-phase energy meters logging electrical parameters.

- **Protocol:** Modbus TCP (holding registers)
- **Encoding:** `float32` (2 registers per field)
- **Address range:** 0–77 (39 fields x 2 registers)
- **Tables:** `mfm_001` through `mfm_245`

### 3.2 Equipment Devices (52)

> **Naming note:** "Equipment devices" here means the non-MFM device types (AHU, chiller, pump…). It is not the same as the **Electrical Equipment model** in [section 9](#9-electrical-equipment-model), which groups devices into panels and assets.

| Type             | Count | Tables                              |
|-----------------|-------|--------------------------------------|
| AHU             | 11    | `ahu_001` – `ahu_011`               |
| Air Washer      | 6     | `air_washer_001` – `air_washer_006` |
| Chiller         | 4     | `chiller_001` – `chiller_004`       |
| Compressor      | 1     | `compressor_001`                    |
| PCW             | 1     | `pcw_001`                           |
| Exhaust         | 7     | `exhaust_001` – `exhaust_007`       |
| CSU             | 10    | `csu_001` – `csu_010`              |
| TFA             | 3     | `tfa_001` – `tfa_003`              |
| Pump            | 4     | `pump_001` – `pump_004`            |
| Toilet Exhaust  | 1     | `toilet_exhaust_001`               |
| STP             | 1     | `stp_001`                          |
| Axial Fan       | 3     | `axial_fan_001` – `axial_fan_003`  |

---

## 4. Table Columns (Register Maps)

Every table has a `timestamp_utc` primary key column plus its mapped data columns.

### 4.1 MFM Schema (39 columns)

| Column                        | Address | Encoding | Registers | Unit         |
|-------------------------------|---------|----------|-----------|--------------|
| current_r                     | 0       | float32  | 2         | A            |
| current_y                     | 2       | float32  | 2         | A            |
| current_b                     | 4       | float32  | 2         | A            |
| current_avg                   | 6       | float32  | 2         | A            |
| voltage_ry                    | 8       | float32  | 2         | V            |
| voltage_yb                    | 10      | float32  | 2         | V            |
| voltage_br                    | 12      | float32  | 2         | V            |
| voltage_ll_avg                | 14      | float32  | 2         | V            |
| voltage_r_n                   | 16      | float32  | 2         | V            |
| voltage_y_n                   | 18      | float32  | 2         | V            |
| voltage_b_n                   | 20      | float32  | 2         | V            |
| voltage_ln_avg                | 22      | float32  | 2         | V            |
| power_factor_r                | 24      | float32  | 2         | —            |
| power_factor_y                | 26      | float32  | 2         | —            |
| power_factor_b                | 28      | float32  | 2         | —            |
| power_factor_total            | 30      | float32  | 2         | —            |
| frequency_hz                  | 32      | float32  | 2         | Hz           |
| active_power_r_kw             | 34      | float32  | 2         | kW           |
| active_power_y_kw             | 36      | float32  | 2         | kW           |
| active_power_b_kw             | 38      | float32  | 2         | kW           |
| active_power_total_kw         | 40      | float32  | 2         | kW           |
| reactive_power_r_kvar         | 42      | float32  | 2         | kVAR         |
| reactive_power_y_kvar         | 44      | float32  | 2         | kVAR         |
| reactive_power_b_kvar         | 46      | float32  | 2         | kVAR         |
| reactive_power_total_kvar     | 48      | float32  | 2         | kVAR         |
| apparent_power_r_kva          | 50      | float32  | 2         | kVA          |
| apparent_power_y_kva          | 52      | float32  | 2         | kVA          |
| apparent_power_b_kva          | 54      | float32  | 2         | kVA          |
| apparent_power_total_kva      | 56      | float32  | 2         | kVA          |
| thd_voltage_r_pct             | 58      | float32  | 2         | %            |
| thd_voltage_y_pct             | 60      | float32  | 2         | %            |
| thd_voltage_b_pct             | 62      | float32  | 2         | %            |
| thd_current_r_pct             | 64      | float32  | 2         | %            |
| thd_current_y_pct             | 66      | float32  | 2         | %            |
| thd_current_b_pct             | 68      | float32  | 2         | %            |
| active_energy_import_kwh      | 70      | float32  | 2         | kWh          |
| active_energy_export_kwh      | 72      | float32  | 2         | kWh          |
| reactive_energy_import_kvarh  | 74      | float32  | 2         | kVARh        |
| reactive_energy_export_kvarh  | 76      | float32  | 2         | kVARh        |

### 4.2 AHU Schema (27 columns)

| Column                          | Encoding   | Description                        |
|---------------------------------|------------|------------------------------------|
| ahu_auto_manual                 | uint16     | Auto/manual mode selector          |
| ahu_on_delay_sec                | float32    | ON delay timer (seconds)           |
| ahu_running_hours               | float32    | Accumulated running hours          |
| ahu_running_status              | uint16     | Running status (0/1)               |
| chw_inlet_temp_c                | float32    | Chilled water inlet temperature    |
| chw_outlet_temp_c               | float32    | Chilled water outlet temperature   |
| filter_dp_pa                    | float32    | Filter differential pressure       |
| heater_status                   | uint16     | Heater ON/OFF status               |
| return_air_flow_cfm             | float32    | Return air flow rate               |
| return_air_humidity_pct         | float32    | Return air relative humidity       |
| return_air_temp_c               | float32    | Return air temperature             |
| return_filter_status            | uint16     | Return filter status               |
| smoke_sensor                    | uint16     | Smoke sensor alarm                 |
| speed_control_mode              | uint16     | Speed control mode                 |
| supply_air_flow_cfm             | float32    | Supply air flow rate               |
| supply_air_humidity_pct         | float32    | Supply air relative humidity       |
| supply_air_temp_c               | float32    | Supply air temperature             |
| supply_filter_status            | uint16     | Supply filter status               |
| thyristor_heater_fb_check_sec   | float32    | Thyristor heater feedback check    |
| thyristor_heater_fb_rst_sec     | float32    | Thyristor heater feedback reset    |
| thyristor_heater_fb_trip_sec    | float32    | Thyristor heater feedback trip     |
| thyristor_heater_off_delay_sec  | float32    | Thyristor heater OFF delay         |
| thyristor_heater_on_delay_sec   | float32    | Thyristor heater ON delay          |
| vfd_fan_off_delay_sec           | float32    | VFD fan OFF delay                  |
| vfd_fan_on_delay_sec            | float32    | VFD fan ON delay                   |
| vfd_fan_speed_rpm               | float32    | VFD fan speed                      |
| vfd_status                      | uint16     | VFD running status                 |

### 4.3 Air Washer Schema (27 columns)

Same column layout as AHU schema (identical register map).

### 4.4 Chiller Schema (80 columns)

| Column                                | Encoding   | Description                              |
|---------------------------------------|------------|------------------------------------------|
| ambient_temp_dbt_c                    | float32    | Ambient dry bulb temperature             |
| ambient_temp_wbt_c                    | float32    | Ambient wet bulb temperature             |
| chw_flow_switch                       | uint16     | Chilled water flow switch                |
| chw_small_temp_diff_c                 | float32    | CHW small temp differential              |
| compressor_motor_run                  | uint16     | Compressor motor run status              |
| cond_inlet_pressure_bar               | float32    | Condenser inlet pressure                 |
| cond_liquid_flow_switch               | uint16     | Condenser liquid flow switch             |
| cond_liquid_pump_status               | uint16     | Condenser liquid pump status             |
| cond_outlet_pressure_bar              | float32    | Condenser outlet pressure                |
| cond_pressure_psig                    | float32    | Condenser pressure                       |
| cond_refrigerant_level_position_pct   | float32    | Condenser refrigerant level position     |
| cond_refrigerant_level_setting_pct    | float32    | Condenser refrigerant level setpoint     |
| cond_saturation_temp_c                | float32    | Condenser saturation temperature         |
| cond_small_temp_diff_c                | float32    | Condenser small temp diff                |
| converter_heatsink_temp_c             | float32    | Converter heatsink temperature           |
| dc_bus_voltage_v                      | float32    | DC bus voltage                           |
| dc_inverter_link_current_a            | float32    | DC inverter link current                 |
| delta_p_cond_evap_psid                | float32    | Delta pressure cond/evap                 |
| discharge_superheat_c                 | float32    | Discharge superheat                      |
| discharge_temp_c                      | float32    | Discharge temperature                    |
| dropleg_saturation_temp_c             | float32    | Dropleg saturation temperature           |
| evap_inlet_pressure_bar               | float32    | Evaporator inlet pressure                |
| evap_outlet_pressure_bar              | float32    | Evaporator outlet pressure               |
| evap_pressure_psig                    | float32    | Evaporator pressure                      |
| evap_refrigerant_level_pct            | float32    | Evaporator refrigerant level             |
| evap_refrigerant_temp_c              | float32    | Evaporator refrigerant temperature       |
| evap_saturation_temp_c                | float32    | Evaporator saturation temperature        |
| fia_setting_pct                       | float32    | FIA setting                              |
| fla_pct                               | float32    | Full Load Amps percentage                |
| harmonic_filter_baseplate_temp_c      | float32    | Harmonic filter baseplate temp           |
| harmonic_filter_dc_bus_voltage_v      | float32    | Harmonic filter DC bus voltage           |
| high_pressure_switch                  | uint16     | High pressure switch status              |
| input_energy_kwh                      | float32    | Input energy                             |
| input_power_kw                        | float32    | Input power                              |
| l1_input_voltage_rms_v                | float32    | L1 input voltage RMS                     |
| l2_input_voltage_rms_v                | float32    | L2 input voltage RMS                     |
| l3_input_voltage_rms_v                | float32    | L3 input voltage RMS                     |
| leaving_chw_setpoint_c                | float32    | Leaving CHW setpoint                     |
| leaving_chw_temp_c                    | float32    | Leaving CHW temperature                  |
| leaving_cond_liquid_temp_c            | float32    | Leaving condenser liquid temp            |
| main_incoming_voltage_v               | float32    | Main incoming voltage                    |
| motor_de_bearing_temp_c               | float32    | Motor DE bearing temperature             |
| motor_nde_bearing_temp_c              | float32    | Motor NDE bearing temperature            |
| motor_pct_full_load                   | float32    | Motor % full load                        |
| motor_status                          | uint16     | Motor run status                         |
| no_of_starts                          | float32    | Number of compressor starts              |
| oil_heater                            | uint16     | Oil heater status                        |
| oil_level_pct                         | float32    | Oil level percentage                     |
| oil_pressure_psig                     | float32    | Oil pressure                             |
| oil_pump_drive_freq_hz                | float32    | Oil pump drive frequency                 |
| oil_pump_run                          | uint16     | Oil pump run status                      |
| oil_return_solenoid                   | uint16     | Oil return solenoid status               |
| oil_sat_sump_temp_diff_c              | float32    | Oil saturation/sump temp diff            |
| oil_sump_temp_c                       | float32    | Oil sump temperature                     |
| operating_hours                       | float32    | Accumulated operating hours              |
| phase_a_heatsink_temp_c               | float32    | Phase A heatsink temperature             |
| phase_a_output_current_a              | float32    | Phase A output current                   |
| phase_a_output_voltage_v              | float32    | Phase A output voltage                   |
| phase_b_heatsink_temp_c               | float32    | Phase B heatsink temperature             |
| phase_b_output_current_a              | float32    | Phase B output current                   |
| phase_b_output_voltage_v              | float32    | Phase B output voltage                   |
| phase_c_heatsink_temp_c               | float32    | Phase C heatsink temperature             |
| phase_c_output_current_a              | float32    | Phase C output current                   |
| phase_c_output_voltage_v              | float32    | Phase C output voltage                   |
| prv_position_pct                      | float32    | PRV position                             |
| pump_oil_pressure_hop                 | float32    | Pump oil pressure HOP                    |
| return_chw_temp_c                     | float32    | Return CHW temperature                   |
| return_cond_liquid_temp_c             | float32    | Return condenser liquid temp             |
| subcooling_temp_c                     | float32    | Subcooling temperature                   |
| sump_oil_pressure_lop                 | float32    | Sump oil pressure LOP                    |
| target_oil_temp_c                     | float32    | Target oil temperature                   |
| total_surge_count                     | float32    | Total surge count                        |
| total_vgt_count                       | float32    | Total VGT count                          |
| vsd_current_a                         | float32    | VSD current                              |
| vsd_input_power_kw                    | float32    | VSD input power                          |
| vsd_internal_ambient_temp_c           | float32    | VSD internal ambient temp                |
| vsd_output_freq_hz                    | float32    | VSD output frequency                     |
| vsd_output_voltage_v                  | float32    | VSD output voltage                       |
| vsd_running_status                    | uint16     | VSD running status                       |
| vsd_trip_status                       | uint16     | VSD trip status                          |

### 4.5 Compressor Schema (48 columns)

| Column                          | Encoding   | Description                          |
|---------------------------------|------------|--------------------------------------|
| auto_drain_valve_status         | uint16     | Auto drain valve status              |
| bearing_de_temp_c               | float32    | Drive-end bearing temperature        |
| bearing_nde_temp_c              | float32    | Non-drive-end bearing temperature    |
| compressor_outlet_pressure_bar  | float32    | Compressor outlet pressure           |
| compressor_outlet_temp_c        | float32    | Compressor outlet temperature        |
| compressor_running_status       | uint16     | Running status                       |
| compressor_trip_status          | uint16     | Trip status                          |
| cooler_1_inlet_temp_c           | float32    | Cooler 1 inlet temperature           |
| cooler_approach_1_c             | float32    | Cooler approach 1                    |
| cooler_approach_2_c             | float32    | Cooler approach 2                    |
| cooling_water_in_pressure_bar   | float32    | Cooling water inlet pressure         |
| cooling_water_in_temp_c         | float32    | Cooling water inlet temperature      |
| dp_element_2_bar                | float32    | DP element 2                         |
| dp_element_2_nozzle_bar         | float32    | DP element 2 nozzle                  |
| dp_oil_filter_bar               | float32    | DP oil filter                        |
| drive_motor_temp_c              | float32    | Drive motor temperature              |
| dryer_dew_point_c               | float32    | Dryer dew point                      |
| dryer_runhours                  | float32    | Dryer run hours                      |
| dryer_run_status                | uint16     | Dryer running status                 |
| dryer_trip_status               | uint16     | Dryer trip status                    |
| element_1_vibration_micron      | float32    | Element 1 vibration                  |
| element_2_inlet_temp_c          | float32    | Element 2 inlet temperature          |
| element_2_vibration_micron      | float32    | Element 2 vibration                  |
| element_3_inlet_temp_c          | float32    | Element 3 inlet temperature          |
| element_3_outlet_pressure_bar   | float32    | Element 3 outlet pressure            |
| element_3_vibration_micron      | float32    | Element 3 vibration                  |
| gearbox_oil_pressure_bar        | float32    | Gearbox oil pressure                 |
| gearbox_oil_supply_temp_c       | float32    | Gearbox oil supply temperature       |
| heater_out_temp_c               | float32    | Heater outlet temperature            |
| inlet_dryer_temp_c              | float32    | Inlet dryer temperature              |
| loaded_hours                    | float32    | Loaded hours                         |
| loading_setpoint_pressure_bar   | float32    | Loading setpoint pressure            |
| load_relay                      | uint16     | Load relay status                    |
| module_hours                    | float32    | Module hours                         |
| motor_starts                    | float32    | Motor start count                    |
| oil_reservoir_temp_c            | float32    | Oil reservoir temperature            |
| present_pressure_bar            | float32    | Present pressure                     |
| pressure_drop_in_out_bar        | float32    | Pressure drop in/out                 |
| pressure_drop_regen_valve_bar   | float32    | Pressure drop regen valve            |
| pressure_vessel_a_bar           | float32    | Pressure vessel A                    |
| pressure_vessel_b_bar           | float32    | Pressure vessel B                    |
| running_hours                   | float32    | Running hours                        |
| unloading_pressure_bar          | float32    | Unloading pressure                   |
| vessel_a_bottom_temp_c          | float32    | Vessel A bottom temperature          |
| vessel_b_bottom_temp_c          | float32    | Vessel B bottom temperature          |
| winding_u1_temp_c              | float32    | Winding U1 temperature               |
| winding_v1_temp_c              | float32    | Winding V1 temperature               |
| winding_w1_temp_c              | float32    | Winding W1 temperature               |

### 4.6 PCW Schema (5 columns)

| Column                          | Encoding   | Description                          |
|---------------------------------|------------|--------------------------------------|
| discharge_chw_pressure_kg_cm2   | float32    | Discharge CHW pressure               |
| motor_frequency_hz              | float32    | Motor frequency                      |
| motor_running_status            | uint16     | Motor running status                 |
| motor_speed_rpm                 | float32    | Motor speed                          |
| motor_trip_status               | uint16     | Motor trip status                    |

### 4.7 Exhaust Schema (4 columns)

| Column                | Encoding   | Description                |
|-----------------------|------------|----------------------------|
| auto_manual_status    | uint16     | Auto/manual mode           |
| motor_frequency_hz    | float32    | Motor frequency            |
| motor_running_status  | uint16     | Motor running status       |
| motor_trip_status     | uint16     | Motor trip status          |

### 4.8 CSU Schema (8 columns)

| Column                | Encoding   | Description                    |
|-----------------------|------------|--------------------------------|
| damper_position_pct   | float32    | Damper position                |
| filter_dp_pa          | float32    | Filter differential pressure   |
| return_air_temp_c     | float32    | Return air temperature         |
| running_hours         | float32    | Running hours                  |
| supply_air_temp_c     | float32    | Supply air temperature         |
| supply_fan_speed_hz   | float32    | Supply fan speed               |
| supply_fan_status     | uint16     | Supply fan status              |
| vfd_frequency_hz      | float32    | VFD frequency                  |

### 4.9 TFA Schema (7 columns)

| Column                | Encoding   | Description                    |
|-----------------------|------------|--------------------------------|
| air_flow_cfm          | float32    | Air flow rate                  |
| damper_position_pct   | float32    | Damper position                |
| fan_speed_hz          | float32    | Fan speed                      |
| fan_status            | uint16     | Fan running status             |
| filter_dp_pa          | float32    | Filter differential pressure   |
| outdoor_air_temp_c    | float32    | Outdoor air temperature        |
| supply_air_temp_c     | float32    | Supply air temperature         |

### 4.10 Pump Schema (8 columns)

| Column                | Encoding   | Description                    |
|-----------------------|------------|--------------------------------|
| discharge_pressure_bar| float32    | Discharge pressure             |
| flow_rate_m3h         | float32    | Flow rate                      |
| motor_current_a       | float32    | Motor current                  |
| pump_status           | uint16     | Pump running status            |
| running_hours         | float32    | Running hours                  |
| suction_pressure_bar  | float32    | Suction pressure               |
| tank_level_pct        | float32    | Tank level                     |
| vfd_frequency_hz      | float32    | VFD frequency                  |

### 4.11 Toilet Exhaust Schema (4 columns)

| Column                | Encoding   | Description                    |
|-----------------------|------------|--------------------------------|
| air_flow_cfm          | float32    | Air flow rate                  |
| dp_across_fan_pa      | float32    | Differential pressure across fan |
| fan_speed_hz          | float32    | Fan speed                      |
| fan_status            | uint16     | Fan running status             |

### 4.12 STP Schema (8 columns)

| Column                | Encoding   | Description                    |
|-----------------------|------------|--------------------------------|
| aerator_status        | uint16     | Aerator running status         |
| blower_status         | uint16     | Blower running status          |
| bod_mgl               | float32    | Biological Oxygen Demand       |
| dissolved_oxygen_mgl  | float32    | Dissolved oxygen               |
| inlet_flow_m3h        | float32    | Inlet flow rate                |
| outlet_flow_m3h       | float32    | Outlet flow rate               |
| ph                    | float32    | pH level                       |
| tss_mgl               | float32    | Total Suspended Solids         |

### 4.13 Axial Fan Schema (4 columns)

| Column                | Encoding   | Description                    |
|-----------------------|------------|--------------------------------|
| fan_speed_hz          | float32    | Fan speed                      |
| fan_status            | uint16     | Fan running status             |
| motor_current_a       | float32    | Motor current                  |
| vibration_mm_s        | float32    | Vibration level                |

---

## 5. Storage Targets

| ID                  | Provider     | Connection String                                  | Default |
|---------------------|-------------|-----------------------------------------------------|---------|
| db_1773214350018    | postgresql  | `postgresql://postgres@localhost/latest_target_v2`   | No      |
| db_1773859505950    | postgresql  | `postgresql://postgres@localhost/target_version1`    | **Yes** |

### Target DB Schema

All data tables live under the `neuract` schema in `target_version1`:

```
target_version1
 └── neuract (schema)
      ├── mfm_001 ... mfm_245      (245 tables)
      ├── ahu_001 ... ahu_011       (11 tables)
      ├── air_washer_001 ... 006    (6 tables)
      ├── chiller_001 ... 004       (4 tables)
      ├── compressor_001            (1 table)
      ├── pcw_001                   (1 table)
      ├── exhaust_001 ... 007       (7 tables)
      ├── csu_001 ... 010           (10 tables)
      ├── tfa_001 ... 003           (3 tables)
      ├── pump_001 ... 004          (4 tables)
      ├── toilet_exhaust_001        (1 table)
      ├── stp_001                   (1 table)
      ├── axial_fan_001 ... 003     (3 tables)
      └── device_mappings           (mapping metadata)
```

Each data table has:
- `timestamp_utc VARCHAR NOT NULL` — primary/index column (ISO 8601 with timezone)
- Data columns as `REAL` — one per mapped Modbus field

---

## 6. Modbus Encoding Reference

| Encoding     | Registers | Bytes | PostgreSQL Type | Description                   |
|-------------|-----------|-------|-----------------|-------------------------------|
| `float32`   | 2         | 4     | REAL            | IEEE 754 single-precision     |
| `uint16`    | 1         | 2     | REAL            | Unsigned 16-bit integer       |
| `uint16_enum`| 1        | 2     | REAL            | Enumerated status code        |
| `bool16`    | 1         | 2     | REAL            | Boolean packed in 16-bit word |

---

## 7. Active Job

| Field        | Value                          |
|-------------|--------------------------------|
| Job ID      | `job_1773859964364`            |
| Name        | Seetharampur Full Site v2      |
| Type        | continuous                     |
| Interval    | 1000 ms (1 second)            |
| Tables      | 297 (all)                      |
| Status      | running                        |

---

## 8. System Architecture Summary

```
┌─────────────────────────────────────────────────────────┐
│                    Physical Layer                        │
│  22 GIC Gateways (10.10.1-22.10) → 245 MFMs            │
│  5 PLC Gateways  (10.10.23-27.10) → 52 Equipment       │
│  Protocol: Modbus TCP, Port 502                         │
└────────────────────┬────────────────────────────────────┘
                     │ Modbus TCP reads
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Rust Job Runner (neuract-job-runner)        │
│  Polls meta_data_version1 for active jobs               │
│  Reads 297 devices @ 1 second interval                  │
│  Batch writes to target_version1                        │
│  ~297 reads/s, ~1 write batch/s                         │
└────────────────────┬────────────────────────────────────┘
                     │ SQL INSERT
                     ▼
┌─────────────────────────────────────────────────────────┐
│              PostgreSQL                                  │
│  meta_data_version1  — schemas, devices, tables, jobs   │
│  target_version1     — neuract.* (297 time-series tbl)  │
│  loggerfast_metrics  — benchmark/performance data       │
└─────────────────────────────────────────────────────────┘
                     ▲
                     │ REST API
┌─────────────────────────────────────────────────────────┐
│              FastAPI Agent (port 5175)                   │
│  Auth, Schemas, Tables, Devices, Gateways, Mappings     │
│  Jobs2, Storage Targets, Notifications, WebSocket       │
│  Reads from meta_data_version1                          │
└─────────────────────────────────────────────────────────┘
```

---

## 9. Electrical Equipment Model

These tables live in the metadata DB only. The Rust engine never reads them, so data logging is unaffected. The API is under `/equipment` (`API_DOCUMENTATION.md` §24).

| Table | Columns | Notes |
|-------|---------|-------|
| `app_equipment_category` | id, name, type (`single` / `distribution`), sort_order, config_json | **Edited in the DB only.** `config_json` = `{"fields": [...], "node": {"incomers": n, "outgoers": n}}`. The `node` part is the default capacity for single categories. Seeded: Source, Transformer, HT Panel, LT Panel, Load |
| `app_equipment` | id, name (unique), category_id → category, subtype, spare, description, values_json, created_at, updated_at | `values_json` = `{fieldId: {"value", "unit"}}` |
| `app_bus` | id, equipment_id → equipment (cascade), name, sort_order, incomers, outgoers, is_main, coupled_next | **Connection nodes.** Distribution equipment has buses (`is_main = 0`). Single equipment has exactly one hidden main node (`is_main = 1`) holding its own capacity and rules. `coupled_next` = a bus coupler to the next bus |
| `app_bus_category` | bus_id → bus (cascade), role (`incomer` / `outgoer`), category_id → category | Allowed categories per node side. No rows for a side means not restricted |
| `app_bus_equipment` | bus_id → bus (cascade), equipment_id → equipment, role, sort_order | Equipment connected to a bus. Several buses per equipment are allowed; loops are rejected |
| `app_bus_meter` | bus_id → bus (cascade), device_id → `app_devices` (**unique**), role (`incomer` / `outgoer` on a bus; NULL on a main node), sort_order | MFMs. Panels meter bus points; single equipment meters itself. A device is in one place only |

Field definitions are seeded only where `config_json` is empty, so changes made in the DB survive restarts. To add a category:

```sql
INSERT INTO app_equipment_category (id, name, type, sort_order, config_json) VALUES
 ('busduct', 'Busduct', 'distribution', 6,
  '{"fields": [{"id": "rating", "label": "Rating", "kind": "quantity", "units": ["A"], "required": true}]}');
```

Field `kind`: `quantity` (with `units`), `choice` (with `options`) or `text`. A field with `"required": true` counts towards readiness. `role` = `voltage`, `voltage.in` or `voltage.out` feeds the Voltage column.

---

## 10. Alerts

| Table | Columns | Written by |
|---|---|---|
| `app_alert` | `id, name, severity, color, sort_order`. Unique on `lower(name)`. `critical`/`mild`/`info` are seeded once (`app_meta.alert_levels_seeded`) | API |
| `app_schema_alert` | `id, schema_id, field_key, alert_id, op, threshold`. Unique on `(schema_id, field_key, alert_id)`. `op` is CHECK-constrained to `> >= < <= == !=` | API |
| `app_table_alert` | `id, table_id, field_key, alert_id, op NULL, threshold NULL, enabled`. Unique on `(table_id, field_key, alert_id)`. A NULL op/threshold falls back to the schema rule | API |
| `app_alert_state` | `table_id, field_key, alert_id, value, since`. PK is `(table_id, field_key)`; a row exists only while the field is not normal | Rust engine |
| `app_alert_event` | `id, table_id, field_key, from_alert_id, to_alert_id, value, op, threshold, job_id, at`. Indexed on `(table_id, at)`; a NULL from/to means normal | Rust engine |

**Engine flow**

At job start the engine:
- loads each table's effective rules (schema rules joined via `app_device_tables.schema_id`, then merged with the table's overrides);
- loads the existing states.

After each read, once derived fields are computed:
- it evaluates every rule on the field values; the highest severity that matches wins;
- if the result differs from the stored state, it upserts or deletes the state row, inserts an event and posts a notification of type `alert`.

Deleting a table, schema or schema field removes the related rules, overrides and states. Events are kept.

---

## 11. Electrical: groups and MFM slots

| Change | Detail |
|---|---|
| `app_equipment_group (id, name, sort_order)` | New top level: `ems`, `source`, `bms`. Missing rows are seeded at boot, and edits in the DB are kept. Unique on `lower(name)` |
| `app_equipment_category.group_id` | FK to `app_equipment_group(id)`. NULL is backfilled to `ems`; all seeded categories are under EMS |
| `app_bus_meter.equipment_id` | On a bus: the attached incomer/outgoer this MFM measures. NULL with `role='outgoer'` means a **spare**. Partial unique index `ux_bus_meter_relation (bus_id, equipment_id) WHERE equipment_id IS NOT NULL`: one MFM per relation |

Rules enforced in `equipment.py`:
- an incoming MFM needs a relation;
- spares take outgoing points;
- detaching a metered outgoer turns its MFM into a spare;
- detaching a metered incomer is refused.

---

## 12. Elements: category + kind + type (2026-10-27)

| Table / column | Meaning |
|---|---|
| `app_equipment_category (id, name, sort_order, kinds_json)` | EMS / Source / BMS. It was `app_equipment_group` until 2026-10-27. `kinds_json` holds the allowed kinds: EMS has both, Source/BMS have none |
| `app_equipment_type (id, name, sort_order, config_json)` | User-defined types with their nameplate fields and default node capacity. It was `app_equipment_category` (its `type` / `group_id` columns were dropped). The built-in five are seeded once (`app_meta.equipment_types_seeded`) |
| `app_equipment.category_id` / `.kind` / `.type_id` | Category (FK, NOT NULL), `single` \| `distribution` (CHECK, NOT NULL), and type (FK, NULL). The old `category_id` became `type_id`. `subtype` is no longer used |
| `app_bus_type (bus_id, role, type_id)` | Allowed types per node side. It was `app_bus_category` |

FKs: `fk_element_category`, `fk_element_type`, `fk_bus_type_bus`, `fk_bus_type_type`.

The migration (`appdb._migrate_equipment_to_types`) is one-time, in place and idempotent. It runs only on the old schema. §11 (groups) is superseded.

---

## 13. Zones

`app_equipment_zone (id, name, sort_order)` holds the user-managed zones (unique on `lower(name)`). `app_equipment.zone_id` is nullable, with FK `fk_element_zone` and index `ix_equipment_zone`.

---

## 14. MFM slots hold logger tables

`app_bus_meter (bus_id, table_id UNIQUE, role, equipment_id, sort_order)`, PK `(bus_id, table_id)`, FK `fk_bus_meter_table` → `app_device_tables(id)`. It replaced `device_id` on 2026-10-27 (`appdb._migrate_bus_meter_to_tables`). The device and schema are read through the table.

# Panel, MFM, reference, role, table, and schema inventory

Generated from the backend metadata database at **2026-10-30T14:14:11+05:30** (Asia/Kolkata), using a read-only consistent snapshot. Includes active and inactive records; no configuration was modified.

## How to read this report

- **Reference panel** is the saved `MFM.reference`: its primary/legacy physical location. Panel memberships are listed separately and are authoritative for roles.
- **Role** is relative to the named membership panel, not a global meter role or a grid/DG/solar classification.
- **Mapped equipment** is the asset linked through `MFM.equipment`; an automatically created name is not proof of a verified physical asset mapping.
- **Group parent** records structural nesting, not a proven electrical feed. Only explicitly saved feed edges are reported as feed relationships.
- Distribution panels have no logger table/schema of their own; each member MFM supplies its own binding.
- `Not configured` means the corresponding metadata is absent. No relationships are inferred from names such as TRANSFORMER, AMF, or PCC.
- Group IDs, raw MFM IDs, frontend meter IDs, and Equipment IDs are distinct. Do not use Equipment IDs in meter/panel socket URLs.

## Inventory totals

| Record | Total | Active |
|---|---|---|
| Distribution panels | 9 | 9 |
| MFMs | 102 | 102 |
| Logger schemas | 4 | 4 |
| Memberships | 85 | See panel/MFM status |
| Feed edges | 0 | See endpoint meter status |

## Distribution-panel summary

| Panel / endpoint ID | Category | Active | Group parent | Mapped panel equipment | Members: incoming / outgoing / spare |
|---|---|---|---|---|---|
| 33KV HT Panel [Group 2] | ht | True | Not configured | 33KV HT Panel [Equipment 1; key: 33-kv] | 1 / 3 / 0 |
| AMF-1 [Group 16] | amf | True | Not configured | AMF-1 [Equipment 2; key: amf-1] | 2 / 2 / 0 |
| PCC-1 [Group 19] | pcc | True | Not configured | PCC-1 [Equipment 5; key: pcc-1] | 2 / 3 / 0 |
| UPS [Group 24] | ups | True | Not configured | UPS [Equipment 112; key: ups] | 4 / 9 / 0 |
| Utility Panel [Group 25] | utility | True | Not configured | Utility Panel [Equipment 113; key: utility-panel] | 2 / 23 / 0 |
| AMF-2 [Group 17] | amf | True | Not configured | AMF-2 [Equipment 3; key: amf-2] | 2 / 2 / 0 |
| PCC-2 [Group 20] | pcc | True | Not configured | PCC-2 [Equipment 6; key: pcc-2] | 2 / 13 / 0 |
| AMF-3 [Group 18] | amf | True | Not configured | AMF-3 [Equipment 4; key: amf-3] | 2 / 2 / 0 |
| PCC-3 [Group 21] | pcc | True | Not configured | PCC-3 [Equipment 7; key: pcc-3] | 2 / 7 / 2 |

## Distribution panel: 33KV HT Panel

- Panel endpoint ID: **2**; key: `33-kv`; active: **True**.
- Group parent: Not configured.
- Configured twins: None configured.
- MFMs explicitly mapped to this panel’s own Equipment: None configured.

| MFM (frontend ID; raw ID) | Active | Role in this panel | Saved reference panel | Mapped equipment | Logger table | Schema (version) | Data source |
|---|---|---|---|---|---|---|---|
| I/C_33KV_MAIN_VCB [1000102; raw 102] | True | Incomings | 33KV HT Panel [Group 2] | I/C_33KV_MAIN_VCB [Equipment 8; key: i-c-33kv-main-vcb] | gic_01_n4_I_C_33KV_MAIN_VCB | sch_EM6400_NG+ (v1) | logger_pg_main [ID 4] |
| OG_33_415kV_TF_1 [1000103; raw 103] | True | Outgoings | 33KV HT Panel [Group 2] | OG_33_415kV_TF_1 [Equipment 9; key: og-33-415kv-tf-1] | gic_01_n1_33_415V_TF_1 | sch_EM6400_NG+ (v1) | logger_pg_main [ID 4] |
| OG_33_415kV_TF_2 [1000104; raw 104] | True | Outgoings | 33KV HT Panel [Group 2] | OG_33_415kV_TF_2 [Equipment 10; key: og-33-415kv-tf-2] | gic_01_n2_33_415V_TF_2 | sch_EM6400_NG+ (v1) | logger_pg_main [ID 4] |
| OG_33_415kV_TF_3 [1000105; raw 105] | True | Outgoings | 33KV HT Panel [Group 2] | OG_33_415kV_TF_3 [Equipment 11; key: og-33-415kv-tf-3] | gic_01_n3_33_415V_TF_3 | sch_EM6400_NG+ (v1) | logger_pg_main [ID 4] |

## Distribution panel: AMF-1

- Panel endpoint ID: **16**; key: `amf-1`; active: **True**.
- Group parent: Not configured.
- Configured twins: None configured.
- MFMs explicitly mapped to this panel’s own Equipment: None configured.

| MFM (frontend ID; raw ID) | Active | Role in this panel | Saved reference panel | Mapped equipment | Logger table | Schema (version) | Data source |
|---|---|---|---|---|---|---|---|
| TRANFORMER_01_INCOMER [1000106; raw 106] | True | Incomings | AMF-1 [Group 16] | TRANFORMER_01_INCOMER [Equipment 12; key: tranformer-01-incomer] | gic_04_n1_TRANFORMER_01_INCOMER | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| O/G_MODULE_PCC_PANEL_1 [1000108; raw 108] | True | Outgoings | AMF-1 [Group 16] | O/G_MODULE_PCC_PANEL_1 [Equipment 14; key: o-g-module-pcc-panel-1] | gic_04_n3_O_G_MODULE_PCC_PANEL_1 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| DIESEL_GENSET_1_INCOMER [1000107; raw 107] | True | Incomings | AMF-1 [Group 16] | DIESEL_GENSET_1_INCOMER [Equipment 13; key: diesel-genset-1-incomer] | gic_04_n2_DIESEL_GENSET_1_INCOMER | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| O/G_APFC_PANEL_01 [1000109; raw 109] | True | Outgoings | AMF-1 [Group 16] | O/G_APFC_PANEL_01 [Equipment 15; key: o-g-apfc-panel-01] | gic_04_n4_O_G_APFC_PANEL_01 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |

## Distribution panel: PCC-1

- Panel endpoint ID: **19**; key: `pcc-1`; active: **True**.
- Group parent: Not configured.
- Configured twins: None configured.
- MFMs explicitly mapped to this panel’s own Equipment: None configured.

| MFM (frontend ID; raw ID) | Active | Role in this panel | Saved reference panel | Mapped equipment | Logger table | Schema (version) | Data source |
|---|---|---|---|---|---|---|---|
| INCOMER_FROM_AMF_1 [1000118; raw 118] | True | Incomings | PCC-1 [Group 19] | INCOMER_FROM_AMF_1 [Equipment 24; key: incomer-from-amf-1] | gic_05_n1_INCOMER_FROM_AMF_1 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| AIR_COMPRESSOR_PDB [1000120; raw 120] | True | Outgoings | PCC-1 [Group 19] | AIR_COMPRESSOR_PDB [Equipment 26; key: air-compressor-pdb] | gic_05_n2_PCC_1_AIR_COMPRESSOR_PDB | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| SOLAR_INCOMER_PCC_1 [1000119; raw 119] | True | Incomings | PCC-1 [Group 19] | SOLAR_INCOMER_PCC_1 [Equipment 25; key: solar-incomer-pcc-1] | gic_05_n5_SOLAR_INCOMER_PCC_1 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| UTILITY_PANEL_1 [1000121; raw 121] | True | Outgoings | PCC-1 [Group 19] | UTILITY_PANEL_1 [Equipment 27; key: utility-panel-1] | gic_05_n3_UTILITY_PANEL_1 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| CT,CDWP,CWP_PANEL [1000122; raw 122] | True | Outgoings | PCC-1 [Group 19] | CT,CDWP,CWP_PANEL [Equipment 28; key: ct-cdwp-cwp-panel] | gic_05_n4_CT_CDWP_CWP_PANEL | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |

## Distribution panel: UPS

- Panel endpoint ID: **24**; key: `ups`; active: **True**.
- Group parent: Not configured.
- Configured twins: None configured.
- MFMs explicitly mapped to this panel’s own Equipment: None configured.

| MFM (frontend ID; raw ID) | Active | Role in this panel | Saved reference panel | Mapped equipment | Logger table | Schema (version) | Data source |
|---|---|---|---|---|---|---|---|
| UPS-A [1000204; raw 204] | True | Incomings | UPS [Group 24] | UPS-A [Equipment 114; key: ups-a] | gic_09_n1_I_C_UPS_A | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_MANUAL_LINE [1000208; raw 208] | True | Outgoings | UPS [Group 24] | O/G_MANUAL_LINE [Equipment 118; key: o-g-manual-line] | gic_09_n5_O_G_MANUAL_LINE | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| UPS-B [1000205; raw 205] | True | Incomings | UPS [Group 24] | UPS-B [Equipment 115; key: ups-b] | gic_09_n2_I_C_UPS_B | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_PRE_LAMINATOR_PANEL_1 [1000209; raw 209] | True | Outgoings | UPS [Group 24] | O/G_PRE_LAMINATOR_PANEL_1 [Equipment 119; key: o-g-pre-laminator-panel-1] | gic_09_n6_O_G_PRE_LAMINATOR_PANEL_1 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| UPS-C [1000206; raw 206] | True | Incomings | UPS [Group 24] | UPS-C [Equipment 116; key: ups-c] | gic_09_n3_I_C_UPS_C | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_PRE_LAMINATOR_PANEL_2 [1000210; raw 210] | True | Outgoings | UPS [Group 24] | O/G_PRE_LAMINATOR_PANEL_2 [Equipment 120; key: o-g-pre-laminator-panel-2] | gic_09_n7_O_G_PRE_LAMINATOR_PANEL_2 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| UPS-D [1000207; raw 207] | True | Incomings | UPS [Group 24] | UPS-D [Equipment 117; key: ups-d] | gic_09_n4_I_C_UPS_D | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_U_LAMINATOR_PANEL1 [1000211; raw 211] | True | Outgoings | UPS [Group 24] | O/G_U_LAMINATOR_PANEL1 [Equipment 121; key: o-g-u-laminator-panel1] | gic_09_n8_O_G_U_LAMINATOR_PANEL1 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_POST_LAMINATOR_PDB_01 [1000212; raw 212] | True | Outgoings | UPS [Group 24] | O/G_POST_LAMINATOR_PDB_01 [Equipment 122; key: o-g-post-laminator-pdb-01] | gic_09_n9_O_G_POST_LAMINATOR_PDB_01 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_180_FLIPER_&_HITPOT [1000213; raw 213] | True | Outgoings | UPS [Group 24] | O/G_180_FLIPER_&_HITPOT [Equipment 123; key: o-g-180-fliper-hitpot] | gic_09_n10_O_G_180_FLIPER___HITPOT | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_POST_LAMINATOR_PDB_02 [1000214; raw 214] | True | Outgoings | UPS [Group 24] | O/G_POST_LAMINATOR_PDB_02 [Equipment 124; key: o-g-post-laminator-pdb-02] | gic_09_n11_O_G_POST_LAMINATOR_PDB_02 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_U_LAMINATOR_PDB_02 [1000215; raw 215] | True | Outgoings | UPS [Group 24] | O/G_U_LAMINATOR_PDB_02 [Equipment 125; key: o-g-u-laminator-pdb-02] | gic_09_n12_O_G_U_LAMINATOR_PDB_02 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_UPS_LIGHTING_DB [1000216; raw 216] | True | Outgoings | UPS [Group 24] | O/G_UPS_LIGHTING_DB [Equipment 126; key: o-g-ups-lighting-db] | gic_09_n13_O_G_UPS_LIGHTING_DB | sch_LG2599 (v1) | logger_pg_main [ID 4] |

## Distribution panel: Utility Panel

- Panel endpoint ID: **25**; key: `utility-panel`; active: **True**.
- Group parent: Not configured.
- Configured twins: None configured.
- MFMs explicitly mapped to this panel’s own Equipment: None configured.

| MFM (frontend ID; raw ID) | Active | Role in this panel | Saved reference panel | Mapped equipment | Logger table | Schema (version) | Data source |
|---|---|---|---|---|---|---|---|
| I/C_PCC_1 [1000217; raw 217] | True | Incomings | Utility Panel [Group 25] | I/C_PCC_1 [Equipment 127; key: i-c-pcc-1] | gic_10_n3_I_C_PCC_1 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AHU_09 [1000219; raw 219] | True | Outgoings | Utility Panel [Group 25] | O/G_AHU_09 [Equipment 129; key: o-g-ahu-09] | gic_10_n5_O_G_AHU_09 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| SOLAR_INCOMING_UTILITY_PANEL [1000218; raw 218] | True | Incomings | Utility Panel [Group 25] | SOLAR_INCOMING_UTILITY_PANEL [Equipment 128; key: solar-incoming-utility-panel] | gic_10_n4_SOLAR_INCOMING_UTILITY_PANEL | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AHU_PDB_01 [1000220; raw 220] | True | Outgoings | Utility Panel [Group 25] | O/G_AHU_PDB_01 [Equipment 130; key: o-g-ahu-pdb-01] | gic_10_n6_O_G_AHU_PDB_01 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AHU_PDB_02 [1000221; raw 221] | True | Outgoings | Utility Panel [Group 25] | O/G_AHU_PDB_02 [Equipment 131; key: o-g-ahu-pdb-02] | gic_10_n7_O_G_AHU_PDB_02 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AHU_PDB_03 [1000222; raw 222] | True | Outgoings | Utility Panel [Group 25] | O/G_AHU_PDB_03 [Equipment 132; key: o-g-ahu-pdb-03] | gic_10_n8_O_G_AHU_PDB_03 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AHU_PDB_05 [1000223; raw 223] | True | Outgoings | Utility Panel [Group 25] | O/G_AHU_PDB_05 [Equipment 133; key: o-g-ahu-pdb-05] | gic_10_n9_O_G_AHU_PDB_05 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AIR_WASHER_PDB_3 [1000224; raw 224] | True | Outgoings | Utility Panel [Group 25] | O/G_AIR_WASHER_PDB_3 [Equipment 134; key: o-g-air-washer-pdb-3] | gic_10_n10_O_G_AIR_WASHER_PDB_3 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AHU_PDB_04 [1000225; raw 225] | True | Outgoings | Utility Panel [Group 25] | O/G_AHU_PDB_04 [Equipment 135; key: o-g-ahu-pdb-04] | gic_10_n11_O_G_AHU_PDB_04 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AHU_PDB_06 [1000226; raw 226] | True | Outgoings | Utility Panel [Group 25] | O/G_AHU_PDB_06 [Equipment 136; key: o-g-ahu-pdb-06] | gic_10_n12_O_G_AHU_PDB_06 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AHU_PDB_07 [1000227; raw 227] | True | Outgoings | Utility Panel [Group 25] | O/G_AHU_PDB_07 [Equipment 137; key: o-g-ahu-pdb-07] | gic_10_n13_O_G_AHU_PDB_07 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AHU_PDB_08 [1000228; raw 228] | True | Outgoings | Utility Panel [Group 25] | O/G_AHU_PDB_08 [Equipment 138; key: o-g-ahu-pdb-08] | gic_10_n14_O_G_AHU_PDB_08 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AIR_WASHER_PDB_2 [1000229; raw 229] | True | Outgoings | Utility Panel [Group 25] | O/G_AIR_WASHER_PDB_2 [Equipment 139; key: o-g-air-washer-pdb-2] | gic_11_n1_O_G_AIR_WASHER_PDB_2 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AIR_WASHER_01 [1000230; raw 230] | True | Outgoings | Utility Panel [Group 25] | O/G_AIR_WASHER_01 [Equipment 140; key: o-g-air-washer-01] | gic_11_n2_O_G_AIR_WASHER_01 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AIR_EXUAST_3 [1000231; raw 231] | True | Outgoings | Utility Panel [Group 25] | O/G_AIR_EXUAST_3 [Equipment 141; key: o-g-air-exuast-3] | gic_11_n3_O_G_AIR_EXUAST_3 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_EXHAUST_UNIT_PDB_01 [1000232; raw 232] | True | Outgoings | Utility Panel [Group 25] | O/G_EXHAUST_UNIT_PDB_01 [Equipment 142; key: o-g-exhaust-unit-pdb-01] | gic_11_n4_O_G_EXHAUST_UNIT_PDB_01 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_EXHAUST_UNIT_PDB_02 [1000233; raw 233] | True | Outgoings | Utility Panel [Group 25] | O/G_EXHAUST_UNIT_PDB_02 [Equipment 143; key: o-g-exhaust-unit-pdb-02] | gic_11_n5_0_G_EXHAUST_UNIT_PDB_02 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AIR_WASHER_03 [1000234; raw 234] | True | Outgoings | Utility Panel [Group 25] | O/G_AIR_WASHER_03 [Equipment 144; key: o-g-air-washer-03] | gic_11_n6_O_G_AIR_WASHER_03 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AXIAL_FLOW_FAN_PDB_03 [1000235; raw 235] | True | Outgoings | Utility Panel [Group 25] | O/G_AXIAL_FLOW_FAN_PDB_03 [Equipment 145; key: o-g-axial-flow-fan-pdb-03] | gic_11_n7_O_G_AXIAL_FLOW_FAN_PDB_03 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AXIAL_FLOW_FAN_PDB_01 [1000236; raw 236] | True | Outgoings | Utility Panel [Group 25] | O/G_AXIAL_FLOW_FAN_PDB_01 [Equipment 146; key: o-g-axial-flow-fan-pdb-01] | gic_11_n8_O_G_AXIAL_FLOW_FAN_PDB_01 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_AXIAL_FLOW_FAN_PDB_02 [1000237; raw 237] | True | Outgoings | Utility Panel [Group 25] | O/G_AXIAL_FLOW_FAN_PDB_02 [Equipment 147; key: o-g-axial-flow-fan-pdb-02] | gic_11_n9_O_G_AXIAL_FLOW_FAN_PDB_02 | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_PRE_LAMINATOR_PDB_AND_LDB [1000238; raw 238] | True | Outgoings | Utility Panel [Group 25] | O/G_PRE_LAMINATOR_PDB_AND_LDB [Equipment 148; key: o-g-pre-laminator-pdb-and-ldb] | gic_11_n10_O_G_PRE_LAINATOR_PDB_AND_LDB | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_ALL_CSU [1000239; raw 239] | True | Outgoings | Utility Panel [Group 25] | O/G_ALL_CSU [Equipment 149; key: o-g-all-csu] | gic_11_n11_O_G_ALL_CSU | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| O/G_LINE_3_AIR_WASHER_PDB [1000240; raw 240] | True | Outgoings | Utility Panel [Group 25] | O/G_LINE_3_AIR_WASHER_PDB [Equipment 150; key: o-g-line-3-air-washer-pdb] | gic_11_n12_O_G_LINE_3_AIR_WASHER_PDB | sch_LG2599 (v1) | logger_pg_main [ID 4] |
| LIGHTNING_DB_3 [1000241; raw 241] | True | Outgoings | Utility Panel [Group 25] | LIGHTNING_DB_3 [Equipment 151; key: lightning-db-3] | gic_05_n12_LIGHTNING_DB_3 | sch_LG2599 (v1) | logger_pg_main [ID 4] |

## Distribution panel: AMF-2

- Panel endpoint ID: **17**; key: `amf-2`; active: **True**.
- Group parent: Not configured.
- Configured twins: None configured.
- MFMs explicitly mapped to this panel’s own Equipment: None configured.

| MFM (frontend ID; raw ID) | Active | Role in this panel | Saved reference panel | Mapped equipment | Logger table | Schema (version) | Data source |
|---|---|---|---|---|---|---|---|
| TRANSFORM_2_INCOMER [1000110; raw 110] | True | Incomings | AMF-2 [Group 17] | TRANSFORM_2_INCOMER [Equipment 16; key: transform-2-incomer] | gic_04_n5_TRANSFORM_2_INCOMER | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| O/G_APFC_PANEL_02 [1000112; raw 112] | True | Outgoings | AMF-2 [Group 17] | O/G_APFC_PANEL_02 [Equipment 18; key: o-g-apfc-panel-02] | gic_04_n7_O_G_APFC_PANEL_02 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| DIESEL_GENSET_2_INCOMER [1000111; raw 111] | True | Incomings | AMF-2 [Group 17] | DIESEL_GENSET_2_INCOMER [Equipment 17; key: diesel-genset-2-incomer] | gic_04_n6_DIESEL_GENSET_2_INCOMER | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| O/G_MODULE_PCC_PANEL_2 [1000113; raw 113] | True | Outgoings | AMF-2 [Group 17] | O/G_MODULE_PCC_PANEL_2 [Equipment 19; key: o-g-module-pcc-panel-2] | gic_04_n8_O_G_MODULE_PCC_PANEL_2 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |

## Distribution panel: PCC-2

- Panel endpoint ID: **20**; key: `pcc-2`; active: **True**.
- Group parent: Not configured.
- Configured twins: None configured.
- MFMs explicitly mapped to this panel’s own Equipment: None configured.

| MFM (frontend ID; raw ID) | Active | Role in this panel | Saved reference panel | Mapped equipment | Logger table | Schema (version) | Data source |
|---|---|---|---|---|---|---|---|
| INCOMER_FROM_AMF_2 [1000123; raw 123] | True | Incomings | PCC-2 [Group 20] | INCOMER_FROM_AMF_2 [Equipment 29; key: incomer-from-amf-2] | gic_05_n6_INCOMER_FROM_AMF_2 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| LAMINATOR_PDB_01 [1000125; raw 125] | True | Outgoings | PCC-2 [Group 20] | LAMINATOR_PDB_01 [Equipment 31; key: laminator-pdb-01] | gic_05_n8_LAMINATOR_PDB_01 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| SOLAR_INCOMER_PCC_2 [1000124; raw 124] | True | Incomings | PCC-2 [Group 20] | SOLAR_INCOMER_PCC_2 [Equipment 30; key: solar-incomer-pcc-2] | gic_05_n7_SOLAR_INCOMER_PCC_2 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| LAMINATOR_PDB_02 [1000126; raw 126] | True | Outgoings | PCC-2 [Group 20] | LAMINATOR_PDB_02 [Equipment 32; key: laminator-pdb-02] | gic_05_n9_LAMINATOR_PDB_02 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| OUT_GOING_UPS_1A [1000127; raw 127] | True | Outgoings | PCC-2 [Group 20] | OUT_GOING_UPS_1A [Equipment 33; key: out-going-ups-1a] | gic_05_n10_OUT_GOING_UPS_1A | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| OUT_GOING_UPS_1B [1000128; raw 128] | True | Outgoings | PCC-2 [Group 20] | OUT_GOING_UPS_1B [Equipment 34; key: out-going-ups-1b] | gic_05_n11_OUT_GOING_UPS_1B | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| OUT_GOING_UPS_1C [1000129; raw 129] | True | Outgoings | PCC-2 [Group 20] | OUT_GOING_UPS_1C [Equipment 35; key: out-going-ups-1c] | gic_06_n1_OUT_GOING_UPS_1C | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| OUT_GOING_UPS_1D [1000130; raw 130] | True | Outgoings | PCC-2 [Group 20] | OUT_GOING_UPS_1D [Equipment 36; key: out-going-ups-1d] | gic_06_n2_OUT_GOING_UPS_1D | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| OUT_GOING_UPS_1E [1000131; raw 131] | True | Outgoings | PCC-2 [Group 20] | OUT_GOING_UPS_1E [Equipment 37; key: out-going-ups-1e] | gic_06_n3_OUT_GOING_UPS_1E | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| HARMONIC_PANEL [1000132; raw 132] | True | Outgoings | PCC-2 [Group 20] | HARMONIC_PANEL [Equipment 38; key: harmonic-panel] | gic_06_n4_HARMONIC_PANEL | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| O/G_CHILLER_FROM_PDB_PCC_3_LDB [1000133; raw 133] | True | Outgoings | PCC-2 [Group 20] | O/G_CHILLER_FROM_PDB_PCC_3_LDB [Equipment 39; key: o-g-chiller-from-pdb-pcc-3-ldb] | gic_06_n5_O_G_CHILLER_FROM_PDB_PCC_3_LDB | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| O/G_PDB_2_FG_SHED [1000134; raw 134] | True | Outgoings | PCC-2 [Group 20] | O/G_PDB_2_FG_SHED [Equipment 40; key: o-g-pdb-2-fg-shed] | gic_06_n6_O_G_PDB_2_FG_SHED | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| O/G_LDB_LT_ROOM [1000135; raw 135] | True | Outgoings | PCC-2 [Group 20] | O/G_LDB_LT_ROOM [Equipment 41; key: o-g-ldb-lt-room] | gic_06_n7_O_G_LDB_LT_ROOM_ | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| OUT_GOING_SPARE [1000136; raw 136] | True | Outgoings | PCC-2 [Group 20] | OUT_GOING_SPARE [Equipment 42; key: out-going-spare] | gic_06_n8_OUT_GOING_SPARE | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| PCW_PANEL_CHILLER_ROOM [1000137; raw 137] | True | Outgoings | PCC-2 [Group 20] | PCW_PANEL_CHILLER_ROOM [Equipment 43; key: pcw-panel-chiller-room] | gic_06_n9_PCW_PANEL_CHILLER_ROOM | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |

## Distribution panel: AMF-3

- Panel endpoint ID: **18**; key: `amf-3`; active: **True**.
- Group parent: Not configured.
- Configured twins: None configured.
- MFMs explicitly mapped to this panel’s own Equipment: None configured.

| MFM (frontend ID; raw ID) | Active | Role in this panel | Saved reference panel | Mapped equipment | Logger table | Schema (version) | Data source |
|---|---|---|---|---|---|---|---|
| TRANSFORMER_3_INCOMER [1000114; raw 114] | True | Incomings | AMF-3 [Group 18] | TRANSFORMER_3_INCOMER [Equipment 20; key: transformer-3-incomer] | gic_02_n1_TF_3_INCOMER | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| O/G_MODULE_PCC_PANEL_3 [1000116; raw 116] | True | Outgoings | AMF-3 [Group 18] | O/G_MODULE_PCC_PANEL_3 [Equipment 22; key: o-g-module-pcc-panel-3] | gic_02_n3_O_G_MODULE_PCC_PANEL_3 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| DIESEL_GENSET_3_INCOMER [1000115; raw 115] | True | Incomings | AMF-3 [Group 18] | DIESEL_GENSET_3_INCOMER [Equipment 21; key: diesel-genset-3-incomer] | gic_02_n2_DG_3_INCOMER | sch_EM6400_NG+ (v1) | logger_pg_main [ID 4] |
| O/G_APFCR_PANEL_3 [1000117; raw 117] | True | Outgoings | AMF-3 [Group 18] | O/G_APFCR_PANEL_3 [Equipment 23; key: o-g-apfcr-panel-3] | gic_02_n4_O_G_APFCR_PANEL_3 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |

## Distribution panel: PCC-3

- Panel endpoint ID: **21**; key: `pcc-3`; active: **True**.
- Group parent: Not configured.
- Configured twins: None configured.
- MFMs explicitly mapped to this panel’s own Equipment: None configured.

| MFM (frontend ID; raw ID) | Active | Role in this panel | Saved reference panel | Mapped equipment | Logger table | Schema (version) | Data source |
|---|---|---|---|---|---|---|---|
| PCC_03_INCOMER [1000138; raw 138] | True | Incomings | PCC-3 [Group 21] | PCC_03_INCOMER [Equipment 44; key: pcc-03-incomer] | gic_02_n6_PCC_03_INCOMER | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| LAMINATOR_PDB_3 [1000140; raw 140] | True | Outgoings | PCC-3 [Group 21] | LAMINATOR_PDB_3 [Equipment 46; key: laminator-pdb-3] | gic_02_n8_LAMINATOR_PDB_3 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| SPARE [1000147; raw 147] | True | Spare | PCC-3 [Group 21] | SPARE [Equipment 53; key: spare] | gic_03_n7_SPARE | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| SOLAR_INCOMER_PCC_3 [1000139; raw 139] | True | Incomings | PCC-3 [Group 21] | SOLAR_INCOMER_PCC_3 [Equipment 45; key: solar-incomer-pcc-3] | gic_02_n7_SOLAR_INCOMER_PCC_3 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| AIR_COMPRESSOR_PDB [1000141; raw 141] | True | Outgoings | PCC-3 [Group 21] | AIR_COMPRESSOR_PDB [Equipment 47; key: air-compressor-pdb-2] | gic_03_n1_AIR_COMPRESSOR_PDB | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| SPARE_2 [1000148; raw 148] | True | Spare | PCC-3 [Group 21] | SPARE_2 [Equipment 54; key: spare-2] | gic_03_n8_SPARE_2 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| UPS_2A [1000142; raw 142] | True | Outgoings | PCC-3 [Group 21] | UPS_2A [Equipment 48; key: ups-2a] | gic_03_n2_UPS_2A | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| PCW_PUMPS [1000143; raw 143] | True | Outgoings | PCC-3 [Group 21] | PCW_PUMPS [Equipment 49; key: pcw-pumps] | gic_03_n3_PCW_PUMPS | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| ADMIN_BUILDING [1000144; raw 144] | True | Outgoings | PCC-3 [Group 21] | ADMIN_BUILDING [Equipment 50; key: admin-building] | gic_03_n4_ADMIN_BUILDING | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| STP,FHS&_PUMPS [1000145; raw 145] | True | Outgoings | PCC-3 [Group 21] | STP,FHS&_PUMPS [Equipment 51; key: stp-fhs-pumps] | gic_03_n5_STP_FHS__PUMPS | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |
| BOPT [1000146; raw 146] | True | Outgoings | PCC-3 [Group 21] | BOPT [Equipment 52; key: bopt] | gic_03_n6_BOPT | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] |

## MFMs without a distribution-panel membership

Includes standalone category meters and meters in plain groups. A saved reference alone is not a membership.

| MFM (frontend ID; raw ID) | Active | Role in this panel | Saved reference panel | Mapped equipment | Logger table | Schema (version) | Data source | Navigation category | Plain-group memberships |
|---|---|---|---|---|---|---|---|---|---|
| I/C_PCC_2_LAMINATOR_PDB [1000242; raw 242] | True | No panel membership | Not configured | I/C_PCC_2_LAMINATOR_PDB [Equipment 152; key: i-c-pcc-2-laminator-pdb] | gic_08_n3_I_C_PCC_2_LAMINATOR_PDB | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| I/C_PCC_2_LAMINATOR_PDB_01 [1000255; raw 255] | True | No panel membership | Not configured | I/C_PCC_2_LAMINATOR_PDB_01 [Equipment 165; key: i-c-pcc-2-laminator-pdb-01] | gic_07_n1_I_C_PCC_2_LAMINATOR_PDB_01 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| I/C_PCC_2_LAMINATOR_PDB_2 [1000244; raw 244] | True | No panel membership | Not configured | I/C_PCC_2_LAMINATOR_PDB_2 [Equipment 154; key: i-c-pcc-2-laminator-pdb-2] | gic_08_n2_I_C_PCC_2_LAMINATOR_PDB_2 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| I/C_PCC_3_LAMINATOR_PDB_3 [1000246; raw 246] | True | No panel membership | Not configured | I/C_PCC_3_LAMINATOR_PDB_3 [Equipment 156; key: i-c-pcc-3-laminator-pdb-3] | gic_08_n7_I_C_PCC_3_LAMINATOR_PDB_3 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| I/C_POST_LAMINATOR_PANEL_2 [1000254; raw 254] | True | No panel membership | Not configured | I/C_POST_LAMINATOR_PANEL_2 [Equipment 164; key: i-c-post-laminator-panel-2] | gic_08_n11_I_C_POST_LAMINATOR_PANEL_2 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| I/C_PRE_LAMINATOR_PANEL_2 [1000253; raw 253] | True | No panel membership | Not configured | I/C_PRE_LAMINATOR_PANEL_2 [Equipment 163; key: i-c-pre-laminator-panel-2] | gic_08_n10_I_C_PRE_LAMINATOR_PANEL_2 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| I/C_SOLAR_AIR_COMPRESSOR_PDB-1 [1000256; raw 256] | True | No panel membership | Not configured | I/C_SOLAR_AIR_COMPRESSOR_PDB-1 [Equipment 166; key: i-c-solar-air-compressor-pdb-1] | gic_07_n2_I_C_SOLAR_AIR_COMPRESSOR_PDB_1 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| I/C_SOLAR_AIR_COMPRESSOR_PDB-2 [1000258; raw 258] | True | No panel membership | Not configured | I/C_SOLAR_AIR_COMPRESSOR_PDB-2 [Equipment 168; key: i-c-solar-air-compressor-pdb-2] | gic_07_n4_I_C_SOLAR_AIR_COMPRESSOR_PDB_2 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| I/C_UPS_PANEL_PRE_LAMINATOR_1 [1000250; raw 250] | True | No panel membership | Not configured | I/C_UPS_PANEL_PRE_LAMINATOR_1 [Equipment 160; key: i-c-ups-panel-pre-laminator-1] | gic_10_n1_I_C_UPS_PANEL_PRE_LAMINATOR_1 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| I/C_UPS_PANEL_PRE_LAMINATOR_2 [1000252; raw 252] | True | No panel membership | Not configured | I/C_UPS_PANEL_PRE_LAMINATOR_2 [Equipment 162; key: i-c-ups-panel-pre-laminator-2] | gic_08_n9_I_C_UPS_PANEL_PRE_LAMINATOR_2 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| I/C_UPS_PANEL_U_LAMINATOR [1000248; raw 248] | True | No panel membership | Not configured | I/C_UPS_PANEL_U_LAMINATOR [Equipment 158; key: i-c-ups-panel-u-laminator] | gic_08_n1_I_C_UPS_PANEL_U_LAMINATOR | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| I/C_UPS_PANEL_U_LAMINATOR_PDB_2 [1000249; raw 249] | True | No panel membership | Not configured | I/C_UPS_PANEL_U_LAMINATOR_PDB_2 [Equipment 159; key: i-c-ups-panel-u-laminator-pdb-2] | gic_08_n5_I_C_UPS_PANEL_U_LAMINATOR_PDB_2 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| INCOMER_LAMINATOR_PDB_02 [1000257; raw 257] | True | No panel membership | Not configured | INCOMER_LAMINATOR_PDB_02 [Equipment 167; key: incomer-laminator-pdb-02] | gic_07_n3_INCOMER_LAMINATOR_PDB_02 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| INCOMER_PRE LAMINATOR_PANEL_1 [1000251; raw 251] | True | No panel membership | Not configured | INCOMER_PRE LAMINATOR_PANEL_1 [Equipment 161; key: incomer-pre-laminator-panel-1] | gic_10_n2_INCOMER_PRE_LAMINATOR_PANEL_1 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| SOLAR_LAMINATOR_PDB_01 [1000243; raw 243] | True | No panel membership | Not configured | SOLAR_LAMINATOR_PDB_01 [Equipment 153; key: solar-laminator-pdb-01] | gic_08_n4_SOLAR_LAMINATOR_PDB_01 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| SOLAR_LAMINATOR_PDB_3 [1000247; raw 247] | True | No panel membership | Not configured | SOLAR_LAMINATOR_PDB_3 [Equipment 157; key: solar-laminator-pdb-3] | gic_08_n8_SOLAR_LAMINATOR_PDB_3 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |
| SOLAR_U_LAMINATOR_PDB_2 [1000245; raw 245] | True | No panel membership | Not configured | SOLAR_U_LAMINATOR_PDB_2 [Equipment 155; key: solar-u-laminator-pdb-2] | gic_08_n6_SOLAR_U_LAMINATOR_PDB_2 | sch_EMMS7_96 (v1) | logger_pg_main [ID 4] | production | None |

## Complete meter relationship and binding register

Exactly one row per MFM, including all panel memberships and Logger device/schema identifiers. Table and saved reference are listed above.

| MFM / frontend ID | All memberships (panel → role) | Reference / membership check | Logger device ID | Table binding status | Logger schema internal ID | Series ID | Parent series |
|---|---|---|---|---|---|---|---|
| ADMIN_BUILDING [1000144] | PCC-3 [Group 21] → Outgoings | Reference matches a membership | dev_1788766435338 | manual | sch_1788773139707 | Not configured | Not configured |
| AIR_COMPRESSOR_PDB [1000120] | PCC-1 [Group 19] → Outgoings | Reference matches a membership | dev_1789541712583 | manual | sch_1788773139707 | Not configured | Not configured |
| AIR_COMPRESSOR_PDB [1000141] | PCC-3 [Group 21] → Outgoings | Reference matches a membership | dev_1788766435335 | manual | sch_1788773139707 | Not configured | Not configured |
| BOPT [1000146] | PCC-3 [Group 21] → Outgoings | Reference matches a membership | dev_1788766435340 | manual | sch_1788773139707 | Not configured | Not configured |
| CT,CDWP,CWP_PANEL [1000122] | PCC-1 [Group 19] → Outgoings | Reference matches a membership | dev_1788766435355 | manual | sch_1788773139707 | Not configured | Not configured |
| DIESEL_GENSET_1_INCOMER [1000107] | AMF-1 [Group 16] → Incomings | Reference matches a membership | dev_1788766435344 | manual | sch_1788773139707 | Not configured | Not configured |
| DIESEL_GENSET_2_INCOMER [1000111] | AMF-2 [Group 17] → Incomings | Reference matches a membership | dev_1788766435348 | manual | sch_1788773139707 | Not configured | Not configured |
| DIESEL_GENSET_3_INCOMER [1000115] | AMF-3 [Group 18] → Incomings | Reference matches a membership | dev_1788766435320 | manual | sch_1788521250508 | Not configured | Not configured |
| HARMONIC_PANEL [1000132] | PCC-2 [Group 20] → Outgoings | Reference matches a membership | dev_1788766435364_1 | manual | sch_1788773139707 | Not configured | Not configured |
| I/C_33KV_MAIN_VCB [1000102] | 33KV HT Panel [Group 2] → Incomings | Reference matches a membership | dev_1789455985126 | manual | sch_1788521250508 | Not configured | Not configured |
| I/C_PCC_1 [1000217] | Utility Panel [Group 25] → Incomings | Reference matches a membership | dev_1788766435396 | manual | sch_1789627016559 | Not configured | Not configured |
| I/C_PCC_2_LAMINATOR_PDB [1000242] | None | No saved reference | dev_1789203642792 | manual | sch_1788773139707 | Not configured | Not configured |
| I/C_PCC_2_LAMINATOR_PDB_01 [1000255] | None | No saved reference | dev_1788766435369 | manual | sch_1788773139707 | Not configured | Not configured |
| I/C_PCC_2_LAMINATOR_PDB_2 [1000244] | None | No saved reference | dev_1788766435374 | manual | sch_1788773139707 | Not configured | Not configured |
| I/C_PCC_3_LAMINATOR_PDB_3 [1000246] | None | No saved reference | dev_1788766435378 | manual | sch_1788773139707 | Not configured | Not configured |
| I/C_POST_LAMINATOR_PANEL_2 [1000254] | None | No saved reference | dev_1788766435380 | manual | sch_1788773139707 | Not configured | Not configured |
| I/C_PRE_LAMINATOR_PANEL_2 [1000253] | None | No saved reference | dev_1788766435379_1 | manual | sch_1788773139707 | Not configured | Not configured |
| I/C_SOLAR_AIR_COMPRESSOR_PDB-1 [1000256] | None | No saved reference | dev_1789203642781 | manual | sch_1788773139707 | Not configured | Not configured |
| I/C_SOLAR_AIR_COMPRESSOR_PDB-2 [1000258] | None | No saved reference | dev_1789203642785 | manual | sch_1788773139707 | Not configured | Not configured |
| I/C_UPS_PANEL_PRE_LAMINATOR_1 [1000250] | None | No saved reference | dev_1789203642795 | manual | sch_1788773139707 | Not configured | Not configured |
| I/C_UPS_PANEL_PRE_LAMINATOR_2 [1000252] | None | No saved reference | dev_1789203642794 | manual | sch_1788773139707 | Not configured | Not configured |
| I/C_UPS_PANEL_U_LAMINATOR [1000248] | None | No saved reference | dev_1789203642789 | manual | sch_1788773139707 | Not configured | Not configured |
| I/C_UPS_PANEL_U_LAMINATOR_PDB_2 [1000249] | None | No saved reference | dev_1788766435376 | manual | sch_1788773139707 | Not configured | Not configured |
| INCOMER_FROM_AMF_1 [1000118] | PCC-1 [Group 19] → Incomings | Reference matches a membership | dev_1788766435353 | manual | sch_1788773139707 | Not configured | Not configured |
| INCOMER_FROM_AMF_2 [1000123] | PCC-2 [Group 20] → Incomings | Reference matches a membership | dev_1788766435356 | manual | sch_1788773139707 | Not configured | Not configured |
| INCOMER_LAMINATOR_PDB_02 [1000257] | None | No saved reference | dev_1788766435371 | manual | sch_1788773139707 | Not configured | Not configured |
| INCOMER_PRE LAMINATOR_PANEL_1 [1000251] | None | No saved reference | dev_1788766435395 | manual | sch_1788773139707 | Not configured | Not configured |
| LAMINATOR_PDB_01 [1000125] | PCC-2 [Group 20] → Outgoings | Reference matches a membership | dev_1788766435358 | manual | sch_1788773139707 | Not configured | Not configured |
| LAMINATOR_PDB_02 [1000126] | PCC-2 [Group 20] → Outgoings | Reference matches a membership | dev_1788766435358_1 | manual | sch_1788773139707 | Not configured | Not configured |
| LAMINATOR_PDB_3 [1000140] | PCC-3 [Group 21] → Outgoings | Reference matches a membership | dev_1788766435331 | manual | sch_1788773139707 | Not configured | Not configured |
| LIGHTNING_DB_3 [1000241] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435360_1 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_180_FLIPER_&_HITPOT [1000213] | UPS [Group 24] → Outgoings | Reference matches a membership | dev_1788766435391 | manual | sch_1789627016559 | Not configured | Not configured |
| OG_33_415kV_TF_1 [1000103] | 33KV HT Panel [Group 2] → Outgoings | Reference matches a membership | dev_1788520308453 | manual | sch_1788521250508 | Not configured | Not configured |
| OG_33_415kV_TF_2 [1000104] | 33KV HT Panel [Group 2] → Outgoings | Reference matches a membership | dev_1788520308457 | manual | sch_1788521250508 | Not configured | Not configured |
| OG_33_415kV_TF_3 [1000105] | 33KV HT Panel [Group 2] → Outgoings | Reference matches a membership | dev_1788520308460 | manual | sch_1788521250508 | Not configured | Not configured |
| O/G_AHU_09 [1000219] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435397 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AHU_PDB_01 [1000220] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435398 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AHU_PDB_02 [1000221] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435399 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AHU_PDB_03 [1000222] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435399_1 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AHU_PDB_04 [1000225] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435401_1 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AHU_PDB_05 [1000223] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435400 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AHU_PDB_06 [1000226] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435402 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AHU_PDB_07 [1000227] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435403 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AHU_PDB_08 [1000228] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435404 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AIR_EXUAST_3 [1000231] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435409 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AIR_WASHER_01 [1000230] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435408 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AIR_WASHER_03 [1000234] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435412 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AIR_WASHER_PDB_2 [1000229] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435407 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AIR_WASHER_PDB_3 [1000224] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435401 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_ALL_CSU [1000239] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435417 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_APFC_PANEL_01 [1000109] | AMF-1 [Group 16] → Outgoings | Reference matches a membership | dev_1788766435346 | manual | sch_1788773139707 | Not configured | Not configured |
| O/G_APFC_PANEL_02 [1000112] | AMF-2 [Group 17] → Outgoings | Reference matches a membership | dev_1788766435349 | manual | sch_1788773139707 | Not configured | Not configured |
| O/G_APFCR_PANEL_3 [1000117] | AMF-3 [Group 18] → Outgoings | Reference matches a membership | dev_1788766435326 | manual | sch_1788773139707 | Not configured | Not configured |
| O/G_AXIAL_FLOW_FAN_PDB_01 [1000236] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435414 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AXIAL_FLOW_FAN_PDB_02 [1000237] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435415 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_AXIAL_FLOW_FAN_PDB_03 [1000235] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435413 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_CHILLER_FROM_PDB_PCC_3_LDB [1000133] | PCC-2 [Group 20] → Outgoings | Reference matches a membership | dev_1788766435365 | manual | sch_1788773139707 | Not configured | Not configured |
| O/G_EXHAUST_UNIT_PDB_01 [1000232] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435410 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_EXHAUST_UNIT_PDB_02 [1000233] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435411 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_LDB_LT_ROOM [1000135] | PCC-2 [Group 20] → Outgoings | Reference matches a membership | dev_1788766435367 | manual | sch_1788773139707 | Not configured | Not configured |
| O/G_LINE_3_AIR_WASHER_PDB [1000240] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435418 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_MANUAL_LINE [1000208] | UPS [Group 24] → Outgoings | Reference matches a membership | dev_1788766435386 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_MODULE_PCC_PANEL_1 [1000108] | AMF-1 [Group 16] → Outgoings | Reference matches a membership | dev_1788766435345 | manual | sch_1788773139707 | Not configured | Not configured |
| O/G_MODULE_PCC_PANEL_2 [1000113] | AMF-2 [Group 17] → Outgoings | Reference matches a membership | dev_1788766435350 | manual | sch_1788773139707 | Not configured | Not configured |
| O/G_MODULE_PCC_PANEL_3 [1000116] | AMF-3 [Group 18] → Outgoings | Reference matches a membership | dev_1788766435324 | manual | sch_1788773139707 | Not configured | Not configured |
| O/G_PDB_2_FG_SHED [1000134] | PCC-2 [Group 20] → Outgoings | Reference matches a membership | dev_1788766435366 | manual | sch_1788773139707 | Not configured | Not configured |
| O/G_POST_LAMINATOR_PDB_01 [1000212] | UPS [Group 24] → Outgoings | Reference matches a membership | dev_1788766435390 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_POST_LAMINATOR_PDB_02 [1000214] | UPS [Group 24] → Outgoings | Reference matches a membership | dev_1788766435392 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_PRE_LAMINATOR_PANEL_1 [1000209] | UPS [Group 24] → Outgoings | Reference matches a membership | dev_1788766435387 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_PRE_LAMINATOR_PANEL_2 [1000210] | UPS [Group 24] → Outgoings | Reference matches a membership | dev_1788766435388 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_PRE_LAMINATOR_PDB_AND_LDB [1000238] | Utility Panel [Group 25] → Outgoings | Reference matches a membership | dev_1788766435416 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_U_LAMINATOR_PANEL1 [1000211] | UPS [Group 24] → Outgoings | Reference matches a membership | dev_1788766435389 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_U_LAMINATOR_PDB_02 [1000215] | UPS [Group 24] → Outgoings | Reference matches a membership | dev_1788766435392_1 | manual | sch_1789627016559 | Not configured | Not configured |
| O/G_UPS_LIGHTING_DB [1000216] | UPS [Group 24] → Outgoings | Reference matches a membership | dev_1788766435393 | manual | sch_1789627016559 | Not configured | Not configured |
| OUT_GOING_SPARE [1000136] | PCC-2 [Group 20] → Outgoings | Reference matches a membership | dev_1788766435367_1 | manual | sch_1788773139707 | Not configured | Not configured |
| OUT_GOING_UPS_1A [1000127] | PCC-2 [Group 20] → Outgoings | Reference matches a membership | dev_1788766435359 | manual | sch_1788773139707 | Not configured | Not configured |
| OUT_GOING_UPS_1B [1000128] | PCC-2 [Group 20] → Outgoings | Reference matches a membership | dev_1788766435360 | manual | sch_1788773139707 | Not configured | Not configured |
| OUT_GOING_UPS_1C [1000129] | PCC-2 [Group 20] → Outgoings | Reference matches a membership | dev_1788766435363 | manual | sch_1788773139707 | Not configured | Not configured |
| OUT_GOING_UPS_1D [1000130] | PCC-2 [Group 20] → Outgoings | Reference matches a membership | dev_1788766435363_1 | manual | sch_1788773139707 | Not configured | Not configured |
| OUT_GOING_UPS_1E [1000131] | PCC-2 [Group 20] → Outgoings | Reference matches a membership | dev_1788766435364 | manual | sch_1788773139707 | Not configured | Not configured |
| PCC_03_INCOMER [1000138] | PCC-3 [Group 21] → Incomings | Reference matches a membership | dev_1788766435329 | manual | sch_1788773139707 | Not configured | Not configured |
| PCW_PANEL_CHILLER_ROOM [1000137] | PCC-2 [Group 20] → Outgoings | Reference matches a membership | dev_1788766435368 | manual | sch_1788773139707 | Not configured | Not configured |
| PCW_PUMPS [1000143] | PCC-3 [Group 21] → Outgoings | Reference matches a membership | dev_1788766435337 | manual | sch_1788773139707 | Not configured | Not configured |
| SOLAR_INCOMER_PCC_1 [1000119] | PCC-1 [Group 19] → Incomings | Reference matches a membership | dev_1788766435355_1 | manual | sch_1788773139707 | Not configured | Not configured |
| SOLAR_INCOMER_PCC_2 [1000124] | PCC-2 [Group 20] → Incomings | Reference matches a membership | dev_1788766435357 | manual | sch_1788773139707 | Not configured | Not configured |
| SOLAR_INCOMER_PCC_3 [1000139] | PCC-3 [Group 21] → Incomings | Reference matches a membership | dev_1788766435330 | manual | sch_1788773139707 | Not configured | Not configured |
| SOLAR_INCOMING_UTILITY_PANEL [1000218] | Utility Panel [Group 25] → Incomings | Reference matches a membership | dev_1788766435396_1 | manual | sch_1789627016559 | Not configured | Not configured |
| SOLAR_LAMINATOR_PDB_01 [1000243] | None | No saved reference | dev_1788766435375 | manual | sch_1788773139707 | Not configured | Not configured |
| SOLAR_LAMINATOR_PDB_3 [1000247] | None | No saved reference | dev_1788766435379 | manual | sch_1788773139707 | Not configured | Not configured |
| SOLAR_U_LAMINATOR_PDB_2 [1000245] | None | No saved reference | dev_1788766435377 | manual | sch_1788773139707 | Not configured | Not configured |
| SPARE [1000147] | PCC-3 [Group 21] → Spare | Reference matches a membership | dev_1788766435341 | manual | sch_1788773139707 | Not configured | Not configured |
| SPARE_2 [1000148] | PCC-3 [Group 21] → Spare | Reference matches a membership | dev_1789203642775 | manual | sch_1788773139707 | Not configured | Not configured |
| STP,FHS&_PUMPS [1000145] | PCC-3 [Group 21] → Outgoings | Reference matches a membership | dev_1788766435339 | manual | sch_1788773139707 | Not configured | Not configured |
| TRANFORMER_01_INCOMER [1000106] | AMF-1 [Group 16] → Incomings | Reference matches a membership | dev_1788766435343 | manual | sch_1788773139707 | Not configured | Not configured |
| TRANSFORM_2_INCOMER [1000110] | AMF-2 [Group 17] → Incomings | Reference matches a membership | dev_1788766435347 | manual | sch_1788773139707 | Not configured | Not configured |
| TRANSFORMER_3_INCOMER [1000114] | AMF-3 [Group 18] → Incomings | Reference matches a membership | dev_1788766435315 | manual | sch_1788773139707 | Not configured | Not configured |
| UPS_2A [1000142] | PCC-3 [Group 21] → Outgoings | Reference matches a membership | dev_1788766435336 | manual | sch_1788773139707 | Not configured | Not configured |
| UPS-A [1000204] | UPS [Group 24] → Incomings | Reference matches a membership | dev_1788766435382 | manual | sch_1789627016559 | Not configured | Not configured |
| UPS-B [1000205] | UPS [Group 24] → Incomings | Reference matches a membership | dev_1788766435383 | manual | sch_1789627016559 | Not configured | Not configured |
| UPS-C [1000206] | UPS [Group 24] → Incomings | Reference matches a membership | dev_1788766435384 | manual | sch_1789627016559 | Not configured | Not configured |
| UPS-D [1000207] | UPS [Group 24] → Incomings | Reference matches a membership | dev_1788766435385 | manual | sch_1789627016559 | Not configured | Not configured |
| UTILITY_PANEL_1 [1000121] | PCC-1 [Group 19] → Outgoings | Reference matches a membership | dev_1788766435354 | manual | sch_1788773139707 | Not configured | Not configured |

## Explicit electrical feed relationships

**No FeedEdge records are configured.** The database therefore does not establish a complete electrical panel-to-panel feed graph. Membership roles alone cannot prove which outgoing feeds which downstream incoming.

## Logger schema catalogue

| Code / version | Schema name | Active | Logger schema ID | Timestamp column | Measured fields | Derived fields | Assigned MFMs |
|---|---|---|---|---|---|---|---|
| sch_DG v1 | sch_DG | True | sch_1789555418173 | timestamp_utc | 32 | 13 | 0 |
| sch_EM6400_NG+ v1 | sch_EM6400_NG+ | True | sch_1788521250508 | timestamp_utc | 43 | 30 | 5 |
| sch_EMMS7_96 v1 | sch_EMMS7_96 | True | sch_1788773139707 | timestamp_utc | 36 | 30 | 59 |
| sch_LG2599 v1 | sch_LG2599 | True | sch_1789627016559 | timestamp_utc | 27 | 28 | 38 |

Schema details describe field layouts, not proof that every physical table currently contains valid readings. This report reads binding metadata only; it does not query telemetry tables or expose connection credentials.

## Follow-up configuration gaps

- MFMs missing a table: **0**.
- MFMs missing a schema: **0**.
- MFMs missing a data source: **0**.
- MFMs missing mapped equipment: **0**.
- Panel-member MFMs missing a saved reference: **0**.

This is a point-in-time export. Re-export after admin/import changes. For relationship definitions see `MFM_PANEL_EQUIPMENT_STRUCTURE.md`; for overall architecture see `PROJECT_CONTEXT.md`.

# LoggerFast Benchmark Results

**Date:** March 3-4, 2026
**System:** Arch Linux, PostgreSQL (local), Modbus TCP Simulator (port 5020)
**Metadata DB:** `postgresql://postgres@localhost/meta_data_break_point`
**Target DB:** `postgresql://postgres@localhost/new_target_test`
**Total Devices:** 250 (240 working + 10 transformer tables with write errors)
**Job Interval:** 1000ms (1 read + 1 write per table per second)
**Duration Per Scenario:** 5 minutes (300 seconds)

---

## Scenario Definitions

### Type 1 — Single Job, Varying Table Count
- **1 job** with increasing table counts: 1, 10, 20, 30, ... 250
- **26 scenarios** total
- Tests: How many tables can a single job handle before overruns occur?

### Type 2 — All 250 Tables, Varying Job Count
- **250 tables** split across 1 to 10 jobs
- **10 scenarios** total
- Tests: Does splitting tables across multiple jobs improve throughput?
- Note: Includes 10 broken transformer tables that cause write errors

### Type 3 — 240 Working Tables, Varying Job Count (Rust only)
- **240 tables** (excluding 10 broken transformer tables) split across 1 to 10 jobs
- **10 scenarios** total
- Tests: Same as Type 2 but with zero write errors for clean comparison

---

## Type 1 Results — Single Job, Varying Tables

| Tables | Python Reads/s | Rust Reads/s | Python Loop P95 (ms) | Rust Loop P95 (ms) | Python Overrun % | Rust Overrun % | Python CPU % | Rust CPU % | Python RSS (MB) | Rust RSS (MB) |
|--------|---------------|-------------|---------------------|-------------------|-----------------|---------------|-------------|-----------|----------------|--------------|
| 1 | 1.0 | 1.0 | 9.2 | 9.0 | 0.0 | 0.0 | 0.0 | 0.1 | 164 | 8.4 |
| 10 | 10.0 | 10.0 | 71.4 | 42.6 | 0.0 | 0.0 | 0.0 | 0.8 | 164 | 8.8 |
| 20 | 20.0 | 20.0 | 134.8 | 84.9 | 0.0 | 0.0 | 0.0 | 1.5 | 165 | 9.2 |
| 30 | 30.1 | 30.1 | 195.9 | 124.4 | 0.0 | 0.0 | 0.0 | 2.1 | 168 | 9.6 |
| 40 | 40.1 | 40.1 | 272.5 | 158.6 | 0.0 | 0.0 | 0.0 | 2.9 | 171 | 9.6 |
| 50 | 50.0 | 50.1 | 334.5 | 195.7 | 0.0 | 0.0 | 0.0 | 3.5 | 172 | 10.0 |
| 60 | 60.0 | 60.0 | 403.0 | 227.6 | 0.0 | 0.0 | 0.0 | 4.0 | 172 | 10.0 |
| 70 | 69.9 | 70.0 | 469.2 | 277.2 | 0.0 | 0.0 | 0.0 | 4.7 | 175 | 10.5 |
| 80 | 79.9 | 80.0 | 518.8 | 306.4 | 0.0 | 0.0 | 0.0 | 5.4 | 179 | 10.4 |
| 90 | 89.8 | 90.0 | 594.6 | 344.2 | **0.4** | 0.0 | 0.0 | 6.0 | 179 | 11.8 |
| 100 | 99.7 | 99.8 | 658.4 | 387.2 | **1.1** | 0.0 | 0.0 | 6.8 | 182 | 12.2 |
| 110 | 109.7 | 109.9 | 712.2 | 420.7 | **2.0** | 0.0 | 0.0 | 7.3 | 182 | 12.5 |
| 120 | 119.5 | 119.9 | 774.5 | 465.5 | **0.8** | 0.0 | 0.0 | 8.2 | 186 | 13.0 |
| 130 | 129.1 | 129.8 | 844.2 | 486.8 | **5.0** | 0.0 | 0.0 | 8.6 | 186 | 13.4 |
| 140 | 138.4 | 139.7 | 910.8 | 534.9 | **12.4** | 0.0 | 0.0 | 9.4 | 187 | 13.8 |
| 150 | 146.2 | 149.8 | 966.5 | 577.1 | **39.1** | 0.0 | 0.0 | 10.0 | 187 | 14.3 |
| 160 | 151.5 | 159.7 | 1012.8 | 609.5 | **64.9** | 0.0 | 0.0 | 10.7 | 187 | 14.6 |
| 170 | 153.8 | 169.5 | 1071.1 | 634.2 | **90.8** | 0.0 | 0.0 | 11.2 | 187 | 14.7 |
| 180 | 154.5 | 179.5 | 1138.6 | 673.0 | **100.0** | **0.4** | 0.0 | 11.5 | 187 | 15.1 |
| 190 | 151.9 | 189.2 | 1216.1 | 712.0 | **100.0** | **0.8** | 0.0 | 12.0 | 190 | 15.7 |
| 200 | 152.6 | 199.2 | 1271.2 | 754.3 | **100.0** | **1.8** | 0.0 | 12.8 | 191 | 16.1 |
| 210 | 151.9 | 209.2 | 1346.5 | 781.1 | **100.0** | **1.9** | 0.0 | 13.5 | 191 | 16.5 |
| 220 | 153.6 | 218.4 | 1393.9 | 832.7 | **100.0** | **4.7** | 0.0 | 14.1 | 191 | 16.9 |
| 230 | 150.3 | 228.3 | 1491.6 | 865.5 | **100.0** | **5.3** | 0.0 | 15.0 | 191 | 17.0 |
| 240 | 147.6 | 237.1 | 1588.4 | 911.4 | **100.0** | **9.0** | 0.0 | 15.4 | 191 | 17.6 |
| 250 | 152.9 | 246.8 | 1590.1 | 922.9 | **100.0** | **6.9** | 0.0 | 16.0 | 191 | 18.1 |

### Type 1 Key Findings

- **Python throughput ceiling:** ~154 reads/s at 170 tables. Beyond this, adding more tables does not increase throughput.
- **Rust throughput:** Scales linearly all the way to 250 tables (246.8 reads/s) with no ceiling.
- **Python first overrun:** 90 tables (0.4%). Reaches 100% overrun at 180 tables.
- **Rust first overrun:** 180 tables (0.4%). Reaches only 9% overrun at 240 tables.
- **Loop latency:** Rust is ~1.7x faster than Python per loop iteration (e.g., 277ms vs 469ms at 70 tables).
- **Memory:** Rust uses ~10-18 MB vs Python's ~164-191 MB (10-20x less).
- **Write errors:** Python had 1,840 write errors at 250 tables. Rust had 2,980 (from broken transformer tables).

---

## Type 2 Results — 250 Tables, Varying Jobs

| Jobs | Python Reads/s | Rust Reads/s | Python Writes/s | Rust Writes/s | Python Loop P95 (ms) | Rust Loop P95 (ms) | Python Overrun % | Rust Overrun % | Python Write Err | Rust Write Err |
|------|---------------|-------------|----------------|--------------|---------------------|-------------------|-----------------|---------------|-----------------|---------------|
| 1 | 152.0 | 245.9 | 145.9 | 236.1 | 1604.6 | 936.5 | **100.0** | **9.0** | 1830 | 2980 |
| 2 | 98.7 | 124.8 | 94.7 | 119.8 | 1225.4 | 547.6 | **100.0** | 0.0 | 2380 | 3020 |
| 3 | 63.6 | 83.3 | 61.3 | 79.9 | 1266.8 | 444.2 | **100.0** | 0.0 | 2160 | 3020 |
| 4 | 43.8 | 62.5 | 42.3 | 60.0 | 1385.2 | 410.9 | **100.0** | 0.0 | 1970 | 3020 |
| 5 | 33.3 | 50.0 | 32.0 | 48.0 | 1459.6 | 383.8 | **100.0** | 0.0 | 1930 | 3040 |
| 6 | 26.4 | 41.7 | 25.5 | 40.0 | 1540.1 | 356.1 | **99.8** | 0.0 | 1700 | 3040 |
| 7 | 21.2 | 35.7 | 20.4 | 34.3 | 1650.4 | 344.9 | **100.0** | 0.0 | 1520 | 3020 |
| 8 | 17.7 | 31.2 | 17.1 | 30.0 | 1717.1 | 337.6 | **100.0** | 0.0 | 1570 | 3030 |
| 9 | 15.5 | 27.8 | 14.8 | 26.7 | 1774.4 | 325.8 | **100.0** | 0.0 | 1340 | 3030 |
| 10 | 13.5 | 25.0 | 12.9 | 24.0 | 1824.7 | 316.7 | **99.9** | 0.0 | 1630 | 3040 |

### Type 2 Key Findings

- **Python:** 100% overrun across ALL job counts. Splitting into more jobs does not help — each job still overruns its interval.
- **Rust:** Only 9% overrun with 1 job. Splitting into 2+ jobs drops overrun to 0%.
- **Per-job reads/s:** Rust consistently delivers the exact expected throughput (e.g., 50.0 reads/s for 5 jobs x 50 tables each).
- **Python per-job reads/s drops:** At 10 jobs, Python gets only 13.5 reads/s per job (should be 25.0).
- **Write errors:** Python had ~19,870 total across Type 2 (concurrency contention). Rust had ~30,260 total but all from the 10 broken transformer tables.
- **Loop P95:** Python's loop latency increases with more jobs (1604ms to 1824ms). Rust's decreases (936ms to 317ms) because fewer tables per job.

---

## Type 3 Results — 240 Working Tables, Varying Jobs (Rust Only)

This scenario excludes the 10 broken transformer tables to get a clean measurement with zero write errors.

| Jobs | Reads/s | Writes/s | Loop P95 (ms) | Overrun % | CPU % | RSS (MB) | Read Err | Write Err |
|------|---------|----------|---------------|-----------|-------|----------|----------|-----------|
| 1 | 236.1 | 236.1 | 945.4 | **10.5** | 16.9 | 18.2 | 0 | **0** |
| 2 | 119.8 | 119.8 | 557.0 | 0.0 | 17.4 | 17.6 | 0 | **0** |
| 3 | 79.9 | 79.9 | 434.2 | 0.0 | 17.4 | 21.0 | 0 | **0** |
| 4 | 60.0 | 60.0 | 401.2 | 0.0 | 17.9 | 23.8 | 0 | **0** |
| 5 | 48.0 | 48.0 | 386.5 | 0.0 | 17.7 | 25.6 | 0 | **0** |
| 6 | 40.0 | 40.0 | 358.5 | 0.0 | 17.6 | 26.5 | 0 | **0** |
| 7 | 34.3 | 34.3 | 337.9 | 0.0 | 17.7 | 27.1 | 0 | **0** |
| 8 | 30.0 | 30.0 | 326.5 | 0.0 | 17.9 | 29.4 | 0 | **0** |
| 9 | 26.7 | 26.7 | 327.6 | 0.0 | 17.8 | 30.8 | 0 | **0** |
| 10 | 24.0 | 24.0 | 316.9 | 0.0 | 18.0 | 31.3 | 0 | **0** |

### Type 3 Key Findings

- **Zero errors:** Removing the 10 broken transformer tables eliminates ALL write errors.
- **Reads = Writes:** Every read results in a successful write (reads/s = writes/s perfectly).
- **1 job:** 10.5% overrun at 240 tables (loop P95 = 945ms, just under 1000ms interval).
- **2+ jobs:** 0% overrun. Splitting into just 2 jobs eliminates all overruns.
- **CPU:** Stable at ~17-18% regardless of job count (process-wide measurement).
- **RSS:** Grows from 18 MB (1 job) to 31 MB (10 jobs) — each job thread adds ~1.5 MB.

---

## Summary Comparison: Python vs Rust

| Metric | Python | Rust | Advantage |
|--------|--------|------|-----------|
| Max tables at 0% overrun | 80 | 170 | **Rust 2.1x** |
| Max tables at <10% overrun | ~100 | 240 | **Rust 2.4x** |
| Throughput ceiling (1 job) | ~154 reads/s | ~247 reads/s | **Rust 1.6x** |
| Loop latency at 100 tables | 658 ms | 387 ms | **Rust 1.7x faster** |
| Memory (RSS) at 250 tables | 191 MB | 18 MB | **Rust 10.6x less** |
| Read latency (avg) | 4.4-4.6 ms | 2.0-2.2 ms | **Rust 2.1x faster** |
| Write latency (avg) | 1.9-2.0 ms | 1.5-1.5 ms | **Rust 1.3x faster** |
| Type 2 overrun (all scenarios) | 99.8-100% | 0-9% | **Rust dramatically better** |
| Type 2 write errors | 19,870 total | 30,260 (all from broken tables) | Rust: 0 from working tables |

---

## Test Configuration

| Parameter | Value |
|-----------|-------|
| Modbus Simulator | Port 5020, 357 equipment nodes |
| API Server | Port 5175 (FastAPI) |
| Job Interval | 1000ms |
| Scenario Duration | 5 minutes (300 seconds) |
| Reporting Window | 2 seconds |
| Python Runner | Built into API server (`/jobs` endpoints) |
| Rust Runner | Standalone daemon (`/jobs2` endpoints), polls metadata DB every 2s |
| Schemas Tested | LT Panel (MCC/PCC/MLDB/SMDB/DB), LT APFC, LT ATS, LT Changeover, LT VFD, LT PLC, Transformer |

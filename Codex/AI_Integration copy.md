# AI Integration — NousResearch Hermes Agent for LoggerFast

**Author:** Rohith
**Date:** 2026-04-09
**Updated:** 2026-04-10
**Status:** Architecture Finalized — Ready for Engineering

---

## Context

Neuact Logger is our industrial data logging product. Today, configuring a site is **entirely manual** — an engineer physically adds each device, defines schemas, maps every Modbus register by hand, and sets up logging jobs. For a site like Premier Energies (297 devices, 10,572 column mappings), this takes days of tedious work and is error-prone.

**The goal is to add an AI-assisted configuration mode powered by the NousResearch Hermes agent framework.** The engineer opens a chat, describes their site, and the Hermes agent configures everything through the existing LoggerFast pipeline — creating gateways, devices, schemas, tables, mappings, and jobs on their behalf. The engineer reviews and approves before anything goes live.

The existing manual pipeline remains completely untouched. Hermes is an optional mode.

---

## Existing System

- **Backend:** FastAPI sidecar (Python) at `agent/plc_agent/`
- **Frontend:** React + Tauri desktop app at `apps/desktop/`
- **Protocols:** Modbus TCP (port 502), OPC UA
- **Core entities:** Gateways -> Devices -> Schemas -> Tables -> Mappings -> Jobs
- **In-memory store:** `agent/plc_agent/api/store.py` — holds all runtime state
- **API docs:** `API_DOCUMENTATION.md` (38KB, complete endpoint reference)
- **Site metadata example:** `METADATA_DOCUMENTATION.md` (297 devices, 13 schemas, 27 gateways)
- **Bulk import example:** `bulk_import_297_devices.json`

Key files:
- `agent/plc_agent/api/routers/devices.py` — device CRUD, connection testing
- `agent/plc_agent/api/routers/mappings.py` — register-to-field mapping
- `agent/plc_agent/api/routers/schemas.py` — schema (template) management
- `agent/plc_agent/api/routers/jobs.py` — job lifecycle
- `agent/plc_agent/api/routers/bulk_import.py` — bulk device/schema/mapping import
- `Codex/requirements.md` — full functional spec of the existing system

---

# Part 1: Domain Knowledge Reference

This section is reference material for Hermes — the MFM knowledge base structure, validation rules, and protocol specifics that Hermes needs to reason about when configuring a site.

---

## MFM Knowledge Base

### Structure Per Model

| Field | Example |
|-------|---------|
| Manufacturer | Schneider Electric |
| Model | PM5110 |
| Protocol | Modbus TCP / RTU |
| Register map | Address 0-1: Voltage L1-N (float32, V), Address 2-3: Voltage L2-N (float32, V), ... |
| Total register count | 78 registers (39 params x 2 regs each) |
| Default unit ID behavior | Sequential from 1 |
| Identification registers | Some MFMs have model ID at a known address (e.g., register 64999) |
| Byte order | Big-endian / Little-endian / Mid-endian |
| Typical value ranges | Voltage: 180-480V, Current: 0-6000A, PF: -1 to 1, Freq: 49-51Hz |
| Known quirks | e.g., "returns 0xFFFF for unsupported registers", "energy counters reset at 999999" |

### Manufacturers to Cover (Priority Order)

1. **Schneider Electric** — PM5100/5300/5500/8000 series, EM6400, Conzerv
2. **ABB** — M2M series, B21/B23/B24, EQ meters
3. **Siemens** — PAC2200/3200/4200, SENTRON
4. **L&T** — WM series (very common in Indian industrial sites)
5. **Selec** — MFM series (MFM376, MFM384, etc.)
6. **Rishabh** — Rish Master series
7. **Elmeasure** — Alpha series
8. **Secure Meters** — Elite series
9. **HPL** — Energy meters
10. **Genus** — Power meters

### Storage

- Versioned JSON files in `agent/plc_agent/data/mfm_kb/` (source of truth, diffable in PRs)
- Loaded into SQLite at startup for fast retrieval
- Hermes accesses via `lookup_mfm_model(model)` tool — only the relevant model is injected into context on demand
- Updatable independently of the app — ship updates with releases

### Document-Driven KB Build Pipeline

The MFM KB is **not hand-authored**. Hermes builds it by ingesting manufacturer communication guide PDFs. The source documents are retained so Hermes can always reference the original when something is ambiguous.

#### Document Storage

```
agent/plc_agent/data/mfm_docs/           # Source PDFs (gitignored, local to deployment)
  schneider_pm5110_modbus_guide.pdf
  schneider_pm5300_modbus_guide.pdf
  abb_b24_communication_manual.pdf
  lt_wm330_modbus_reference.pdf
  selec_mfm376_comm_protocol.pdf
  ...

agent/plc_agent/data/mfm_kb/             # Extracted structured KB (versioned in repo)
  schneider_pm5110.json
  schneider_pm5300.json
  abb_b24.json
  ...
  index.json                              # Manifest: model → file, version, source_doc, extraction_date
```

#### Ingestion Flow

1. **Upload:** Engineer uploads a manufacturer communication guide PDF via `POST /ai/kb/upload` or drops it in the session chat ("here's the PM5110 modbus guide")
2. **Extract:** Hermes reads the PDF using GLM-OCR for text and table extraction:
   - `read_document(path, pages)` — text extraction via GLM-OCR (handles scanned pages, complex tables, multi-column layouts)
   - `read_document_page_image(path, page)` — render a page as image and run through GLM-OCR for structured table recognition (register map tables are the primary target)
3. **Parse:** Hermes identifies register map tables in the document and extracts structured data:
   - Register address, parameter name, data type (float32/uint16/int32), unit (V/A/kW/Hz), register count, R/W access
   - Byte order specification (often in a separate section)
   - Identification register (if any)
   - Scale factors, known quirks
4. **Propose:** Hermes presents the extracted KB entry to the engineer for review:
   - "I extracted 39 parameters from the PM5110 guide. Here's the register map — please verify."
   - Shows a structured table the engineer can approve, edit, or reject
5. **Store:** On approval, Hermes writes the KB JSON file and updates the index. The source PDF path and page numbers are stored in the KB entry for traceability.

#### KB Entry Structure (with document provenance)

```json
{
  "manufacturer": "Schneider Electric",
  "model": "PM5110",
  "protocol": "modbus_tcp",
  "byte_order": "big_endian",
  "identification": {
    "register": 64999,
    "expected_value": "0x0050",
    "description": "Model ID register"
  },
  "registers": [
    {
      "address": 0,
      "count": 2,
      "parameter": "voltage_l1n",
      "data_type": "float32",
      "unit": "V",
      "scale": 1.0,
      "access": "read",
      "typical_range": [180, 280],
      "source_page": 12
    },
    {
      "address": 2,
      "count": 2,
      "parameter": "voltage_l2n",
      "data_type": "float32",
      "unit": "V",
      "scale": 1.0,
      "access": "read",
      "typical_range": [180, 280],
      "source_page": 12
    }
  ],
  "quirks": [
    "Returns 0xFFFF for unsupported registers",
    "Energy counters reset at 999999.99"
  ],
  "source_document": "schneider_pm5110_modbus_guide.pdf",
  "extraction_date": "2026-04-10",
  "verified_by_engineer": true,
  "version": 1
}
```

#### Document Reference During Configuration

When Hermes is configuring a site and encounters an ambiguity (e.g., byte order mismatch, unexpected register value), it can go back to the source:

- `read_mfm_document(model, page)` — read a specific page from the source PDF for the given model
- `search_mfm_document(model, query)` — search the source document for a keyword (e.g., "byte order", "endian", "energy counter reset")

This allows Hermes to **self-verify** against the manufacturer's documentation rather than blindly trusting the extracted KB entry.

#### Learning New Models On-Site

If the engineer encounters a meter not in the KB:
1. Engineer: "I have a Rishabh Rish Master 3440, here's the communication guide" (uploads PDF)
2. Hermes ingests the document, extracts register map, proposes KB entry
3. Engineer verifies, Hermes saves to KB
4. Hermes immediately uses the new KB entry to configure the device in the same session
5. On next deployment, the new KB entry is available (portable via `agent/plc_agent/data/mfm_kb/`)

This means the KB **grows organically** as Hermes encounters new meter types across deployments.

#### KB-Related Tools

| Tool | Category | Purpose |
|------|----------|---------|
| `lookup_mfm_model(model)` | Read | Pull structured register map into context |
| `list_mfm_models()` | Read | List all models in the KB |
| `read_mfm_document(model, page)` | Read | Read a page from the source PDF for verification |
| `search_mfm_document(model, query)` | Read | Search the source document by keyword |
| `read_document(path, pages)` | Read | Extract text/OCR from an uploaded PDF |
| `read_document_page_image(path, page)` | Read | Render a PDF page as image for vision analysis |
| `propose_kb_entry(model, data)` | Write (gated) | Propose a new KB entry from extracted data |
| `update_kb_entry(model, patch)` | Write (gated) | Update an existing KB entry |

#### KB Quality Gates

- Every KB entry must have `verified_by_engineer: true` before Hermes uses it in production configuration
- Unverified entries are marked as `draft` — Hermes will warn the engineer: "This register map was auto-extracted and hasn't been verified. Want me to do a live register sweep to cross-check?"
- If live readings don't match the KB entry (e.g., voltage at register 0 reads as garbage), Hermes flags it and references the source document: "Register 0 should be Voltage L1-N per page 12 of the PM5110 guide, but I'm reading 0xFFFF. The device might use a different firmware version."

---

## Configuration Stages

When Hermes configures a site — whether from the engineer's description (Mode 1) or from network discovery (Mode 2) — it walks through these conceptual stages. These are not separate engines; they are steps in Hermes's reasoning.

### Stage 1+2: Discovery & Identification

**In Mode 1 ("I know my setup"):** The engineer tells Hermes what devices they have and where. Hermes validates by running connection tests and reading sample values.

**In Mode 2 ("Scan and discover"):** Hermes uses diagnostic tools to find and identify devices:

1. **Port scan** the subnet for devices responding on Modbus TCP (502) or OPC UA
2. For each responding IP, **enumerate unit IDs** (1-247, or configured range)
3. **Check identification registers** — many MFMs expose a model ID at a known address
4. **If no ID register**, do a register sweep:
   - Read holding registers in blocks (0-99, 100-199, etc.)
   - The pattern of "which registers exist and which don't" is itself a fingerprint
5. **Decode sample values** trying different byte-order assumptions (big-endian, little-endian, mid-endian)
6. **Score candidates** based on register pattern match, value range plausibility, byte order consistency, ID register match

### Validation — Three-Layer Intelligence

Validation uses three progressively sophisticated layers. Each layer adds signal — Hermes integrates all three into its reasoning.

#### Layer 1: Rule-Based Validation (deterministic, instant)

Static thresholds and cross-parameter checks. Fast, zero training needed. First pass — catches the obvious.

**Physical range validation (Indian industrial 3-phase):**

| Parameter | Expected Range | Red Flag If |
|-----------|---------------|-------------|
| Voltage L-L | 380 - 440V | < 50V or > 600V |
| Voltage L-N | 220 - 254V | < 30V or > 350V |
| Current (per phase) | 0 - rated CT value | Negative, or > 10x CT |
| Power Factor | -1.0 to +1.0 | Outside this range |
| Frequency | 49.5 - 50.5 Hz | < 45 or > 55 Hz |
| Active Power | 0 - rated capacity | Negative on non-bidirectional meter |
| Reactive Power | Proportional to PF & active | Wildly inconsistent with PF |
| Energy (cumulative) | Monotonically increasing | Decreasing (unless counter reset) |

**Cross-parameter consistency checks:**
- `V_LN * sqrt(3) ~ V_LL` (within 5%)
- `P_total ~ V_avg * I_avg * PF_avg * sqrt(3)` (within 10%)
- `P_apparent^2 ~ P_active^2 + P_reactive^2` (within 5%)
- All three phase voltages should be similar (unbalance < 10% typically)
- Frequency should be identical across all devices on the same grid

#### Layer 2: Anomaly Detection NN (during configuration)

A lightweight neural network that learns "what do valid MFM readings look like" from historical installation data. Catches things static rules miss — subtle misidentification, CT wiring errors, encoding mismatches that produce individually-valid but collectively-unusual readings.

**Architecture:** Autoencoder / Variational Autoencoder (VAE)
- **Input:** A reading snapshot — all parameters from one device, normalized to [0,1] (voltage, current, PF, frequency, active/reactive/apparent power, energy, etc.)
- **Output:** Reconstruction error = anomaly score. High error → "this device's readings don't look like any healthy installation I've seen"
- **Per-parameter contribution:** Which specific parameters are driving the anomaly (e.g., "power/current/PF relationship is unusual")
- **Model size:** Tiny — 3-layer autoencoder on 39 input features, <1MB. Runs on CPU, no GPU competition with Qwen

**What it catches that rules don't:**
- A PM5110 and PM5300 can both produce readings in valid ranges, but with different parameter correlations. The autoencoder learns these correlations per model type.
- CT wired in reverse produces current readings that are individually valid, but the power factor relationship is subtly wrong
- Incorrect byte order that produces values technically in range but with an unusual distribution across parameters
- "All values pass threshold checks but the overall reading profile is unusual for this meter type"

**Training data:**
- **Cold start (synthetic):** Generate synthetic reading snapshots from MFM KB `typical_range` values with physically realistic correlations (P = V × I × PF × √3, S² = P² + Q², etc.). Provides a reasonable initial model.
- **Warm up (real):** Each confirmed-good installation (engineer-verified `clean_run` sessions) feeds anonymized reading snapshots back into the training set. The model improves with every deployment.
- **Cross-deployment:** Training datasets are portable alongside skills — export anonymized snapshots (parameter values + meter model, no IPs or device names) as a training bundle.

**Per-model specialization:** Train a separate small autoencoder per MFM model family (one for PM5110, one for ABB B24, etc.). This captures model-specific parameter correlations rather than generic "power meter" patterns.

#### Layer 3: Predictive Analysis (runtime, post-configuration)

After logging starts, a time-series model learns the device's baseline behavior and predicts future values. This is a **runtime monitoring enhancement** that runs alongside the Rust job runner, not part of the configuration pipeline.

**Architecture options (start simple, upgrade if needed):**

| Approach | Complexity | Training Required | Best For |
|----------|-----------|-------------------|----------|
| Statistical (Z-score on rolling window, Holt-Winters exponential smoothing) | Low | None — immediate startup | Threshold drift, sudden anomalies |
| Isolation Forest on sliding windows | Medium | ~1 day of data | Multivariate anomalies across parameters |
| Small LSTM / Temporal Convolutional Network | Higher | ~3-7 days of data | Temporal patterns (daily load cycles, shift changes) |

**Recommended:** Start with statistical methods (zero training delay, catches 90% of anomalies). Upgrade to LSTM/TCN per-device after sufficient baseline data accumulates.

**What it predicts:**
- Expected next reading ± confidence interval — alert if actual deviates beyond confidence
- Trend detection: "voltage on this feeder has dropped 3% over the past week — possible transformer tap issue"
- Load pattern classification: "motor load" vs "lighting panel" vs "UPS" based on PF profile and load curve shape
- Degradation patterns: increasing harmonic distortion trending toward equipment stress

**How it runs:**
- Lightweight background process alongside the Rust job runner
- Reads from the same logged data tables
- Each device gets its own model instance (statistical methods = negligible memory; LSTM = ~10-50KB per device)
- Alerts surface as notifications through the existing `app_notifications` system
- Hermes can query prediction state via a `read_prediction_status(device_id)` tool

**Baseline learning period:**
- Statistical: immediate (rolling window adapts in real-time)
- Isolation Forest: ~1 day for stable baseline
- LSTM/TCN: ~3-7 days, configurable per site
- During baseline, only Layer 1+2 rules apply (no predictive alerts)

#### How Hermes Integrates All Three Layers

During configuration (Stage 1+2), after reading live values from a device:

```
1. Layer 1 (rules):    "Voltage 415V — PASS, Current 12A — PASS, PF 0.87 — PASS"
2. Layer 2 (anomaly):  "Anomaly score 0.12 (low). Readings consistent with healthy PM5110. Confidence: 94%"
→ Hermes: "All readings verified. Proceeding to schema."
```

When something is wrong:

```
1. Layer 1 (rules):    "Voltage 415V — PASS, Current 12A — PASS, PF 0.87 — PASS"  (all in range)
2. Layer 2 (anomaly):  "Anomaly score 0.78 (HIGH). Active power 4.2kW vs apparent 8.1kVA is unusual
                        for PF 0.87 — expected apparent ≈ 4.8kVA. Top contributors: S_total, P_total"
→ Hermes: "Rule checks pass but the anomaly model flags a power consistency issue.
           Possible CT ratio mismatch or incorrect encoding. Let me check the source
           document page 15 and try alternate byte order..."
```

After logging starts (runtime):

```
3. Layer 3 (predict):  "Device mfm_003 — current on Phase R trending up 2%/day for 5 days.
                        Current: 45A, baseline: 38A. Deviation: 3.2σ."
→ Notification: "Possible increasing load or CT degradation on mfm_003. Review recommended."
```

#### Confidence Scoring (Mode 2 — combines all layers)

| Confidence | Layer 1 | Layer 2 | Action |
|-----------|---------|---------|--------|
| **High (>90%)** | All rules pass + cross-checks pass | Anomaly score < 0.2 | Auto-accept |
| **Medium (70-90%)** | Rules pass but some values borderline | Anomaly score 0.2-0.5 | Present to engineer with recommendation |
| **Low (<70%)** | Some rules fail or multiple candidates | Anomaly score > 0.5 | Flag for manual identification |

Layer 2 anomaly score is a weighted input to the overall confidence, not a veto. A high anomaly score with passing rules triggers investigation, not automatic rejection.

### Stage 3: Schema

Hermes looks up the identified model in the MFM KB and knows its full register map.

- Proposes a schema with all available parameters (e.g., "This PM5110 exposes 39 parameters")
- Groups logically: always-recommended (V, I, P, PF, F, Energy) vs. optional (harmonics, THD, demand, min/max)
- Checks if a schema for this model already exists in the system — reuses rather than creating duplicates
- Suggests table names based on topology (e.g., `mfm_001`, `mfm_002`, or `incomer_main`, `feeder_block_a`)

### Stage 4: Mapping

Deterministic KB lookup — for each field in the approved schema, Hermes retrieves:
- Modbus register address
- Register count (1 for uint16, 2 for float32, etc.)
- Encoding (float32, uint16, int32, etc.) with byte order (e.g., `float32_be`, `float32_me`)
- Scale factor (e.g., some MFMs report voltage in 0.1V units)
- Recommended deadband

Applies via `store.upsert_mapping()` in the format the existing system already uses.

**Edge cases Hermes should watch for:**
- Same model, different firmware → dry-run values help disambiguate
- Custom register configurations → flag if detected values don't match default map
- Gateway-level address offsets → some GICs apply a base offset per unit ID

### Stage 5: Job Recommendation

Hermes reasons about job configuration based on:

| Factor | Logic |
|--------|-------|
| Devices per gateway | More devices = longer poll cycle. 13 devices on one GIC ≈ 1.5s minimum for sequential polling |
| Parameter volatility | Fast-changing (current, power) -> short interval. Slow-changing (energy) -> longer interval or trigger-based |
| Network bandwidth | Calculate expected bytes/sec. Flag if approaching gateway limits |
| Storage volume | At 1s interval, 39 fields, 297 devices = ~11.5K rows/sec = ~1B rows/day |
| Use case | Real-time monitoring: 1s. Billing/audit: 15-min aligned. Trending: 1-5 min |

Suggests: job grouping (typically by gateway), polling interval, batching config, trigger rules, and retention policy.

---

# Part 2: Backend Plan — NousResearch Hermes Agent

---

## Summary

- The AI mode uses the [NousResearch Hermes](https://github.com/NousResearch) agent framework — an agentic function-calling system with tool use, skills, and structured reasoning. Hermes runs as an **in-process agent** inside the FastAPI backend that operates the existing LoggerFast pipeline on behalf of the user. It is not a parallel system — it calls the same `store`, `appdb`, and router logic that the manual pipeline uses.
- The underlying model is **Qwen3.5-27B** served via a local Ollama instance (OpenAI-compatible HTTP API). No cloud dependency.
- The Hermes agent has **full system access**: it can read any source file in the codebase (code awareness), call internal Python functions directly (not just REST), and read/write raw store and DB state for diagnostics.
- Each AI interaction is modeled as a **session** — one onboarding/configuration run, resumable, fully traced, ending in either discard or apply.
- A mandatory **plan-then-execute approval gate** ensures live config is only mutated after the engineer reviews and confirms. Reads and diagnostics are auto-approved; writes require confirmation.
- Hermes has a built-in **skills system** — it learns reusable procedures from sessions, stores them as portable natural language skills, and retrieves relevant skills in future sessions across deployments.

---

## Operating Modes

### Mode 1: "I Know My Setup" (MVP)

The engineer describes their site to Hermes in natural language. Hermes configures everything through the existing pipeline.

Example flow:
1. Engineer: "I have 10 Schneider PM5110 meters behind a gateway at 10.10.1.1, unit IDs 1-10"
2. Hermes retrieves PM5110 register map from MFM KB
3. Hermes presents a plan: create gateway, 10 devices, PM5110 schema (reuse if exists), 10 tables, 390 mappings, 1 job
4. Engineer approves
5. Hermes executes via internal function calls: `store.add_gateway()`, `store.add_device()`, `store.create_schema()`, `store.upsert_mapping()`, etc.
6. Hermes runs connection tests and validates live readings against expected ranges
7. Hermes reports results: "All 10 devices connected. Voltage readings 410-418V, frequency 50.01Hz. Configuration complete."

### Mode 2: "Scan and Discover" (Phase 2)

Hermes scans the network, identifies devices using register fingerprinting and the MFM KB, and proposes a configuration. The 5 configuration stages (discovery, identification, schema, mapping, jobs) are driven by Hermes's reasoning using diagnostic tools — not by separate deterministic engines.

---

## Model & Runtime

- **Agent framework:** NousResearch Hermes — provides agentic function calling, tool use, structured reasoning, and skills
- **Model:** Qwen3.5-27B served via local Ollama (offline-capable)
- **Runtime:** In-process async task within the FastAPI agent (not a separate service)
- **LLM communication:** Ollama HTTP API (OpenAI-compatible endpoint)
- **Internal access:** Direct Python-level access to `store`, `appdb`, router logic, internal functions — the agent is not limited to the REST API surface
- **Code awareness:** The agent can read any source file in `agent/plc_agent/` to understand system behavior, debug issues, and explain logic to the engineer

### Reference Implementation

A production Hermes integration already exists in the Neurareport V2 template creation pipeline (`/home/rohith/desktop/Neurareport V2/backend/app/services/chat/`). The LoggerFast integration follows the same proven patterns.

**Components to vendor/fork from Neurareport V2:**

| Component | Neurareport Source | LoggerFast Adaptation |
|-----------|-------------------|----------------------|
| Agent wrapper | `hermes_agent.py` (982 lines) — wraps `AIAgent`, background thread, NDJSON drain | Fork, replace tool surface |
| Tool adapter | `hermes_adapter.py` (496 lines) — tool registration, sync wrappers, callback bridge | Fork, rewire to LoggerFast tools |
| Session state machine | `session.py` (327 lines) — state transitions, persistence | Rewrite states for LoggerFast |
| LLM config | `llm.py` — OpenAI-compatible provider, Qwen config, thinking mode | Reuse as-is |
| System prompt builder | `hermes_system_prompt.py` (550 lines) — dynamic context injection per state | Rewrite for LoggerFast domain |
| Hermes framework | `vendor/hermes-agent/` — `AIAgent`, tool registry, skills, memory, session search | Direct reuse (vendored) |

**What must be written fresh for LoggerFast:**
- `tools.py` — all LoggerFast domain tools (read/write/diagnostic)
- `hermes_system_prompt.py` — LoggerFast-specific persona, domain knowledge, state directives
- MFM KB retrieval tool
- Session DB schema (LoggerFast-specific tables)

### Threading Model

Follows the Neurareport pattern:
1. Hermes `AIAgent` runs in a **background thread** via `asyncio.to_thread()`
2. The main async loop **drains NDJSON events** in real-time via a sentinel queue pattern
3. Async tool functions are wrapped for Hermes's sync registry via `asyncio.run_coroutine_threadsafe()`
4. Callbacks (`on_tool_start`, `on_tool_complete`, `on_tool_progress`, `on_thinking`) are bridged to NDJSON events via `loop.call_soon_threadsafe()`

### LLM Configuration

Two model endpoints, same pattern as Neurareport V2's `llm.py`:

**Primary (reasoning + tool calling):**
```
LLM_PROVIDER=openai_compat
LLM_MODEL=qwen3.5:27b
LLM_API_BASE=http://localhost:11434/v1    # Ollama default
LLM_API_KEY=ollama
LLM_MAX_TOKENS=4096                       # per tool-calling turn
LLM_EXTRA_BODY={"chat_template_kwargs": {"enable_thinking": true}}
```

**Vision / OCR (document extraction):**
```
VISION_LLM_MODEL=glm-ocr
VISION_LLM_API_BASE=http://localhost:11434/v1   # Ollama (same instance)
VISION_LLM_API_KEY=ollama
```

GLM-OCR handles all PDF/image processing — register map table extraction, scanned page OCR, and structured data recognition. Hermes delegates to GLM-OCR via the `read_document` and `read_document_page_image` tools, then reasons over the extracted text with Qwen3.5.

### Iteration & Timeout Limits

| Setting | Value | Rationale |
|---------|-------|-----------|
| Max iterations | 30 | A 300-device site may need many tool calls |
| Session timeout | 1800s (30 min) | End-to-end config of a large site |
| Per-tool timeout | 30s (default), 120s (network scan) | Prevent hung tools from blocking the session |

### System Access — Two Tiers

**Tier 1 — Internal function calls (preferred path):**
Hermes calls the same validation and business logic the REST endpoints use, but directly in-process. Examples: `store.create_schema()`, `store.upsert_mapping()`, `appdb.ensure_data_table()`. This preserves validation and side effects.

**Tier 2 — Raw store/DB access (escape hatch):**
For diagnostics and edge cases, Hermes can read raw store state or query the DB directly. These calls are marked differently in the session trace for auditability.

---

## End User

The target user is a **customer's site engineer**, not the Neuact development team. This means:
- Hermes must explain what it's doing and why
- Hermes must ask for confirmation before mutating live config
- Error messages and suggestions must be in plain language, not developer jargon
- Hermes should proactively flag potential issues ("this gateway has 15 devices — at 1s polling you'll need at least 2s cycle time")

---

## Public APIs and Interfaces

### Session API

- `POST /ai/sessions` — create a session with scan scope, target DB, and optional user intent
- `GET /ai/sessions/{id}` — fetch session state, staged plan, approvals, and summary
- `POST /ai/sessions/{id}/chat` — NDJSON streaming endpoint for Hermes interaction
- `GET /ai/sessions/{id}/trace` — fetch persisted audit events (every tool call logged)
- `POST /ai/sessions/{id}/approve` — record user approvals or rejections for staged items
- `POST /ai/sessions/{id}/apply` — execute the approved plan into live LoggerFast config

### New Utility Endpoints

- `POST /devices/raw_read` — raw Modbus register read / OPC UA node browse without pre-existing device config. Parameters: `{ip, port, unit_id, start_address, count, protocol}`. Used by Hermes for discovery and verification.

### MFM Knowledge Base API

- `GET /ai/kb` — list all models in the KB (name, manufacturer, register count, verified status)
- `GET /ai/kb/{model}` — get full KB entry for a model (register map, byte order, quirks)
- `POST /ai/kb/upload` — upload a manufacturer communication guide PDF for ingestion
- `POST /ai/kb/{model}` — create or update a KB entry (from Hermes extraction or manual edit)
- `DELETE /ai/kb/{model}` — remove a KB entry
- `GET /ai/kb/{model}/document` — download the source PDF for a model
- `GET /ai/kb/{model}/document/page/{page}` — render a specific page from the source PDF

### NDJSON Event Contract

Streaming events from `POST /ai/sessions/{id}/chat`. Follows the same callback bridge pattern as Neurareport V2 (`hermes_adapter.py` lines 350-496) — Hermes callbacks are mapped to NDJSON events via `loop.call_soon_threadsafe()`.

**Lifecycle events:**

```jsonc
// Session start
{"event": "chat_start", "session_id": "sess_abc", "pipeline_state": "chatting"}

// Tool execution (maps to on_tool_start / on_tool_complete callbacks)
{"event": "stage", "stage": "create_device", "status": "started", "progress": 0}
{"event": "stage", "stage": "create_device", "status": "running", "progress": 50, "detail": "5/10 devices created"}
{"event": "stage", "stage": "create_device", "status": "complete", "progress": 100}

// Plan proposal
{"event": "plan_proposed", "plan": {"gateways": 1, "devices": 10, "schemas": 1, "tables": 10, "mappings": 390, "jobs": 1}}

// Approval gate
{"event": "approval_required", "plan_id": "plan_001", "message": "Create 10 PM5110 devices with full mapping?"}

// Completion (frontend bulk-restores from config state)
{"event": "chat_complete", "pipeline_state": "applied", "message": "Configuration complete. All 10 devices logging.",
 "learning_signal": {"clean_run": true, "patterns": [...]},
 "session_id": "sess_abc"}

// Error
{"event": "error", "code": "device:connection_failed", "message": "Could not reach 10.10.1.10:502", "recoverable": true}
```

**No token streaming** — Hermes emits event-driven progress via stage events, and a final message on `chat_complete`. This avoids partial text artifacts and keeps the frontend simple (same approach as Neurareport V2).

---

## Hermes Tool Surface

### Read Tools (auto-approved)

| Tool | Maps To | Purpose |
|------|---------|---------|
| `read_config` | `store` getters | Read all devices, schemas, tables, mappings, jobs |
| `read_gateway_list` | `store._gateways` | Existing gateways and status |
| `read_schema_list` | `store._schemas` | Schemas in the system |
| `read_table_mapping` | `store._mappings[table_id]` | What's mapped on a table |
| `read_job_status` | `store._jobs` | Running/stopped, metrics, error rate |
| `read_live_values` | WS live read logic | Current readings from a device |
| `read_device_status` | `store._devices[id]` | Connected/disconnected, latency |
| `lookup_mfm_model` | MFM KB retrieval | Pull register map for a specific MFM model into context |
| `read_source_file` | filesystem read | Read any source file in `agent/plc_agent/` for debugging |
| `list_mfm_models` | MFM KB index | List all models in the knowledge base |
| `read_mfm_document` | PDF read | Read a specific page from the source PDF for a model |
| `search_mfm_document` | PDF search | Search the source document by keyword |
| `read_document` | GLM-OCR | Extract text + tables from a PDF via GLM-OCR (for KB ingestion) |
| `read_document_page_image` | GLM-OCR | Render a PDF page as image → GLM-OCR for structured table recognition |

### Write Tools (require approval)

| Tool | Maps To | Purpose |
|------|---------|---------|
| `create_gateway` | `store.add_gateway()` | Create a gateway entry |
| `create_device` | `store.add_device()` | Create a device with protocol params |
| `test_device` | `store.test_device_connection()` | Test connectivity, get latency |
| `create_schema` | `store.create_schema()` | Create schema with field definitions |
| `create_table` | `store.add_table()` | Create table bound to device + schema |
| `apply_mappings` | `store.upsert_mapping()` | Apply register-to-field mappings |
| `migrate_table` | `appdb.ensure_data_table()` | Create destination data table |
| `create_job` | `store.add_job()` | Create polling job |
| `start_job` | `store.set_job_status()` | Start a job |
| `propose_kb_entry` | MFM KB write | Propose a new KB entry extracted from a document |
| `update_kb_entry` | MFM KB patch | Update an existing KB entry (e.g., firmware variant) |

### Diagnostic Tools (auto-approved)

| Tool | Maps To | Purpose |
|------|---------|---------|
| `read_raw_registers` | new `POST /devices/raw_read` | Read Modbus registers without device config |
| `browse_opcua_nodes` | new `POST /devices/raw_read` | Browse OPC UA server without device config |
| `ping_host` | subprocess | Check host reachability |
| `scan_port` | asyncio TCP connect | Check if a port is open |
| `query_db` | `appdb` read-only query | Run diagnostic SQL on app-local DB |
| `run_anomaly_check` | Layer 2 autoencoder | Run anomaly detection on a device's current readings, returns score + per-parameter contribution |
| `read_prediction_status` | Layer 3 runtime | Get prediction state, trend alerts, and baseline status for a device |

### State-Specific Toolsets

Not all tools are available in every state. Hermes only sees tools relevant to the current pipeline stage. This reduces context window pressure and prevents invalid operations.

| Session State | Available Toolsets |
|--------------|-------------------|
| `created` | `read_config`, `read_gateway_list`, `read_schema_list`, `lookup_mfm_model`, `read_source_file` |
| `chatting` (pre-plan) | All read tools + all diagnostic tools + `lookup_mfm_model` |
| `plan_proposed` | Read tools only (no writes until approved) |
| `awaiting_review` | Read tools only |
| `approved` | All read tools + all write tools + diagnostic tools |
| `applying` | All tools (Hermes executes the plan) |
| `applied` | Read tools + `read_live_values` + `read_job_status` + `run_anomaly_check` + `read_prediction_status` (verification) |
| `failed` | All read + diagnostic tools (investigation) + `read_source_file` |

### Per-Tool Call Limits

Prevents runaway tool calls. Enforced by the adapter, not the system prompt.

| Tool | Limit Per Session | Rationale |
|------|-------------------|-----------|
| `create_device` | plan device count + 5 | Prevent runaway creation |
| `apply_mappings` | plan table count + 5 | One per table, with margin |
| `start_job` | 10 | Reasonable ceiling |
| `read_raw_registers` | 50 | Prevent network flooding during discovery |
| `create_schema` | 10 | Unlikely to need more |
| `migrate_table` | plan table count + 5 | One per table, with margin |
| `read_source_file` | 20 | Enough for debugging, prevents context bloat |

### Sanitization Gate

Before Hermes sees a tool result, `_sanitize_for_agent()` strips data that should not leak into skills or memory:

- **Strip from tool results:** Full IP addresses (mask to `10.10.x.x`), credentials, connection strings, raw SQL
- **Keep in tool results:** Device counts, status summaries, error types, value ranges, field names
- **Strip from skill learning:** Any site-specific identifiers (IPs, device names, gateway hosts)
- **Keep in skill learning:** Abstract procedures, error recovery patterns, MFM model handling

This follows the same pattern as Neurareport V2's sanitization gate (`hermes_adapter.py` line 183), where column names and schema details are stripped before reaching Hermes memory.

---

## Skills System

Skills are a core feature of the Hermes agent framework (`vendor/hermes-agent/tools/skills_hub.py`). Unlike Neurareport V2 where skills are disabled in pipeline mode to save LLM calls, **LoggerFast keeps skills enabled** — site configuration is precisely where skills add the most value. Hermes gets measurably faster at configuring PM5110 sites after doing it 3 times.

### What a Skill Is

A **named, parameterized, natural language procedure** that Hermes discovered works during a real session. Not code — Hermes interprets the procedure each time, adapting to the specific situation.

### Hermes Built-In Skill Tools

These are provided by the Hermes framework and available in all sessions:

| Tool | Purpose |
|------|---------|
| `skills_list` | List all learned skills, filterable by tags |
| `skill_view` | View a specific skill's full procedure |
| `skill_manage` | Create, update, or deprecate a skill |
| `memory` | Persistent learned patterns (abstract, not site-specific) |
| `session_search` | FTS5 full-text search across past sessions for recall |
| `clarify` | Ask the engineer a question when ambiguous |

### Skill Structure

```
skill_name: str
description: str
trigger_conditions: str         # natural language — Hermes decides when to apply
parameters: [{name, type, description}]
steps: str                      # natural language procedure
source_session_id: str
success_count: int
failure_count: int
last_used: datetime
tags: [str]                     # "schneider", "modbus", "batch-config", "troubleshooting"
```

### Example Learned Skill

```
skill_name: "configure_schneider_pm5110_batch"
description: "Configure multiple Schneider PM5110 meters behind a single gateway"
trigger_conditions: "User has multiple PM5110 meters behind one gateway"
parameters:
  - gateway_ip: str
  - unit_id_range: [start, end]
  - db_target: str
steps: |
  1. Create or reuse gateway at {gateway_ip}
  2. Create PM5110 schema (39 fields) if not exists, else reuse existing
  3. For each unit_id in range:
     - Create device "mfm_{unit_id:03d}" with modbus TCP params
     - Test connection, flag failures
     - Create table bound to device + schema
     - Apply PM5110 register map as mapping (lookup from MFM KB)
     - Migrate table
  4. Create one job grouping all tables, 1s interval, batch 100
  5. Start job, validate live readings against expected ranges
source_session_id: "session_abc123"
success_count: 3
tags: ["schneider", "pm5110", "modbus", "batch-config"]
```

### Skill Lifecycle

- **Learning:** After a `clean_run` session (no retries, no user corrections), Hermes auto-proposes skills to save. Engineer can approve, edit, or reject. This mirrors Neurareport V2's learning signal where skills are only auto-generated from first-try validation passes.
- **Retrieval:** At session start, Hermes searches skills by tags and trigger conditions via `session_search` (FTS5). Injects only the top 3-5 relevant skills into context (not all skills — context window budget).
- **Refinement:** If Hermes uses a skill and deviates (something didn't work, or engineer corrected it), it proposes an update via `skill_manage`. Skills evolve.
- **Deprecation:** If a skill fails repeatedly (success rate drops), Hermes flags it for review or auto-disables.

### Skill Portability

Skills are **exportable/importable as JSON** across LoggerFast deployments. A team that deploys PM5110s at every site can export their battle-tested skills and import them at a new installation. Skills contain no site-specific artifacts (no IPs, no device names) — only abstract procedures.

Export/import API:
- `GET /ai/skills` — list all learned skills
- `GET /ai/skills/export` — export all skills as JSON
- `POST /ai/skills/import` — import skills from JSON
- `DELETE /ai/skills/{id}` — remove a skill

### What Skills Are NOT

- Not macros or executable scripts — they are natural language, interpreted each time
- Not site-specific configs — no IP addresses, device names, or credentials
- Not full session replays — abstractions, not recordings

---

## Session Model

### Persistence Layers

Two complementary persistence layers, following the Neurareport V2 pattern:

**1. LoggerFast session tables (app-local DB):**

| Table | Purpose |
|-------|---------|
| `app_ai_sessions` | Session metadata: id, state, scope, created_at, updated_at |
| `app_ai_messages` | Conversation history: role, content, timestamp (user + assistant only, not intermediate tool calls) |
| `app_ai_tool_events` | Every tool call: name, args, result, duration, tier (internal/raw) |
| `app_ai_plans` | Staged plans awaiting approval: items, status |
| `app_ai_approvals` | Engineer approval/rejection records with timestamps |
| `app_ai_skills` | Learned skills: name, structure, metrics, tags, export/import metadata |

**2. Hermes-native persistence (managed by the Hermes framework):**

| Store | Purpose |
|-------|---------|
| `~/.hermes/sessions/` | Hermes SessionDB — FTS5 full-text search across sessions for cross-session skill discovery |
| `~/.hermes/skills/` | Hermes skill store — auto-generated from clean pipeline runs |
| `~/.hermes/memory/` | Hermes persistent memory — abstract patterns, not site data |
| `trajectory_samples.jsonl` | Successful session trajectories in ShareGPT format |
| `failed_trajectories.jsonl` | Failed session trajectories for debugging |

The LoggerFast tables are the authoritative session record. Hermes-native persistence is for the agent's own learning and cross-session recall. Both are present and complementary.

### Session Schema

```json
{
  "session_id": "sess_abc123",
  "pipeline_state": "chatting",
  "scope": {"subnet": "10.10.1.0/24", "protocols": ["modbus", "opcua"]},
  "db_target_id": "target_001",
  "completed_stages": ["discovery", "identification"],
  "created_entities": {
    "gateway_ids": ["gw_001"],
    "device_ids": ["dev_001", "dev_002"],
    "schema_ids": ["sch_pm5110"],
    "table_ids": ["tbl_001", "tbl_002"],
    "job_ids": []
  },
  "turn_count": 5,
  "created_at": "2026-04-10T10:00:00Z",
  "updated_at": "2026-04-10T10:05:30Z"
}
```

### State Machine

```
created → chatting → plan_proposed → awaiting_review → approved → applying → applied
               ↑           |                |                          |
               |           v                v                          v
               +------ chatting          discarded                   failed
```

- `created` — session initialized, no interaction yet
- `chatting` — Hermes and engineer are conversing
- `plan_proposed` — Hermes has presented a configuration plan
- `awaiting_review` — waiting for engineer approval
- `approved` — engineer approved, ready to execute
- `applying` — Hermes is executing the plan (creating entities)
- `applied` — configuration complete and verified
- `failed` — something went wrong (checkpointed via `created_entities`, resumable)
- `discarded` — engineer cancelled the session

State transitions are **hard-enforced via a transition table** (same as Neurareport V2's `session.py`). Every tool enforces its required state via `_require_state()` — the LLM cannot bypass this; Python enforces it.

---

## Approval Model

**Plan-then-execute (default):** Hermes builds a complete plan, presents it as a summary ("I will create 10 devices, 1 schema, 10 tables, 390 mappings, 1 job"), engineer approves or edits, then Hermes executes everything.

**Trust tiers:**
- **Auto-approved:** All read tools, diagnostic tools, connection tests
- **Gated:** All write tools (create, map, migrate, start) — bundled into the plan approval
- **Never auto:** Destructive operations (delete device, drop table, stop job)

The engineer is a customer's site engineer, not a developer. Hermes must explain the plan in plain language, flag potential issues proactively, and never mutate live config without explicit confirmation.

---

## System Prompt Design

The system prompt is **dynamic** — rebuilt on every turn based on current session state. Follows the Neurareport pattern of `build_system_prompt(session)` that injects live context.

### Always-Present Sections

- **Persona:** "LoggerFast AI Assistant — an intelligent industrial configuration agent"
- **Language rules:** Plain language for a site engineer, not developer jargon. "devices" not "entities", "register addresses" not "mapping rows"
- **Approval rules:** Never mutate live config without explicit plan approval. Always explain the plan before proposing it.
- **Domain knowledge:** LoggerFast entity model (gateway → device → schema → table → mapping → job), encoding types, protocol basics
- **Learning rules:**
  - **Learn:** Tool sequences, error recovery patterns, MFM-specific handling, byte order discoveries
  - **Never learn:** IP addresses, device names, credentials, site-specific topology, raw register dumps

### State-Injected Context

Injected dynamically per turn:

| Context | When |
|---------|------|
| Current pipeline state + completed stages | Always |
| Devices created so far (count + summary, not full list) | After first write |
| Schemas in the system (names, field counts) | During schema stage |
| Mapping health per table | During mapping stage |
| Job metrics (if jobs are running) | During verification |
| Explicit next-step directive ("You should now propose a plan" / "Execute the approved plan") | Always |
| Relevant skills (top 3-5 by tag match) | Session start |

### Error Taxonomy

Structured error types returned to Hermes for learning (not raw stack traces):

```
device:connection_failed, device:timeout, device:auth_required
mapping:invalid_address, mapping:encoding_mismatch, mapping:byte_order_wrong
schema:duplicate_name, schema:field_type_invalid
job:start_failed, job:no_mapped_tables
discovery:no_response, discovery:multiple_candidates
validation:value_out_of_range, validation:cross_check_failed
validation:anomaly_high, validation:anomaly_moderate
prediction:baseline_drift, prediction:trend_alert, prediction:deviation
precondition:wrong_state, gate:approval_required
limit:call_limit_reached
```

---

## Learning Signal & Trajectory

### Completion Signal

After each session reaches `applied` or `failed`, a learning signal is persisted:

```json
{
  "valid": true,
  "session_id": "sess_abc123",
  "stage": "applied",
  "device_count": 10,
  "clean_run": true,
  "no_retries": true,
  "no_user_corrections": true,
  "patterns": [
    {"id": "p1", "name": "batch_pm5110", "description": "10x PM5110 behind single GIC, sequential unit IDs"},
    {"id": "p2", "name": "mid_endian_detected", "description": "byte order auto-corrected from BE to ME on GIC"}
  ]
}
```

- `clean_run` = no retries AND no user corrections — Hermes preferentially learns skills from clean runs
- `patterns` = abstract observations Hermes can reuse (not site-specific data)

### Trajectory Capture

Every session is saved as a trajectory in ShareGPT format for potential fine-tuning and debugging:

- Successful runs → `trajectory_samples.jsonl`
- Failed runs → `failed_trajectories.jsonl`
- Format: `{"conversations": [...], "timestamp": ISO8601, "model": "qwen3.5:27b", "completed": bool}`

### Budget Pressure Warnings

Injected into tool results (not as separate messages) when approaching limits:

- **70% iterations used:** "Caution: approaching iteration budget. Consider batching remaining operations."
- **90% iterations used:** "Warning: near iteration limit. Prioritize essential operations only."

---

## Context Window Budget (Qwen3.5-27B)

| Content | Estimated Tokens | Strategy |
|---------|-----------------|----------|
| System prompt (role, rules, approval logic) | ~2K | Always loaded |
| LoggerFast domain knowledge (entity model, encoding types) | ~3K | Always loaded |
| MFM register maps | ~2-4K per model | On-demand via `lookup_mfm_model` tool |
| Relevant skills | ~1-2K per skill | Top 3-5 retrieved at session start |
| Current session state (entities created so far) | ~2-5K | Compressed — summaries, not raw tool results |
| Conversation history | ~5-15K | Rolling window with summarization |
| Code context (when debugging) | ~2-5K per file | On-demand via `read_source_file` tool |

**Key rule:** Never pre-load MFM KB or code into the system prompt. Always retrieve on demand. Summarize completed steps rather than carrying full tool call/result history.

---

## Byte Order Propagation

AI-derived byte order must flow through the entire backend:
1. Identification result (Hermes determines byte order during discovery/verification)
2. Mapping recommendation (Hermes applies correct byte order when generating mappings)
3. Mapping persistence (`store.upsert_mapping()` stores byte order per mapping)
4. Runtime job decoding (Rust job runner reads byte order from mapping and decodes accordingly)

This is required so Hermes's decisions affect actual polling behavior. The encoding field in mappings should encode byte order explicitly (e.g., `float32_be`, `float32_le`, `float32_me`).

---

## Test Plan

### Session lifecycle
- Create, resume, discard, fail, and apply a session
- One onboarding run = one session
- Session state machine transitions are valid and complete
- `_require_state()` guards reject tool calls in wrong state
- `created_entities` checkpoint allows `failed` sessions to resume from last successful step

### Hermes runtime
- Tool calls route to correct internal functions
- Approval gate blocks writes until engineer confirms
- Tool call tracing captures every call with args, result, duration, and tier (Tier 1 vs Tier 2)
- Per-tool call limits enforced by adapter (not system prompt)
- Context window stays within budget across long sessions
- Budget pressure warnings injected at 70% and 90% iteration usage
- Background thread + NDJSON drain loop does not deadlock under load

### NDJSON streaming
- Event ordering: `chat_start` → `stage` events → `chat_complete`
- Reconnect to session after disconnect — resume from session state
- Long-running tools (network scan) emit progress events during execution
- Sanitized data in events — no raw IPs in stage detail messages

### Skills system
- Skills learned from `clean_run` sessions contain no site-specific artifacts
- Skill retrieval returns relevant skills by tag/trigger matching via FTS5
- Skill export/import produces valid portable JSON
- Skill refinement updates an existing skill rather than creating duplicates
- Deprecated skills (high failure rate) are flagged
- Hermes-native skill store (`~/.hermes/skills/`) and LoggerFast skill table (`app_ai_skills`) stay in sync

### Sanitization
- Tool results are sanitized before reaching Hermes memory/skills
- IPs masked, credentials stripped, connection strings removed
- Error taxonomy preserved (structured error types, not raw stack traces)
- Sanitization does not remove data needed for immediate tool-calling reasoning

### Approval model
- Plan-then-execute: Hermes cannot write until plan is approved
- Read/diagnostic tools execute without approval prompt
- Destructive operations are never auto-approved
- State-specific toolsets enforced — write tools not even visible until `approved` state

### MFM Knowledge Base
- PDF upload → extraction → structured KB entry round-trip works end-to-end
- Extracted register maps match known-good manual entries (regression test against hand-verified PM5110 map)
- Unverified (draft) KB entries trigger warning when used in configuration
- Source document page references are valid (page number exists, content matches)
- Live register sweep cross-checks against KB entry — mismatches flagged with source doc reference
- KB entries are portable — export from one deployment, import to another, schema valid

### Compatibility
- Existing manual pipeline is completely unaffected when AI mode is unused
- Entities created by Hermes are indistinguishable from manually created entities (same tables, same format, same store state)
- Jobs created by Hermes run identically in the Rust job runner
- Hermes-created mappings include byte order and are decoded correctly by the Rust runner

### Validation layers
- Layer 1 (rules): all static range checks and cross-parameter checks produce correct PASS/FAIL
- Layer 2 (anomaly NN): autoencoder trained on synthetic data produces reasonable anomaly scores for known-good vs known-bad reading snapshots
- Layer 2 cold start: synthetic training data generated from MFM KB typical_range values with physically realistic correlations
- Layer 2 warm up: confirmed-good readings from `clean_run` sessions feed back into training set
- Layer 2 per-parameter contribution identifies the correct anomalous parameter in test cases (e.g., reversed CT, wrong byte order)
- Layer 3 (predictive): statistical baseline detection flags drift beyond configurable sigma threshold
- Layer 3 alerts surface through existing `app_notifications` system
- Anomaly model training datasets are portable (anonymized, no site-specific data)

### End-to-end (Mode 1)
- Engineer describes a site with N devices of model X
- Hermes creates full config: gateways, devices, schema, tables, mappings, migration, job
- Live readings validated against Layer 1 rules + Layer 2 anomaly check
- Total time for 10-device site < 2 minutes
- Learning signal persisted, trajectory captured in ShareGPT format

---

## Deliverables

1. **Hermes Agent Runtime** — NousResearch Hermes agent framework running in-process with Qwen3.5-27B via Ollama, tool registry, session manager, NDJSON streaming
2. **MFM Knowledge Base + Document Pipeline** — PDF ingestion via GLM-OCR → structured KB entries with source document provenance. Hermes builds the KB from manufacturer communication guides, verified by engineer. KB stored as versioned JSON, loaded into SQLite at runtime.
3. **Tool Surface** — read tools (config, devices, schemas, live values, KB lookup, document read, anomaly check, prediction status), write tools (create/map/migrate/job, KB propose/update), diagnostic tools (raw register read, port scan, code read)
4. **Session API** — `/ai/sessions` endpoints with state machine, approval gates, trace persistence
5. **KB API** — `/ai/kb` endpoints for upload, extraction, CRUD, and document retrieval
6. **Validation Intelligence** — three-layer validation: Layer 1 (rule-based), Layer 2 (anomaly detection autoencoder per MFM model), Layer 3 (runtime predictive analysis via statistical methods / LSTM)
7. **Skills System** — skill learning from sessions, structured storage, retrieval by relevance, portable export/import across deployments
8. **Raw Register Endpoint** — one new endpoint for Modbus register read / OPC UA node browse without pre-existing device config
9. **Frontend Integration** — chat UI in the React app (deferred — backend first)

---

## Implementation Phases

Each phase is self-contained and testable. Phases within the same wave run in parallel as separate Claude Code sessions on separate git branches. Waves execute sequentially — all sessions in a wave must merge before the next wave starts.

---

## Wave Execution Plan

```
Wave 0:  1A                         — 1 session   (foundation, everything depends on this)
Wave 1:  1B  1D  1F  1H             — 4 parallel  (read tools, diagnostics, KB pipeline, validation L1)
Wave 2:  1C  1G  1I                 — 3 parallel  (write tools, seed KB, anomaly NN)
Wave 3:  1E                         — 1 session   (sanitization, tracing, learning signal)
Wave 4:  2A  2B                     — 2 parallel  (skills, network discovery)
Wave 5:  2C                         — 1 session   (anomaly warm-up from real data)
Wave 6:  3A  3C                     — 2 parallel  (predictive runtime, frontend chat UI)
Wave 7:  3B                         — 1 session   (LSTM/TCN upgrade)
Wave 8:  3D                         — 1 session   (SLD inference, skill marketplace, cloud fallback)
                                      ─────────
                              Total: 15 sessions across 9 waves
```

### Dependency Map

```
1A ─────────────────────────────────────────────────────── (foundation)
 │
 ├── 1B (read tools)           ── Wave 1 parallel ──┐
 ├── 1D (diagnostic tools)     ── Wave 1 parallel ──┤
 ├── 1F (KB pipeline)          ── Wave 1 parallel ──┤
 └── 1H (validation Layer 1)   ── Wave 1 parallel ──┘
       │                                │          │
       ▼                                ▼          ▼
 1C (write tools + approval)   1G (seed KB)   1I (anomaly NN)
 needs 1A + 1B                 needs 1F       needs 1H
 ── Wave 2 parallel ───────────────────────────────────
       │
       ▼
 1E (sanitization, tracing, learning signal)
 needs 1C
 ── Wave 3 ────────────────────────────────────────────
       │
       ├── 2A (skills)         ── Wave 4 parallel ──┐
       └── 2B (discovery)      ── Wave 4 parallel ──┘
            needs 1D + 1F             │
                                      ▼
                               2C (anomaly warm-up)
                               needs 1I + 2A
                               ── Wave 5 ──────────
                                      │
                               ┌──────┴──────┐
                               ▼              ▼
                         3A (predictive   3C (frontend)
                         stats)           needs 1E (NDJSON stable)
                         needs 2C
                         ── Wave 6 parallel ──────
                               │
                               ▼
                         3B (LSTM/TCN)
                         needs 3A
                         ── Wave 7 ───────────────
                               │
                               ▼
                         3D (advanced)
                         needs everything
                         ── Wave 8 ───────────────
```

### Branch Strategy

Each parallel session works on its own git branch off `abishek_test`. Merge branches in dependency order at the end of each wave before starting the next.

| Wave | Phase | Branch | Key Files / Modules |
|------|-------|--------|---------------------|
| 0 | 1A | `ai/phase-1a-foundation` | `agent/plc_agent/api/ai/` (new module), vendor `hermes-agent/` |
| 1 | 1B | `ai/phase-1b-read-tools` | `ai/tools.py` (read functions), `ai/hermes_adapter.py` (state toolsets) |
| 1 | 1D | `ai/phase-1d-diagnostics` | `ai/tools.py` (diagnostic functions), `routers/devices.py` (raw_read endpoint) |
| 1 | 1F | `ai/phase-1f-kb-pipeline` | `ai/mfm_kb/` (new module), `routers/ai_kb.py` (new router) |
| 1 | 1H | `ai/phase-1h-validation-l1` | `ai/validation/` (new module), pure logic, no Hermes dependency |
| 2 | 1C | `ai/phase-1c-write-tools` | `ai/tools.py` (write functions), `ai/hermes_adapter.py` (approval gate) |
| 2 | 1G | `ai/phase-1g-seed-kb` | `data/mfm_kb/*.json`, `data/mfm_docs/*.pdf` |
| 2 | 1I | `ai/phase-1i-anomaly-nn` | `ai/validation/anomaly.py` (new), `ai/validation/synthetic_data.py` (new) |
| 3 | 1E | `ai/phase-1e-sanitization` | `ai/hermes_adapter.py` (sanitization gate), `ai/hermes_agent.py` (trajectory), `routers/ai_sessions.py` (trace endpoint) |
| 4 | 2A | `ai/phase-2a-skills` | `ai/hermes_agent.py` (enable skills), `routers/ai_skills.py` (new router) |
| 4 | 2B | `ai/phase-2b-discovery` | `ai/discovery/` (new module), `ai/tools.py` (discovery orchestration) |
| 5 | 2C | `ai/phase-2c-anomaly-warmup` | `ai/validation/anomaly.py` (retrain pipeline), `ai/validation/training_data.py` (new) |
| 6 | 3A | `ai/phase-3a-predictive-stats` | `ai/prediction/` (new module), notifications integration |
| 6 | 3C | `ai/phase-3c-frontend-chat` | `apps/desktop/src/` (React chat components) |
| 7 | 3B | `ai/phase-3b-predictive-lstm` | `ai/prediction/lstm.py` (new), per-device model training |
| 8 | 3D | `ai/phase-3d-advanced` | SLD inference, skill marketplace, cloud fallback |

### Merge Conflict Avoidance

- **1B and 1D** both add to `tools.py` but different function groups (read vs diagnostic). Merge order: 1B first, 1D rebased on top.
- **1F and 1H** write to separate new modules (`ai/mfm_kb/` and `ai/validation/`) — no overlap.
- **1C** adds write tools to `tools.py` in Wave 2, after 1B and 1D are merged — no conflict.
- **1G** only touches `data/` directory — no code overlap with anything.
- **1I** extends `ai/validation/` which 1H created — 1H must merge first.

### Session Brief Template

Each parallel Claude Code session should be started with this context:

```
You are implementing Phase {PHASE} of the LoggerFast AI integration.

Read the full plan: /home/rohith/desktop/LoggerFast/Codex/AI_Integration copy.md
Read Phase {PHASE} specifically for your scope.

Reference implementation: /home/rohith/desktop/Neurareport V2/backend/app/services/chat/

Branch: {BRANCH} (create from abishek_test after Wave {N-1} is merged)

Previous phases already merged — the following exists:
  {LIST OF FILES FROM PRIOR PHASES}

Your job: {ONE LINE SUMMARY}

Do NOT modify files outside your scope. Commit to your branch only.
```

---

### Phase 1A: Hermes Foundation — Get the Agent Loop Running

**Goal:** Prove that Hermes runs in-process inside the FastAPI agent, calls tools, and streams NDJSON back.

**Scope:**
- Vendor `hermes-agent/` framework from Neurareport V2
- Fork `llm.py` — Qwen3.5-27B + GLM-OCR provider config, env-driven
- Fork `hermes_agent.py` — agent wrapper, background thread (`asyncio.to_thread()`), NDJSON drain loop
- Fork `hermes_adapter.py` — tool registration into `ToolRegistry`, sync wrappers via `asyncio.run_coroutine_threadsafe()`, callback bridge (`on_tool_start`, `on_tool_complete`)
- Fork `session.py` — state machine with LoggerFast states (`created → chatting → plan_proposed → awaiting_review → approved → applying → applied / failed / discarded`)
- Fork `chat_history.py` — conversation persistence
- Minimal system prompt — persona ("LoggerFast AI Assistant"), basic rules, no state directives yet
- 3 read-only tools to prove the loop: `read_config`, `read_gateway_list`, `read_schema_list`
- API endpoints: `POST /ai/sessions`, `POST /ai/sessions/{id}/chat` (NDJSON streaming)

**Test:** Start a session, send "what devices are configured?", Hermes calls `read_config`, returns answer via NDJSON `chat_complete` event.

**Ref:** `hermes_agent.py` lines 664-697 (threading), `hermes_adapter.py` lines 268-340 (registration)

---

### Phase 1B: Full Read Tool Surface

**Goal:** Hermes can answer any question about the current system state and read source code for debugging.

**Scope:**
- Remaining read tools: `read_table_mapping`, `read_job_status`, `read_live_values`, `read_device_status`, `read_source_file`
- `GET /ai/sessions/{id}` endpoint (fetch session state, staged plan, summary)
- State-specific toolsets — only expose relevant tools per session state (created → read-only, chatting → all reads + diagnostics, etc.)

**Test:** Hermes answers "why is table X showing Unmapped?", reads `store.py` via `read_source_file`, explains the `mapping_health()` logic.

**Ref:** `hermes_adapter.py` lines 214-257 (state-specific toolsets)

---

### Phase 1C: Write Tools + Approval Gate

**Goal:** Hermes can create a complete site configuration from a user description, gated by plan-then-execute approval.

**Scope:**
- All write tools: `create_gateway`, `create_device`, `test_device`, `create_schema`, `create_table`, `apply_mappings`, `migrate_table`, `create_job`, `start_job`
- Plan-then-execute approval model:
  - Hermes proposes plan → `plan_proposed` state → NDJSON `plan_proposed` event
  - Engineer approves → `POST /ai/sessions/{id}/approve` → `approved` state
  - Hermes executes → `applying` state → NDJSON `apply_progress` events → `applied` state
- `POST /ai/sessions/{id}/approve` and `POST /ai/sessions/{id}/apply` endpoints
- Per-tool call limits (enforced by adapter, not system prompt)
- System prompt updated with approval rules, trust tiers, next-step directives
- `created_entities` tracking in session (gateway_ids, device_ids, schema_ids, table_ids, job_ids) for checkpoint/resume on failure

**Test:** "I have 5 Schneider PM5110 at 10.10.1.1, unit IDs 1-5" → Hermes proposes plan (1 gateway, 5 devices, 1 schema, 5 tables, 195 mappings, 1 job) → engineer approves → Hermes executes all writes → config exists in store.

**Ref:** `hermes_adapter.py` lines 71-80 (call limits), `tools.py` line 3225 (approval gate)

---

### Phase 1D: Diagnostic Tools + Raw Read Endpoint

**Goal:** Hermes can probe the network, read raw Modbus registers, and investigate issues without a pre-configured device.

**Scope:**
- New endpoint: `POST /devices/raw_read` — raw Modbus register read / OPC UA node browse. Params: `{ip, port, unit_id, start_address, count, protocol}`
- Diagnostic tools: `read_raw_registers`, `browse_opcua_nodes`, `ping_host`, `scan_port`, `query_db`
- Diagnostic tools are auto-approved (no approval gate needed)

**Test:** Hermes pings a host, scans port 502, reads holding registers 0-9, decodes as float32, reports "Voltage L1-N: 415.2V".

---

### Phase 1E: Sanitization, Tracing, and Learning Signal

**Goal:** Production-grade session audit trail, data hygiene, and the foundation for skill learning.

**Scope:**
- Sanitization gate: `_sanitize_for_agent()` strips IPs, credentials, connection strings from tool results before Hermes memory/skills. Keeps error types, device counts, value ranges, field names.
- Error taxonomy: structured error types (`device:connection_failed`, `mapping:byte_order_wrong`, `validation:value_out_of_range`, etc.)
- `GET /ai/sessions/{id}/trace` endpoint — full audit log of every tool call (name, args, sanitized result, duration, tier)
- Learning signal persistence after `applied`/`failed`: `clean_run` flag, patterns, device count
- Trajectory capture: `trajectory_samples.jsonl` (successful), `failed_trajectories.jsonl` (failed), ShareGPT format
- Budget pressure warnings injected at 70%/90% iteration usage
- Dynamic system prompt: rebuilt per turn with current state, completed stages, entity counts, explicit next-step directive

**Test:** After a successful session, trace shows sanitized tool events (IPs masked), learning signal persists with `clean_run: true`, trajectory saved.

**Ref:** `hermes_adapter.py` line 183 (sanitization), `tools.py` lines 193-279 (sanitization impl), lines 311-383 (learning signal)

---

### Phase 1F: MFM Knowledge Base + Document Pipeline

**Goal:** Hermes can ingest a manufacturer PDF, extract register maps via GLM-OCR, and build its own knowledge base.

**Scope:**
- Document storage: `agent/plc_agent/data/mfm_docs/` (PDFs, gitignored), `agent/plc_agent/data/mfm_kb/` (extracted JSON, versioned)
- GLM-OCR tools: `read_document(path, pages)`, `read_document_page_image(path, page)`
- KB tools: `lookup_mfm_model(model)`, `list_mfm_models()`, `propose_kb_entry(model, data)`, `update_kb_entry(model, patch)`
- Document reference tools: `read_mfm_document(model, page)`, `search_mfm_document(model, query)`
- KB API: `GET /ai/kb`, `POST /ai/kb/upload`, `POST /ai/kb/{model}`, `DELETE /ai/kb/{model}`, `GET /ai/kb/{model}/document`, `GET /ai/kb/{model}/document/page/{page}`
- KB quality gates: `verified_by_engineer` flag, draft entries trigger warning, unverified entries require live cross-check
- KB index file (`index.json`): model → file, version, source_doc, extraction_date

**Test:** Upload PM5110 communication guide PDF → GLM-OCR extracts register map tables → Hermes proposes KB entry with 39 registers → engineer verifies → `lookup_mfm_model("PM5110")` returns the structured entry with source page references.

---

### Phase 1G: Seed KB — Top 5 MFM Models

**Goal:** Hermes has verified register maps for the most common Indian industrial meters.

**Scope:**
- Ingest communication guide PDFs for:
  1. Schneider PM5110
  2. Schneider PM5300
  3. ABB B23/B24
  4. L&T WM330
  5. Selec MFM376
- Engineer-verified KB entry for each (all marked `verified_by_engineer: true`)
- Index file updated with all 5 models
- Each entry includes: full register map, byte order, identification register (if any), scale factors, typical ranges, known quirks, source page references

**Test:** Hermes can configure a full site using any of the 5 models end-to-end: describe setup → lookup KB → propose plan → approve → create all entities → validate live readings.

**Dependency:** Requires actual manufacturer PDF documents. If PDFs unavailable, manually author KB entries from datasheet data as fallback.

---

### Phase 1H: Validation Layer 1 — Rule-Based

**Goal:** Hermes validates live readings against physical rules and flags impossible/inconsistent values.

**Scope:**
- Static threshold checks: voltage, current, PF, frequency, power, energy ranges (Indian industrial 3-phase)
- Cross-parameter consistency: `V_LN × √3 ≈ V_LL` (±5%), `P ≈ V × I × PF × √3` (±10%), `S² ≈ P² + Q²` (±5%), phase balance, frequency consistency
- Confidence scoring: combines rule results into High (>90%) / Medium (70-90%) / Low (<70%)
- Validation integrated into Hermes tool chain — called automatically after `test_device` or `read_live_values` during configuration
- Validation results included in NDJSON events and plan summaries

**Test:** Hermes reads values from a device, Layer 1 flags: "Voltage 415V PASS, PF 0.87 PASS, cross-check V_LN×√3=415.3 vs V_LL=415.2 PASS (0.02% deviation)". With bad data: "Current -5.2A FAIL — negative current on non-bidirectional meter".

---

### Phase 1I: Validation Layer 2 — Anomaly Detection Autoencoder

**Goal:** A lightweight neural network catches subtle issues that pass static rules — wrong byte order, reversed CT, misidentified meter model.

**Scope:**
- Autoencoder architecture: 3-layer (39 → 16 → 8 → 16 → 39), per MFM model family, <1MB, CPU inference
- Synthetic training data generator: create reading snapshots from KB `typical_range` with physically realistic correlations (P = V × I × PF × √3, S² = P² + Q², phase balance with realistic variance)
- Cold start training on synthetic data for all 5 KB models
- `run_anomaly_check(device_id)` tool: returns anomaly score (0-1) + per-parameter contribution (which fields drive the anomaly)
- Integrated into Hermes reasoning: called alongside Layer 1 during configuration, result influences confidence scoring
- Anomaly score thresholds: <0.2 normal, 0.2-0.5 moderate (investigate), >0.5 high (flag to engineer)

**Test:** Feed a reading snapshot with reversed CT (current values valid but power/PF relationship subtly wrong). Layer 1 passes (all values in range). Layer 2 flags anomaly score 0.72 with top contributors: `active_power`, `power_factor`. Hermes explains: "Power readings are inconsistent with the current and PF values — possible CT wiring issue."

---

### Phase 2A: Skills System

**Goal:** Hermes learns reusable procedures from successful sessions and applies them to future configurations.

**Scope:**
- Enable Hermes built-in skill tools in pipeline mode: `skills_list`, `skill_view`, `skill_manage`, `memory`, `session_search`, `clarify`
- Skill learning trigger: after `clean_run` sessions (no retries, no user corrections), Hermes proposes skills to save
- Skill retrieval: FTS5 search by tags/trigger at session start, inject top 3-5 into context
- Skill refinement: update existing skills when Hermes deviates and succeeds
- Skill deprecation: flag skills with high failure rate
- Skill API: `GET /ai/skills`, `GET /ai/skills/export`, `POST /ai/skills/import`, `DELETE /ai/skills/{id}`
- Sanitization: skills contain no site-specific data (IPs, device names stripped)

**Test:** Session 1: Hermes configures 10 PM5110s → clean_run → proposes skill "configure_schneider_pm5110_batch" → engineer approves. Session 2: "I have 20 PM5110s" → Hermes retrieves skill → executes faster with learned procedure.

---

### Phase 2B: Mode 2 — Network Discovery

**Goal:** Hermes can scan a network, find responding devices, identify them, and propose a full configuration.

**Scope:**
- Async network scanner: Python asyncio + pymodbus (Modbus TCP port 502) + opcua (OPC UA FindServers + Browse)
- Scan flow: ping sweep → port scan → unit ID enumeration (1-247, configurable) → register sweep
- Hermes drives discovery via diagnostic tools (`scan_port`, `read_raw_registers`, `browse_opcua_nodes`)
- Identification: KB fingerprint matching (register existence pattern + value range plausibility + byte order consistency + ID register)
- Candidate scoring: Hermes reasons about candidates, asks engineer to confirm uncertain identifications
- Full end-to-end: scan → identify → propose schema → propose mappings → propose jobs → approve → apply

**Test:** "Scan 10.10.1.0/24" → Hermes finds 15 responding devices → identifies 12 as PM5110 (high confidence), 2 as WM330 (medium), 1 unknown → proposes full config → engineer confirms unknowns → apply.

---

### Phase 2C: Layer 2 Warm-Up — Real Training Data

**Goal:** Anomaly detection improves by training on confirmed-good readings from real installations.

**Scope:**
- After each `clean_run` session: extract anonymized reading snapshots (parameter values + meter model, no IPs/names) and append to training dataset
- Anonymized training dataset export/import across deployments
- Retrain autoencoders on real + synthetic data mix
- Track model version + training data stats per MFM model family

**Test:** Anomaly autoencoder trained on synthetic data flags some borderline readings as moderate anomaly. After ingesting 50 real installation snapshots, the same readings score lower (model learned tighter real-world correlations).

---

### Phase 3A: Predictive Runtime — Statistical Baseline (Layer 3)

**Goal:** After logging starts, detect drift, trends, and anomalies in live data using statistical methods.

**Scope:**
- Statistical baseline: Z-score on rolling window + Holt-Winters exponential smoothing — immediate startup, no training delay
- `read_prediction_status(device_id)` tool: returns baseline status, current deviation, active alerts, trend summary
- Alerts via existing `app_notifications` system (type: "prediction")
- Baseline learning period: configurable (default: rolling window adapts in real-time)
- Per-device monitoring: lightweight, negligible memory per device

**Test:** Device logs for 24h. Voltage gradually drifts down 5% over 6 hours. Layer 3 detects trend: "voltage_l1n trending down 0.8%/hr, current deviation 2.1σ from baseline."

---

### Phase 3B: Layer 3 Upgrade — LSTM / Temporal Convolutional Network

**Goal:** Temporal pattern awareness — learns daily cycles, shift changes, seasonal patterns.

**Scope:**
- Small LSTM or TCN per device (~10-50KB per model, CPU inference)
- Trains on 3-7 day baseline (configurable)
- Load pattern classification: motor load vs lighting panel vs UPS vs mixed (based on PF profile, load curve shape)
- Temporal anomaly detection: "current is 40A at 3am — unusual for this device which normally drops to 5A overnight"
- Model persistence: save/load per device, retrain on schedule

---

### Phase 3C: Frontend Chat UI

**Goal:** Engineer interacts with Hermes via a chat panel in the React/Tauri desktop app.

**Scope:**
- Chat panel component (sidebar or dedicated tab)
- NDJSON event rendering: stage progress bars, plan display as structured card, approval buttons (approve/reject/edit)
- Session history: list past sessions, resume incomplete ones
- KB upload UI: drag-and-drop PDF, review extracted register map
- Skill viewer: browse learned skills, export/import

---

### Phase 3D: Advanced Capabilities

**Goal:** Long-term enhancements.

**Scope:**
- SLD topology inference from power flow patterns (incomer → feeder → sub-feeder based on power distribution)
- Skill marketplace: shared skill repository across deployments, versioned, rated by success rate
- Cloud fallback: Claude/Qwen API for uncertain identification when local model can't resolve
- Multi-session: parallel sessions for different sections of a large site

---

## Decisions Made

| Question | Decision |
|----------|----------|
| KB format | PDF source docs → Hermes extraction → JSON (versioned in repo) → SQLite at runtime |
| KB build | Hermes ingests manufacturer PDFs, engineer verifies. Not hand-authored. |
| Scanner language | Python asyncio (pymodbus for Modbus, opcua for OPC UA) |
| Non-standard Modbus | Flag for manual review — don't try to handle programmatically |
| OPC UA discovery | Use built-in FindServers + Browse — in scope from day one |
| Confidence thresholds | Configurable per session at creation time |
| Agent framework | NousResearch Hermes, in-process async task within FastAPI agent |
| Model | Qwen3.5-27B via local Ollama |
| System access | Full — internal functions (Tier 1) + raw store/DB (Tier 2) |
| Approval model | Plan-then-execute with trust tiers |
| Skills | Enabled in pipeline mode (unlike Neurareport), portable, learned from clean runs |
| Sanitization | Strip IPs/credentials before skills/memory, keep error types and counts |
| Token streaming | No — event-driven stage progress + final message (same as Neurareport) |
| Threading | Background thread for Hermes, NDJSON drain in main async loop |
| Trajectory capture | ShareGPT format, clean/failed split |
| OCR/Vision | GLM-OCR via Ollama for PDF register map extraction |
| Validation Layer 1 | Rule-based: static thresholds + cross-parameter checks (deterministic) |
| Validation Layer 2 | Anomaly detection autoencoder per MFM model family, CPU inference, synthetic cold start |
| Validation Layer 3 | Statistical methods first (immediate), LSTM/TCN upgrade later (needs baseline data) |
| Anomaly training data | Synthetic cold start → warm up from clean_run sessions → portable cross-deployment |
| Frontend | Deferred — backend + API first |

---

## Reference

- Existing API: `API_DOCUMENTATION.md`
- Site metadata example: `METADATA_DOCUMENTATION.md`
- Bulk import format: `bulk_import_297_devices.json`
- System requirements: `Codex/requirements.md`
- MFM register map example (39 fields): see `mfm` schema in metadata docs

---

## Reference Implementation: Neurareport V2

**For any doubts on how to implement Hermes, refer to the working production implementation at `/home/rohith/desktop/Neurareport V2/`.**

This is the authoritative reference for all Hermes integration patterns. The Neurareport V2 template creation pipeline uses the same NousResearch Hermes agent framework, the same Qwen3.5-27B model, the same Ollama runtime, and the same NDJSON streaming protocol that LoggerFast will use.

### Key Files and What to Learn From Each

| File | Path | Lines | What It Teaches |
|------|------|-------|-----------------|
| **Agent wrapper** | `backend/app/services/chat/hermes_agent.py` | 982 | How to wrap `AIAgent` in a background thread, drain NDJSON events in the main async loop, manage iteration limits and timeouts, handle session lifecycle |
| **Tool adapter** | `backend/app/services/chat/hermes_adapter.py` | 496 | How to register tools into Hermes's `ToolRegistry`, wrap async functions for Hermes's sync registry via `asyncio.run_coroutine_threadsafe()`, bridge callbacks to NDJSON events, enforce per-tool call limits, sanitize tool results |
| **Tool definitions** | `backend/app/services/chat/tools.py` | 3387 | How to define pipeline tools with state preconditions (`_require_state()`), structure learning signals, build error taxonomy, implement sanitization gate |
| **System prompt** | `backend/app/services/chat/hermes_system_prompt.py` | 550 | How to build a dynamic system prompt that injects current pipeline state, completed stages, and explicit next-step directives per turn |
| **Session model** | `backend/app/services/chat/session.py` | 327 | How to implement a state machine with hard-enforced transitions, persist session state, track completed stages |
| **Chat history** | `backend/app/services/chat/chat_history.py` | 110 | How to persist conversation history (user + assistant only, no intermediate tool calls) |
| **LLM config** | `backend/app/services/llm.py` | 176 | How to configure the OpenAI-compatible provider for Qwen + GLM-OCR vision model, env-driven settings |
| **API route** | `backend/app/api/routes/routes_a.py` | lines 7982-8128 | How to expose the chat endpoint (JSON + multipart upload), feature-flag between Hermes and fallback orchestrator |
| **Hermes framework** | `vendor/hermes-agent/run_agent.py` | 6000+ | The `AIAgent` class itself — tool-calling loop, memory, skills, session search, trajectory sampling, context compression, budget pressure |
| **Skills hub** | `vendor/hermes-agent/tools/skills_hub.py` | — | How Hermes skills are stored in `~/.hermes/skills/`, auto-generated from clean runs, retrieved per session |
| **Trajectory** | `vendor/hermes-agent/agent/trajectory.py` | 56 | ShareGPT format trajectory sampling for fine-tuning and debugging |

### Specific Patterns to Follow

**Threading model** (hermes_agent.py lines 664-697):
- Hermes `AIAgent.run()` executes in `asyncio.to_thread()` (background thread)
- Main async loop drains a sentinel queue for NDJSON events
- Tools registered as sync wrappers that bridge back to the event loop

**State-specific toolsets** (hermes_adapter.py lines 214-257):
- Each pipeline state has a minimal set of allowed tools
- Hermes only sees tools relevant to the current stage
- Reduces context window pressure and prevents invalid operations

**Call limits** (hermes_adapter.py lines 71-80):
- Per-tool call limits enforced at the adapter level, not via system prompt
- Hermes gets a structured error when a limit is hit, categorized in the error taxonomy

**Sanitization** (hermes_adapter.py line 183, tools.py lines 193-279):
- `_sanitize_for_agent()` runs on every tool result before Hermes sees it
- Strips semantic data that shouldn't leak into skills or memory
- Preserves error types and counts needed for immediate reasoning

**Dynamic system prompt** (hermes_system_prompt.py lines 329-425):
- Rebuilt on every turn with live context
- Injects: current state, completed stages, relevant counts, explicit next-step directive
- Learning rules section defines what Hermes should and should not persist

**Approval gate** (tools.py line 3225):
- `dry_run_preview` returns a verdict (PASS/WARN/FAIL)
- WARN requires explicit `user_approved_warnings=true` parameter to proceed
- No implicit approval — Python enforces, not the system prompt

**Learning signal** (tools.py lines 311-383):
- `clean_run` flag enables preferential skill learning from unretried, user-correction-free runs
- Patterns extracted as abstract observations, not site-specific data

**Feature flag** (routes_a.py):
- `PIPELINE_ORCHESTRATOR=hermes` env var selects the Hermes agent
- Fallback to classic orchestrator if Hermes/Ollama unavailable

### What to Fork vs. Reuse Directly

| Component | Action |
|-----------|--------|
| `vendor/hermes-agent/` | **Direct reuse** — vendor into LoggerFast as-is |
| `hermes_agent.py` | **Fork** — same wrapper structure, replace tool surface and session model |
| `hermes_adapter.py` | **Fork** — same registration/callback pattern, rewire to LoggerFast tools |
| `llm.py` | **Reuse** — same Qwen + GLM-OCR config, same env vars |
| `session.py` | **Fork** — same state machine pattern, rewrite states for LoggerFast pipeline |
| `hermes_system_prompt.py` | **Rewrite** — LoggerFast-specific persona, domain knowledge, state directives |
| `tools.py` | **Rewrite** — all LoggerFast domain tools (completely different pipeline) |
| `chat_history.py` | **Reuse** — same conversation persistence pattern |

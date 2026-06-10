# LoggerFast Backend — Production-Hardening Brief

**Audience:** the verification-and-fix agent.
**Purpose:** this is a *guide*, not a task list. It defines **what must be done and what "done" looks like** — not the exact steps. You own the investigation: explore the code, decide the how, verify, fix, and re-test.

**Scope note:** this brief is about **code quality, correctness, reliability, and bug-fixing** — taking the backend from pilot quality to a stable, maintainable, production-grade state. It is a hardening-and-bug-fix pass, not a rewrite.

---

## 0. Context & inputs

- The codebase is a PLC/Modbus/OPC-UA/MQTT → PostgreSQL data-logging backend (FastAPI config API + Rust acquisition engine).
- A prior production-readiness review exists in the repo as a **starting lead only** (`PRODUCTION_AUDIT_DETAILED.md`). Use it to orient yourself, but **re-verify everything yourself** — do not trust it blindly, and do not treat it as the full scope.
- The code is already reasonably structured. **This is a hardening pass, not a rewrite.**

---

## 1. Mission

- Take the backend from **pilot quality → production-ready**.
- Method: **end-to-end testing → find real failures → fix → re-test**, focused on **reliability, correctness, and usability**.

---

## 2. In scope

- End-to-end testing of real workflows, with multiple test cases.
- Finding and fixing **functional bugs and correctness issues**.
- **Reliability and resilience** — surviving restarts, device/DB outages, and bad input without crashing or losing data.
- **Data integrity** — no silent corruption, no precision loss, no silent NULLs hiding failures, no duplicate writes.
- **Usability** — clear errors, correct status codes, consistent API behavior.
- Removing **bloated / dead source code** where it clearly exists.

## 3. Out of scope

- **No large refactor / restructuring** — the structure is fine. Touch structure only where a fix genuinely requires it.
- **Do NOT delete build artifacts** (`dist/`, `node_modules/`, installers, etc.). "Bloat removal" means **dead/bloated source code only**.
- **AI pipeline = excluded (coming-soon feature):**
  - Do not test it, fix it, or count it as part of production.
  - **Keep all AI code in the repo** — do **not** physically strip it.
  - **Exclude it from the production build/runtime behind a feature flag** (default OFF). It must be cleanly dormant and re-enable-able later.

---

## 4. How to work (operating principles)

- **Verify → fix → re-verify.** Never fix blind. Confirm each issue is real before changing code, and prove the fix with a test afterward.
- **Evidence-based.** Every issue and fix should be backed by a reproduction or a passing/failing test.
- **Smallest safe change.** Prefer targeted fixes over sweeping edits. Don't introduce new structure unless required.
- **No regressions.** A fix in one area must not break another; keep the happy-path workflows working end to end.
- **Prioritize by risk:** data correctness & reliability first → usability → cleanup.

---

## 5. Jobs to be done

Each job below is an **outcome to achieve**, not a recipe. Decide the specifics yourself.

### J1 — End-to-end test coverage
- Stand up the full system and exercise real user/operator workflows from start to finish (config → device mapping → migration → job run → data written → read back).
- Cover happy paths **and** failure paths (bad input, device down, DB down, restart mid-run).
- Capture where it breaks across **usability, reliability, and data correctness**.
- **Done when:** the critical workflows have repeatable automated tests and a clear pass/fail report of where the system fails.

### J2 — Data integrity & engine correctness
- Ensure logged data is correct end to end: no silent corruption, no precision loss, no silent NULLs hiding failures, no duplicate/double-writes.
- Ensure writes are atomic/consistent where multiple steps or databases are involved.
- **Done when:** sampled device → DB values are provably correct, and failure conditions surface as explicit errors/metrics rather than silent bad data.

### J3 — Reliability & resilience
- Make the system survive real production conditions: transient DB/device/network failures, restarts, and shutdown — without crashing everything or losing in-flight data.
- Ensure graceful shutdown, recovery/reconnect, and that one failure doesn't take down all jobs.
- **Done when:** fault-injection tests (kill DB, drop device, send SIGTERM mid-write) recover cleanly with no data loss or stuck state.

### J4 — Usability & API consistency
- Exercise the API/operator experience: clear errors, correct status codes, sensible and consistent responses, predictable behavior.
- Flag and fix confusing or inconsistent behavior that would trip up a real integrator (mixed response shapes, business failures returned as HTTP 200, missing validation).
- **Done when:** the API behaves consistently and a new integrator can complete the core workflows without surprises.

### J5 — Bloat & dead-code removal
- Remove clearly dead or bloated **source** code (unused/duplicate logic, dead branches, abandoned paths).
- Do not over-reach — only remove what is provably unused and safe to drop.
- **Done when:** obvious dead/bloat source is gone, with no behavior change (tests still green). Build artifacts untouched.

### J6 — AI pipeline exclusion (feature-flagged)
- Put the entire AI pipeline behind a single feature flag, **OFF by default**, so the production build/runtime never loads or exposes it.
- Keep all AI code in the repo and re-enable-able for the future.
- **Done when:** the production build runs with zero AI routes/dependencies active, and flipping the flag cleanly restores it.

### J7 — Observability & operability
- Ensure an operator can run and debug this in production: sane logging (bounded/rotated, no noise), real health/readiness checks, and visibility into failures.
- **Done when:** failures are observable, logs are bounded, and health endpoints reflect true system state.

### J8 — Build & dependency integrity
- Ensure the production build is reproducible and trustworthy (pinned/locked dependencies, clean build that excludes the AI pipeline).
- **Done when:** a fresh build produces a consistent, AI-free, runnable artifact.

### J9 — Regression & final verification
- After all fixes, run the full end-to-end suite again to confirm everything works together and nothing regressed.
- **Done when:** the whole suite is green and a final report summarizes what was found, what was fixed, and residual risks.

---

## 6. Constraints / rules

- Keep AI code in the repo; only flag it off — never delete it.
- Don't delete build artifacts; bloat removal = source code only.
- No big restructuring; minimal, targeted changes.
- Every fix must be verified and regression-checked.
- Production build must exclude the AI pipeline.

---

## 7. Deliverables

- A working **end-to-end automated test suite** + a pass/fail findings report.
- **Fixes** for all confirmed correctness / reliability / usability issues.
- The **AI feature flag** (off by default) and an AI-free production build.
- A **final report**: what was found, what was fixed, how it was verified, and any residual risks left open.

---

## 8. Definition of done

- End-to-end workflows pass, including failure/recovery scenarios.
- No silent data corruption; failures are explicit and observable.
- AI pipeline fully excluded from production via flag (code retained).
- Dead/bloat source removed without regressions.
- Full suite green; final verification report delivered.

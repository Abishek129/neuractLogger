# LoggerFast production deployment (systemd)

Units in this directory:

| Unit | Runs | Why |
|---|---|---|
| `neuract-job-runner.service` | the Rust data engine (`neuract-job-runner`) | data acquisition + writes; `Restart=always` is the defense-in-depth for findings **C1** (meta-DB outage) and **H-ERR-4** (no respawn after crash) |
| `loggerfast-api.service` | the FastAPI control plane via uvicorn | config/metadata API; AI pipeline OFF by default (`LOGGER_ENABLE_AI` unset) |

Both units read all configuration from **`/etc/neuract/logger.env`**
(template: `deploy/logger.env.example`).

## Install steps

```bash
# 1. Service user + directories
sudo useradd --system --home-dir /var/lib/neuract --shell /usr/sbin/nologin neuract || true
sudo install -d -o neuract -g neuract /var/lib/neuract /var/log/neuract /opt/neuract/bin

# 2. Engine binary (build first: cd agent/rust_jobs && cargo build --release)
sudo install -m 0755 agent/rust_jobs/target/release/neuract-job-runner /opt/neuract/bin/

# 3. API code + virtualenv
sudo mkdir -p /opt/neuract/agent
sudo cp -r agent/plc_agent /opt/neuract/agent/
sudo python3 -m venv /opt/neuract/venv
sudo /opt/neuract/venv/bin/pip install -r requirements.txt uvicorn
sudo chown -R neuract:neuract /opt/neuract

# 4. Environment file (contains credentials -> root:neuract 0640)
sudo install -d -m 0750 -o root -g neuract /etc/neuract
sudo install -m 0640 -o root -g neuract deploy/logger.env.example /etc/neuract/logger.env
sudo $EDITOR /etc/neuract/logger.env   # set APP_DB_URL, KC_*, LOGGER_CORS_ORIGINS, ...

# 5. Units
sudo cp deploy/neuract-job-runner.service deploy/loggerfast-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now neuract-job-runner.service loggerfast-api.service

# 6. Verify
systemctl status neuract-job-runner loggerfast-api
journalctl -u neuract-job-runner -f
curl -s http://127.0.0.1:5175/health
```

## Operator notes

* **The engine must be restarted to pick up a new binary.** Deploying a new
  `neuract-job-runner` to `/opt/neuract/bin/` does nothing until you run
  `sudo systemctl restart neuract-job-runner`. The engine handles SIGTERM
  gracefully (drains pending writes, flushes batch buffers, exits 0), so a
  restart loses no buffered data. The same applies to the API
  (`sudo systemctl restart loggerfast-api`) after updating `plc_agent/`.
* **Database outages are non-fatal.** The engine reconnects to the metadata
  DB, the target DB(s) and the bench-metrics DB on its own with capped
  backoff; running jobs keep acquiring throughout a meta-DB outage. The
  systemd `Restart=always` is a second line of defense for crashes only.
* **Buffered-row cap.** During a target-DB outage, batched rows buffer up to
  `BATCH_BUFFER_CAP_ROWS` per table (default 10000); beyond that the oldest
  rows are dropped and the drop is logged + recorded in the error CSV.
* **Logs.** Engine stderr goes to journald (`journalctl -u
  neuract-job-runner`). The error CSV (`error_log_rust.csv`) lands in
  `RUST_BENCH_LOG_DIR` (default in the template: `/var/log/neuract`), capped
  by `LOGGER_ERROR_CSV_MAX_MB`. Rotating-file logs are capped by
  `LOGGER_LOG_MAX_MB` x (`LOGGER_LOG_BACKUPS`+1).
* **AI stays off** unless `LOGGER_ENABLE_AI=1` is explicitly set in
  `/etc/neuract/logger.env`.
* **Keycloak/CORS placeholders** (`LOGGER_CORS_ORIGINS`, `KC_REQUIRED_AZP`,
  `KC_ADMIN_CLIENT_SECRET`) MUST be replaced with real values; the committed
  defaults are deliberately non-functional.

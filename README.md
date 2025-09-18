# PLC Logger Workspace

This repository hosts the PLC Logger agent, desktop UI, and deployment assets. All written documentation now lives in the `Codex/` directory.

## Key Directories
- `agent/` - FastAPI backend and packaging scripts.
- `apps/desktop/` - React/Tauri desktop interface.
- `Codex/` - Centralised Markdown docs (requirements, runbooks, change logs).
- `scripts/` - Helper PowerShell utilities for local builds and service management.

## Getting Help
Consult `Codex/README.md` for the full functional overview. The other Markdown files inside `Codex/` retain their original names and act as focused guides (build commands, immediate requirements, historical logs, etc.).

## Contributing Notes
- Use the existing virtual environment/setup scripts inside `scripts/` for local development.
- Build artefacts land under `build/`, `dist/`, or `dist-tray/`; they are ignored by Git.
- Keep new documentation in `Codex/` to preserve the single-source structure.

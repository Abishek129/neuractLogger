# Production
- Plan: move agent writable data to `%LOCALAPPDATA%` during install (avoid ProgramData ACL issues)
- Plan: update installer to seed/apply ACLs if ProgramData is still used
- Plan: revisit manifest/UAC requirements after data path change

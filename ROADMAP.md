# Development roadmap

1. **Hardware acceptance:** test Neighborhood COM, drive enumeration, XEX read and launch on the target Windows/console setup. Capture sanitized operation outcomes only.
2. **Discovery integration:** consume Nebulah's normalized PathRegistry/application inventory, with per-console paths and no USB/HDD assumptions. Identify titles and distinguish games/homebrew using actual metadata.
3. **Plugin adapter:** negotiate supported JRPC/XRPC/Nebulah-service capabilities; implement explicit inspected plugin load/unload and slot management. No plugin loading until a tested runtime backend exists.
4. **Core telemetry:** initial temperature and running-title display implemented with optional JRPC reads; hardware validation remains. Next: friendly title metadata, supported uptime/memory/free-space figures. No invented values or private identifiers.
5. **RTE workspace:** screenshots, title-aware read-only inspection and controlled extensions. Design writes separately with title/version checks and rollback where possible.
6. **Mobile packaging:** retain the API boundary, add HTTPS/pairing UX, native shell or PWA packaging, reconnect and network discovery. Native packaging does not remove the need for the Windows Neighborhood bridge.
7. **Stable release:** signed/versioned host packaging, Windows CI and hardware regression checks before stable promotion.

## Games library follow-up

Implemented: target-scoped persistent folder/XEX shortcuts; game detail preview; bounded execution-info extraction; optional curated local artwork; per-file reviewed-baseline badges and launch enforcement.

Pending hardware and adapter work: automatic Aurora/XboxUnity metadata import, persistent cover indexing, trainer discovery/activation, title-update package discovery/compatibility and activation, and title/version-specific GSC applicability and injection. Current UI explicitly reports these extensions as unavailable. Never infer GSC support from `default_mp.xex` alone. Confirm the running title, exact version/TU and reviewed payload before enabling any future extension action. Keep trainer/plugin loading separate from title launching.

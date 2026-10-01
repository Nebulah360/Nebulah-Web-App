# Local API v0.1

All operations are `POST /api/<action>`, `Content-Type: application/json`, `Authorization: Bearer <pairing-token>`. The bridge requires the exact same `Origin` as its own HTTP host. The mobile browser receives the app from that same host. Tokens rotate on bridge restart and are not persisted in the UI. One console target is active per bridge instance; connecting changes it for all clients and invalidates outstanding launch tickets.

| Action | Request | Response |
|---|---|---|
| `connect` | `{ "target": "" }` | `type`, `kernel`, discovered `drives`, `temperatures`, `current_title` |
| `status` | `{}` | same explicit status allowlist |
| `browse` | `{ "path": "<discovered root or directory>" }` | `files`: name, directory, size |
| `validate` | `{ "path": "<absolute XEX path>" }` | valid, plugin, hash, checks, ticket |
| `launch` | `{ "ticket": "<validation ticket>" }` | `{ "accepted": true }` |

Tickets expire in 120 seconds, are single use, and bind to the inspected path/hash and active connection. Launch re-reads and revalidates the file. A successful response means the adapter accepted the command, not that the game finished booting. Plugin XEXs never receive a usable launch ticket. No generic COM/raw command endpoint exists.

Errors are JSON `{ "error": "..." }`; 400 validation/adapter rejection, 401 invalid token, 403 wrong Host/Origin, 502 unavailable local adapter, 504 timeout. Raw console exceptions and arbitrary COM objects are never returned.

Future native clients must use authenticated requests with the expected origin, or a separately designed and reviewed native-client authentication flow. No unrestricted CORS is planned.

## Read-only telemetry

`connect` and `status` now return `temperatures: {cpu, gpu, edram, motherboard}` (finite Celsius numbers or null) and `current_title: {executable, title_id}` (strings or null). Sensor support can be partial. Only these explicitly projected fields leave the bridge; raw COM/JRPC responses are not forwarded. The title ID is an eight-character uppercase hexadecimal application ID, not a console or account identifier. Zero/invalid/out-of-range sensor responses become null. An unsupported telemetry command does not fail the core status request.

The browser polls status every 10 seconds while visible and idle. Last-success age is measured in the browser, so the UI can mark stale data even if the bridge stops responding. No telemetry is saved in browser storage. `nebulah.accent` is the only saved browser preference.

## Explicitly confirmed CPU-key reveal

Both routes use the same pairing-token and same-origin protections as other API operations. `POST /api/cpu-key/prepare` with `{}` returns a `confirmation_ticket` valid for 60 seconds; it performs no console read. After the user confirms, `POST /api/cpu-key/reveal` with `{ "confirmation_ticket": "...", "confirmed": true }` returns `{ "cpu_key": "<32 uppercase hex characters>" }` if supported. Tickets are single-use, expire, and are invalidated on connect. Missing/false/non-boolean consent cannot invoke the adapter. An invalid or unsupported response fails closed with the generic error response; the raw plugin response is never returned. Status remains key-free. Consent is enforced as an API workflow; authenticated custom clients are responsible for presenting their own confirmation UI.

## Build registry

Authenticated `registry/list` returns `builds` plus the catalog content revision. `registry/check` takes `sha256`, integer `size`, and optional `build_id`; returns status, actual digest/size, expected record, matches, discrepancies and catalog revision. This is a caller-supplied digest lookup, not a server byte check, and always returns `eligible_for_install: false`. Neither route needs a console connection.

`validate` accepts optional `build_id` and now returns `size` and `verification` measured from actual console-file bytes. Revoked/mismatched/unknown-selected builds and registry errors get no launch ticket. Launch reloads the catalog to honor revocations and compares the bytes again. Unknown/unreviewed local applications retain manual structural launch behavior; they are not labeled reviewed. The CLI `tools/xex_registry.py verify FILE --build ID` provides the stricter actual-file, reviewed-only preinstall gate. See `registry/README.md` for status semantics and trust limitations.

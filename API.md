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

## Repositories and plugin inventory

All routes retain pairing-token and same-origin checks. No console is required for repository management.

- `repos/list {}` → preset/saved repositories and last-success snapshots.
- `repos/save {repository}` / `repos/remove {repository}` → save a canonical `owner/repo` or HTTPS GitHub URL, or remove a user-saved entry. Presets remain tracked.
- `repos/check {repository}` → metadata/revision for one saved repository, `first-check`, `changed`, `unchanged` or `unavailable`; `push_changed` is separate from default-branch `revision_changed`. On failure `last_success` is historical, not current. Partial release failures are `release_status: unavailable`.
- `plugins/list {}` → console observation state/items, loaded bundled backend components, and user metadata registrations.
- `plugins/register {name, version, repository}` → save metadata only, `loaded: false`; automatically track its repository.
- `plugins/remove {name}` → remove metadata registration only.

Limits: 50 repository subscriptions and 100 plugin registrations. Storage is host-local SQLite. API checks do not accept arbitrary URLs/hosts or fetch executable artifacts. A revision change is independent of reviewed-build hash verification and does not approve installation.

## Game shortcuts

Authenticated, same-origin requests require a connected console. Entries are scoped to the selected target name/IP; blank means the Neighborhood default profile.

- `POST /api/games/list` `{}` returns `shortcuts` with `id`, `name`, `folder`, and `executable`.
- `POST /api/games/save` `{name, folder, executable}` saves or renames the same folder/file shortcut. `executable` is an optional filename within the folder, or an empty string. The bridge verifies the discovered root, browses the folder, and checks file presence.
- `POST /api/games/remove` `{id}` removes only that target's shortcut. No console files are deleted.

These endpoints issue no launch tickets. Use the existing `validate` and confirmed `launch` flow.

`POST /api/games/inspect` `{path}` reads a console XEX and returns its filename, plugin flag, game verification report (including allowlisted execution metadata, optional local catalog artwork and reviewed references), and extension capability states. It does not launch, load plugins, or issue a launch ticket. Use one request per file to bound transfers; XEX inspection remains limited to 64 MiB. Trainer, title-update, and GSC actions are unavailable in the current adapter; unknown API operations are rejected. `validate` also returns `game_verification`, and game mismatch/revocation blocks ticket creation and launch.

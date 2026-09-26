# Local API v0.1

All operations are `POST /api/<action>`, `Content-Type: application/json`, `Authorization: Bearer <pairing-token>`. The bridge requires the exact same `Origin` as its own HTTP host. The mobile browser receives the app from that same host. Tokens rotate on bridge restart and are not persisted in the UI. One console target is active per bridge instance; connecting changes it for all clients and invalidates outstanding launch tickets.

| Action | Request | Response |
|---|---|---|
| `connect` | `{ "target": "" }` | `type`, `kernel`, discovered `drives` |
| `status` | `{}` | same explicit status allowlist |
| `browse` | `{ "path": "<discovered root or directory>" }` | `files`: name, directory, size |
| `validate` | `{ "path": "<absolute XEX path>" }` | valid, plugin, hash, checks, ticket |
| `launch` | `{ "ticket": "<validation ticket>" }` | `{ "accepted": true }` |

Tickets expire in 120 seconds, are single use, and bind to the inspected path/hash and active connection. Launch re-reads and revalidates the file. A successful response means the adapter accepted the command, not that the game finished booting. Plugin XEXs never receive a usable launch ticket. No generic COM/raw command endpoint exists.

Errors are JSON `{ "error": "..." }`; 400 validation/adapter rejection, 401 invalid token, 403 wrong Host/Origin, 502 unavailable local adapter, 504 timeout. Raw console exceptions and arbitrary COM objects are never returned.

Future native clients must use authenticated requests with the expected origin, or a separately designed and reviewed native-client authentication flow. No unrestricted CORS is planned.

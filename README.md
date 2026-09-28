# Nebulah Link — Xbox 360 web companion

Development foundation for [Nebulah Web App](https://github.com/Nebulah360/Nebulah-Web-App). A locally hosted, responsive browser UI with a Windows Neighborhood bridge. PC and phone browsers use the same API; the console connection stays on the Windows host.

**Status: v0.1 development foundation, not a console-verified stable release.** Python validation and API tests run without hardware. The Windows XDevkit COM adapter must be smoke-tested against the user's installed Neighborhood version before relying on live launch operations. No proprietary SDK files are bundled.

## Start on Windows

1. Install Python 3.10 or newer and your existing Xbox 360 Neighborhood installation. Confirm Neighborhood can browse the console first.
2. Download this repository with **Code → Download ZIP** and extract it, or clone it.
3. Double-click `start-local.cmd`.
4. Open `http://127.0.0.1:8765` in your browser.
5. Click **Connect console**, paste the pairing token printed in the terminal, and optionally enter the console's local IP or Neighborhood name. Blank uses Neighborhood's default.
6. Open **Applications**, select a discovered root, browse to an XEX, inspect it, then confirm launch.

The bridge defaults to 32-bit Windows PowerShell for XDevkit COM. If your COM registration uses another architecture, pass the appropriate executable:

```powershell
py -3 bridge/server.py --powershell C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe
```

## Open on your phone

Find the PC's private IPv4 address with `ipconfig`, then bind the bridge to that exact address. Example only — replace the address with your PC's address:

```powershell
py -3 bridge/server.py --host 192.168.1.50
```

Open the printed URL on the phone on the same private Wi-Fi and enter the printed pairing token. Allow the selected TCP port (default 8765) through Windows Firewall on the **Private** network profile if prompted. Keep the PC and terminal running. No PC/console IP is hard-coded.

LAN mode uses HTTP: pairing and traffic are not encrypted. Use only trusted private networks; do not expose or port-forward the bridge. HTTPS/reverse-proxy support is future work. The initial base binds one explicit interface and does not enable wildcard CORS.

## Included

- Responsive overview, console connection, storage browser, XEX inspection and confirmed application launch.
- Games and homebrew use their console-provided paths; storage roots are discovered via Neighborhood.
- Explicit demo mode with sample data; demo launch never sends a console command.
- Core status allowlist: console type, kernel, storage roots, supported temperatures, running executable and title ID. Unknown properties display unavailable.
- In-memory session activity; no persistent telemetry, console secrets, serials, account IDs, DVD keys, or keyvault endpoints. CPU-key access is a separate confirmed operation.
- Pairing token, same-origin requests, Host validation, request bounds, fixed adapter operations, and path validation.
- XEX2 structural checks, SHA-256 file identity, short-lived single-use launch tickets, re-read before launch, and DLL/plugin launch rejection.

Structural validation is **not signature verification**, publisher trust, full loader validation, or a compatibility guarantee. Files over 64 MiB are intentionally rejected by this initial inspector. A small external-write race remains between re-read and console launch; avoid simultaneous console file transfers during launch.

## Appearance and live overview

Use **Appearance** in the header to change the accent with the color wheel, brightness slider, RGB channels (0–255), or 3/6-digit HEX. The controls stay synchronized, preview immediately, and remember the chosen color in this browser. Reset restores Nebulah green. Button/card text automatically uses black or white for contrast; dark accents use a lighter related color for text on dark panels. Keyboard users can adjust hue with left/right, saturation with up/down, and brightness with its slider.

The overview includes CPU, GPU, eDRAM and motherboard temperatures, running executable, title ID, connection, console type, kernel and discovered root count. A sticky status bar keeps current title, CPU/GPU and update age visible across sections. Status is refreshed every 10 seconds while visible and idle; hidden tabs, open dialogs and active operations pause polling. Failed refreshes clear readings, and readings older than 30 seconds are labeled stale. Polling preserves the directory being browsed.

Temperature readings and title ID use **optional read-only JRPC v2 `consolefeatures`** commands through Neighborhood. A compatible console plugin must already be installed; this app does not install or load it. Unsupported sensors are unavailable, never zero or invented. The running executable uses Neighborhood's `RunningProcessInfo.ProgramName`; friendly game-name lookup is not implemented. Demo readings are explicitly labeled samples. The four accepted sensor values are finite numbers above 0 and no higher than 125 °C; outside-range responses display unavailable rather than a false reading.

The new COM telemetry path requires Windows/console verification; automated tests cover response projection and invalid readings, not hardware compatibility. Protocol reference: [JRPC client](https://github.com/XboxChef/JRPC/blob/master/JRPC_Client/JRPC.cs), fixed read operations 15 (temperatures) and 16 (title ID). Normal status polling issues no private-info commands.

## Plugin and RTE boundary

**Plugin runtime loading is not implemented in v0.1.** Plugins cannot be treated as ordinary title launches. The UI marks the loader unavailable. Future work needs a tested JRPC/XRPC or Nebulah service adapter with capability negotiation, compatibility checks and explicit load/unload operations. Screenshots, title-aware tooling and plugin-slot management are future work. No arbitrary command or memory-write endpoint is exposed.

## Architecture

```text
PC / phone browser → local Python HTTP API → Windows PowerShell → XDevkit COM → console
```

`dist/` contains dependency-free browser assets; `bridge/server.py` implements auth, routing, validation and adapter boundaries; `bridge/neighborhood.ps1` contains the Neighborhood COM integration. This separation allows a future native mobile client to reuse the local API. The mobile app will still need the PC bridge unless a separate console-side LAN service is implemented.

See [API.md](API.md), [ROADMAP.md](ROADMAP.md), and [AGENTS.md](AGENTS.md).

## Tests

```sh
python -m unittest discover -s tests -v
node --check dist/app.js
node --check dist/theme.js
node --test tests/theme.test.cjs
```

Node is only needed for the JavaScript syntax check, not to run the app. No npm install or third-party Python package is required.

## Console smoke-test checklist

- Confirm XDevkit COM creation in the chosen PowerShell architecture.
- Connect with both default Neighborhood target and explicit target.
- Verify discovered roots and directory entry shapes against actual COM responses.
- Verify available type/kernel fields; unsupported fields must stay unavailable.
- Inspect a known working homebrew XEX; verify hash against a local copy.
- Launch that homebrew after saving the current title's progress.
- Check malformed XEX and DLL modules cannot launch.
- Test a phone on the same trusted network, stale tickets, disconnected console and changed files.

Do not promote to the stable public release channel until this checklist passes. This repository is the user-designated development repository; do not mirror testing commits into Nebulah Dash's stable repository.

Protocol/architecture references: [XboxChef/XDCKIT](https://github.com/XboxChef/XDCKIT) and [Experiment5X/XBDM](https://github.com/Experiment5X/XBDM). These are reference implementations, not vendored dependencies. COM member compatibility remains a hardware validation item.

## Optional CPU-key display

On Overview, choose **Reveal CPU key…**, then **Confirm — read and display CPU key**. Opening the prompt does not read the key. Canceling sends no key-read command. The bridge requires a fresh 60-second single-use confirmation ticket and `confirmed: true` before invoking JRPC v2 type 10. Reconnecting invalidates pending confirmations. This requires compatible JRPC support and remains subject to hardware testing.

The key is shown only in the dedicated dialog. It is cleared after 60 seconds, on dialog close, tab hiding, navigation or connection changes. A late response after dismissal is discarded. It is never included in status polling, activity logs, localStorage, exports or automatic clipboard operations. Responses use `Cache-Control: no-store`; the bridge does not persist keys. This is transient handling, not a guarantee of secure erasure from process/browser memory. LAN HTTP remains unencrypted, which is stated in the confirmation prompt.

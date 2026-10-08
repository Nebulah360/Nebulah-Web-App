# Nebulah Link

**Your Xbox 360, from your browser.** See your console, manage files and games, and use supported plugin tools from a Windows PC or phone.

Nebulah Link connects through Xbox 360 Neighborhood on your PC. A phone reaches that PC over your private network. The console connection stays local.

> **Beta build:** Tested on one console setup. More hardware checks are needed before a stable release.

## Get started

**You need:** Windows 10 or 11 and a console you can browse in Xbox 360 Neighborhood on that PC.

1. Extract the full project folder onto your PC. The source ZIP uses Python 3.10 or newer; its launcher checks Python and can install it through WinGet.
2. Double-click `Start Nebulah Link.cmd`. If you chose the optional standalone Windows build, double-click `Nebulah-Link.exe` instead; it bundles Python but still needs Neighborhood.
3. Keep the bridge window open. Your browser opens and connects to Neighborhood's default console.

Press **Ctrl+C** in the bridge window to stop it. Only one bridge can run at a time.

### Use your phone

1. Double-click `Start Nebulah Link.cmd` on a trusted private network. The bridge prints a phone URL.
2. Connect the PC browser to your console and select **Show Phone PIN**.
3. On your phone, open the printed URL and enter that PIN.

Phone access is on for new installs. An existing saved choice to turn it off stays in effect. If this PC has no suitable private network address, run `& '.\Start Nebulah Link.cmd' --local-only` in PowerShell until it does.

The optional standalone build uses the same bridge and web UI. Build it on Windows with PyInstaller 6.22.3 using `tools/build-standalone.ps1`; distribute the entire resulting folder. Its executable is currently unsigned and needs a separate second-PC trial before public beta.

Use phone access only on a trusted private network. LAN traffic uses unencrypted HTTP. Never port-forward the bridge.

## What you can do

- See the running title and supported temperatures, capture the console screen, and use explicit power controls.
- Send controller button presses from the screen-capture panel with a compatible Companion module. Virtual input has been verified on Dash and the Borderlands 2 menu; other games are still being tested.
- Browse discovered storage, transfer files, organize games, and launch an inspected XEX after confirmation.
- Use **Settings** to choose a private default console IP, manage console profiles, or lock console write commands. Blank IP uses Neighborhood's default.
- Load compatible modules through Neighborhood or the optional Nebulah Companion manager. The manager can unload modules it loaded.
- View a supported live stream and inspect COD4's running title and XEX. Game stat editing is not available yet.

## Good to know

- XEX inspection checks file structure and identity. It does **not** prove a file is safe or compatible.
- Direct plugin unload, force release, boot plugin slot changes, memory writes, and Call of Duty rank, class, or unlock edits remain unavailable in this beta.
- Admin control on the bridge PC can override the app's write lock for the current console session. It does not bypass file inspection, beta gates, recovery holds, or fresh CPU-key consent.
- Private console information is hidden by default. Showing the CPU key requires fresh confirmation and hides it automatically.
- Keep the `.local` folder when updating; it holds your local settings and saved library.
- No games, mod menus, console binaries, or proprietary SDK files are included.

## Help and details

[Project website](https://nebulah.app/)

For help, use **Copy diagnostic** in the app, then [report an issue](https://github.com/Nebulah360/Nebulah-Web-App/issues/new) or [join Discord](https://discord.gg/QCQcXaz6RU). Never share pairing tokens, CPU keys, serials, account data, or keyvault material.

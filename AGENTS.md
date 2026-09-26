# Nebulah Web App agent instructions

- Work in this repository for the local companion app. Nebulah Dash console code is a separate project.
- Local Windows Neighborhood bridge + responsive phone/PC UI is the core architecture. Do not replace it with a cloud-to-console connection.
- Never request, read, expose or log private console keys, keyvault material, serials or account identifiers unless the user explicitly requests that separate feature. Keep status fields allowlisted.
- Discover storage roots; never assume Hdd/USB assignments or hard-code the user's testing drive.
- Launch only server-inspected XEX files through a short-lived single-use ticket. Preserve DLL/plugin rejection for title launches.
- Do not claim structural validation is cryptographic verification. Do not claim console compatibility based on mock tests.
- Do not implement runtime plugin loading through the title-launch operation. Use an explicit capability-gated adapter.
- Keep demo data labeled, separate from real connection state, and incapable of sending console operations.
- Run `python -m unittest discover -s tests -v` and `node --check dist/app.js` when changing the corresponding behavior.
- Use the hardware smoke-test checklist in README before calling a release stable.
- This is the development repository specified by the user. Stable promotion is separate; never push this work into Dash's stable repo automatically.

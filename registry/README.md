# Reviewed XEX build registry

This catalog records byte identity and review provenance, not a universal claim that a binary is safe. There is no complete trusted inventory here of “all known XEXs.” The initial catalog is intentionally empty; no real project build has yet been reviewed for inclusion. Never infer trust from `default.xex`, a repository name, a release tag, or an upstream-provided checksum alone.

## What is implemented

- SHA-256 and exact byte count for each executable, with project/version, canonical source repository, full source commit, and exact filename.
- Candidate, reviewed and revoked states. Reviewed records require reviewer/date, review evidence, and hardware-test evidence. These are maintainer attestations, not independently authenticated proof.
- Exact-build comparison showing expected/actual hash and byte size. A matching different build does not satisfy the selected build.
- Revocation overrides any reviewed record for the same digest. Revocations are reloaded before launch.
- Offline, read-only registry API, console-byte inspection and local downloaded-file verification CLI.
- No public enrollment endpoint, automatic trust-on-first-download, arbitrary URL downloader, or binary redistribution.

## Maintainer workflow

1. Obtain the exact released XEX from the project's canonical source or build it from a pinned source commit in an isolated, documented environment. Do not execute newly obtained code merely to hash it.
2. Record the asset source URL, acquisition date, release identifier, build toolchain and options in review evidence. A source SHA supplied on the CLI is a provenance claim; this tool does not prove the binary was built from that source.
3. Generate a candidate from the actual bytes:

   ```sh
   python tools/xex_registry.py propose path/to/default.xex --id project-1-release --project Project --version 1.0 --repository https://github.com/owner/repo --commit FULL_SOURCE_COMMIT
   ```

   It prints a candidate record; it does not modify or approve the catalog. Add the record under `builds` in `registry/catalog.json` through normal repository review. Different patched/debug/repacked XEX bytes need distinct build records. Archive hashes are not executable hashes.
4. Review source/provenance, compare independent publisher evidence when available, investigate discrepancies, and complete the applicable isolated test-console acceptance checks. Record actual results, limitations, tester and console configuration without secrets.
5. Only then change `state` to `reviewed` and add `review` with `reviewer`, `date` (YYYY-MM-DD), `evidence`, and `hardware_test` strings. Prefer links to durable review/test reports. Required fields do not themselves establish that review happened.
6. Run `python tools/xex_registry.py lint`, run the tests, and review/publish the catalog commit. Revoke a suspect record by setting `state: revoked` with a `revocation_reason`; retain historical metadata.

## Checking a repository download before installation

Stage the downloaded/extracted executable locally, then run:

```sh
python tools/xex_registry.py verify path/to/default.xex --build project-1-release
```

This hashes actual file bytes and performs existing structural XEX checks. Exit 0 requires an exact **reviewed match for the selected build**. Exit 2 means stop: unknown, candidate, mismatch, revoked, malformed XEX, or registry error. JSON includes actual hash/size, expected metadata, all matching records and discrepancies. Do not invoke an installer on exit 2. Reverify the exact staged bytes immediately before writing them; this command alone does not close a later file-replacement race. Read back installed bytes and compare before launch.

Repository download/install automation itself does not yet exist in Nebulah Link. This is its verification backend and CLI gate, not a claim that every future installer is already protected. Plugin files still need a separate compatible loader; a reviewed hash never authorizes treating a DLL as an application.

## Trust and updates

The catalog is versioned with the app's Git checkout. Only use a trusted maintainer-reviewed checkout. The catalog revision is a SHA-256 content fingerprint, **not a signature**. Local file modification can change trust; remote catalog refresh/signing/rollback protection is not implemented. Offline copies cannot learn newer revocations until updated. The UI must never advertise freshness or signature validation it has not established.

Ordinary user-requested console launches may still launch structurally valid unknown/candidate builds after the existing confirmation; they are labeled unreviewed. A selected-build mismatch, revocation, unknown selected ID or malformed/unavailable registry blocks the launch ticket. Future repository installs use the stricter reviewed-only gate above.

## Game baselines and artwork

`games.json` is separate from the source-build catalog. Retail game files do not require a GitHub source repository. No executable, proprietary game data, fabricated checksum, or approved retail reference is shipped.

Measure your own reference file:

```powershell
py -3 tools/game_baselines.py propose path\default_mp.xex --id game-release-mp --title "Game title" --provenance "Document the source and edition of this reference" --cover path\cover.jpg
py -3 tools/game_baselines.py lint
```

The proposal prints one candidate entry. Add it to the `builds` array in `registry/games.json`. Optional artwork must be a local PNG/JPEG no larger than 512 KiB and is embedded in the entry; the browser does not contact an artwork service. Only distribute artwork you have permission to include. Metadata/cover presentation is separate from verification.

Approval requires an independent review of the reference's unmodified provenance: set `unmodified` to `true`, `state` to `reviewed`, and add a `review` object with nonempty `reviewer`, ISO `date` (`YYYY-MM-DD`), `evidence`, and `hardware_test`. Merely copying these fields is not evidence. Never promote a file just because it runs or matches an untrusted published checksum. Proposals are never automatically approved.

Matching uses filename, Title ID, Media ID, raw file version and base version, then exact SHA-256 and size. Several reviewed references can represent legitimate variants. Green means exact bytes matching one of these reviewed unmodified references; it does not establish publisher authenticity or general safety. Red means different bytes from the available matching reference set, or a revoked hash. A mismatch can also indicate an unrecorded legitimate variant, not necessarily malicious modification. Missing references, other versions/media, and candidates stay gray/unknown. Revoked hashes are rejected regardless of filename. Set `state` to `revoked` with `revocation_reason` to revoke a reference.

Game previews show verification details and a check timestamp per XEX. They do not issue launch tickets. Launch re-reads the file and checks both catalogs, including revocations, before executing. Catalog errors fail closed. Game metadata extraction uses the bounded XEX execution-info header (`0x40006`); it excludes private console fields. File versions are not a report of the active title update.

Format reference: [Xenia Manager XEX execution-info structure](https://github.com/xenia-manager/xenia-manager/blob/main/source/XeniaManager.Core/Models/Files/Xex/XexExecutionInfo.cs).

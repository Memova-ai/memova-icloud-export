# Memova iCloud export V1

The Skill package version is `0.1.0`. The file protocol is `schema_version: 1`. The writer and reader can release independently while they preserve the V1 contract.

## Root and layout

The user sees iCloud Drive → Memova Exports → v1. Automatic Mac discovery checks these narrowly scoped candidate paths for the proposed production container, in the current user's home.

```text
~/Library/Mobile Documents/iCloud~ai~memova~exports/Documents/v1
~/Library/Mobile Documents/com~apple~CloudDocs/Memova Exports/v1
```

Development substitutes `iCloud~ai~memova~exports~dev` and `Memova Exports Dev`, and expects `environment: development`. These are discovery candidates. Registering the container and verifying which path iCloud exposes to the target Agent require a signed-device run. The reader validates the root marker and reports ambiguity if distinct paths match. A deliberately supplied directory may be the parent of `v1` or the export directory itself.

```text
v1/
  format.json
  YYYY-MM-DD/
    manifest.json
    results/<revision>/daily-summary.md
    transcripts/<revision>/{hourly,meetings}/<recording-key>.json
    audio/<revision>/{hourly,meetings}/<recording-key>.<ext>
```

Dates are real Gregorian archive dates. Store a cross-midnight phone meeting under its start date. Use the original archive recording ID bytes in UTF-8 to compute the lowercase SHA-256 `recording-key`. Paths use exact lowercase category names, revision UUIDs and extensions. `hourly` maps to kind `hourly` and `meetings` to kind `phone_meeting`. Allowed audio extensions are `m4a`, `caf`, `wav`, `mp3` and `aac`. These are ordinary files.

## JSON schemas and semantics

- [format.json](schemas/format-v1.schema.json) identifies the protocol, environment and anonymous publisher UUID. The day manifest uses the same publisher UUID.
- [manifest.json](schemas/manifest-v1.schema.json) binds one commit ID to one archive date and has all three category keys. It refers only to the current published revision of each category. The writer sorts each category's file array by relative path and supplies actual payload byte counts and lowercase SHA-256. Unknown additive fields may be ignored. JSON duplicate keys and non-finite numbers are invalid.
- [Per-recording transcript](schemas/transcript-v1.schema.json) binds the recording ID, kind and date to its manifest entry. Sentences retain archive position order. ID uniqueness is per recording. Use RFC 3339 timestamps with offsets, nullable IANA time zones and explicit nulls for unknown data. `committed_at` and per-type `updated_at` are UTC. Anonymous speaker identifiers such as `speaker-01` apply within the file. `is_self` is true, false or null.
- The daily summary is UTF-8 Markdown with an archive-day title and the available daily review and event sections. The audio entry contains original bytes. Neither uses a JSON payload wrapper. All JSON and Markdown use UTF-8 without BOM. Published transcript files contain at least one sentence.

Structural schemas describe field shapes. The reader also validates path derivation, sorted unique entries, dates and identity, finite ordered ranges, publisher and category relationships, and actual file bytes. The date and active revision control reads. The reader never resolves a payload through obsolete version enumeration.

| Manifest state | Revision and update time | Files |
| --- | --- | --- |
| `ready` | Required | One or more. Results have one |
| `empty` | Required | None. The source query found no exportable material |
| `deleted` | Required | None. A user withdrew the export |
| `never_exported` | Both null | None |

Audio pairing requires the same recording ID and kind, a transcript `audio_sha256` equal to the actual verified audio SHA-256, and a populated valid sentence range. The writer checks offsets against the known length of the source audio. The reader checks binding and finite ranges. Independent re-exports can produce a mismatch or leave the transcript unbound, and its text remains usable. When writing transcripts alone, use null for `audio_sha256` and for the audio ranges.

The reader checks the current manifest again after reading its files and retries once if it changed. macOS metadata distinguishes known conflicts, stale copies, undownloaded files and Finder aliases. Non-Mac local copies cannot expose iCloud metadata. A validated report always represents files visible to that device and its runtime. A checksum binds content to a manifest and does not authenticate who authored it.

## CLI and compatibility check

Use Python 3.9+ on a POSIX filesystem with descriptor-relative opens. Automatic discovery uses macOS and the included Foundation metadata helper. An explicitly supplied copy can be validated on a supported non-Mac POSIX system. These commands are from the Skill directory.

```bash
python3 -B scripts/read_export.py list
python3 -B scripts/read_export.py read --date 2026-11-24 --type results --type transcripts
python3 -B scripts/read_export.py read --latest --type results
python3 -B scripts/read_export.py validate --root assets/synthetic
python3 -B scripts/read_export.py validate --root "/path/to/App-generated export" --date 2026-11-24
```

App QA can set `--environment development` for a development export. `validate` verifies all three content categories and outputs metadata and counts, including verified audio pairings where both files exist. It emits no payload text or bytes. Use `--date` repeatedly to target specific dates. Without a date this command validates all date directories in the supplied root. `list` enumerates date directories only and does not promise they have manifests or data.

`read` requires an explicit archive date or `--latest`. The default types are results and transcripts. Repeat `--type` to override that selection. Explicit audio selection returns verified relative file locators and never emits audio bytes. With transcripts also selected, matching evidence carries sentence offsets. `--recording-id` filters recording files, and `--sentence-id` and `--contains` filter transcript evidence. Coverage counts distinguish the manifest file count, verified file count and matched sentences. The text excerpt budget defaults to 24,000 characters with up to 200 evidence entries. Its accounting includes citation overhead. For long Markdown, `next_offset` advances through Unicode characters. `--timeout` can increase the default 60-second operation deadline for a deliberate larger validation.

A `ready` publication with readable payloads yields per-type `readable`. `no_match` means a recording or text filter had no hits. A missing or invalid payload leaves that category without evidence and preserves other validated categories. `file_missing`, `not_downloaded`, `stale`, `icloud_conflict`, `permission_denied` and `integrity_mismatch` describe distinct failures. A missing day manifest yields `manifest_not_found`. A known newer schema yields `unsupported_version`. A root error produces a top-level status. `--latest` includes skipped newer dates and only returns a day with a readable requested category.

Exit status 0 means the requested inspection completed, including valid empty, deleted, unexported or no-match states. Status 1 means at least one requested day or type could not be fully verified, or no readable latest date was found. Status 2 means an invalid invocation, unavailable root or whole-operation error. A successful zero exit applies to the reported coverage and does not imply every possible type was published.

Input bounds are 16 KiB for `format.json`, 16 MiB per manifest, 64 MiB per transcript and 4 MiB per Markdown file. Audio is checked in blocks. Files must be regular and directly inside the validated directory tree. Symbolic links, Finder aliases, hard links shared with other paths and out-of-contract paths are rejected. Root discovery never searches unrelated folders. User material remains read-only and the reader does not maintain a persistent content index.

The [synthetic fixture](../assets/synthetic/v1/format.json) includes a complete hour with two seconds of synthetic silence and a separate phone meeting spanning midnight. The fixture contains no actual recordings.

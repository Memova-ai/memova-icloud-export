# Memova Local iCloud sync V1

The iPhone App publishes plain files under Finder → iCloud Drive → Memova Exports → app-v1. The development App uses Memova Exports Dev → app-v1. The reader checks these two macOS representations of the production folder.

```text
~/Library/Mobile Documents/iCloud~ai~memova~exports/Documents/app-v1
~/Library/Mobile Documents/com~apple~CloudDocs/Memova Exports/app-v1
```

Development uses `iCloud~ai~memova~exports~dev` and `Memova Exports Dev`. Use `--environment development` for development data. The reader's default discovery prefers App V1. It tries the [public preview](v1-export.md) only when both App V1 directory candidates are absent. An existing but unavailable or invalid App V1 root yields a diagnostic. Use `--root` with an authorized copy of either export directory or its parent.

## Layout

```text
app-v1/
  format.json
  YYYY-MM-DD/
    manifest.json
    transcripts/{hourly,meetings}/<recording-key>/<sha256>.json
    events/<item-key>/<sha256>.md
    daily_reviews/<item-key>/<sha256>.md
    audio/{hourly,meetings}/<recording-key>/<sha256>.<ext>
    meeting_notes/<item-key>/<sha256>.md
    favorites/{event,daily_review,meeting}/<item-key>/<sha256>.md
```

`recording-key` and `item-key` are lowercase SHA-256 of the UTF-8 `recording_id` and `item_id`. The filename hash is the lowercase SHA-256 of the full payload bytes. The reader uses only files listed in the active day manifest. A changed item gets a new content-addressed path. Other items can retain their existing paths even when a category's revision changes.

## Format marker and day manifest

`format.json` has `format: "memova-icloud-sync"`, integer `schema_version: 1`, `environment` of `production` or `development`, and lowercase UUID `publisher_id`. The public preview has a different marker and directory layout.

A day manifest has integer `schema_version: 1`, Gregorian `archive_day` matching the directory, its root's `publisher_id`, lowercase UUID `commit_id`, UTC RFC 3339 `committed_at`, and `contents` with exactly the six categories listed above. Its category object holds `state`, `revision`, `updated_at`, and `files`. Sorted unique paths are required, and file entries include `path` relative to the day directory, positive integer `byte_count` and `sha256`.

| State | Revision and update time | Files |
| --- | --- | --- |
| `never_exported` | Both null | None |
| `ready` | Lowercase UUID and UTC RFC 3339 timestamp | One or more |
| `empty` | Lowercase UUID and UTC RFC 3339 timestamp | None. The source had no publishable items |
| `deleted` | Lowercase UUID and UTC RFC 3339 timestamp | None. The last previously published item was removed |

A paused switch preserves the previous cloud publication. State shows what the manifest publishes on this Mac's snapshot. After resuming, iCloud can take time to deliver updates, including deletions. A deleted or empty manifest category has no usable payloads even if an obsolete file is still visible.

## File entries and content

| Category | Additional manifest entry fields | Content |
| --- | --- | --- |
| `transcripts` | `recording_id`, `kind` | UTF-8 JSON using the [transcript schema](schemas/transcript-v1.schema.json) |
| `events` | `item_id`, `kind: event` | Standalone UTF-8 Markdown for one event |
| `daily_reviews` | `item_id` equal to the archive day, `kind: daily_review` | UTF-8 Markdown, at most one daily review per day |
| `audio` | `recording_id`, `kind` | Original file bytes with extension `m4a`, `caf`, `wav`, `mp3`, or `aac` |
| `meeting_notes` | `item_id`, `kind: meeting` | Standalone UTF-8 Markdown for one meeting note |
| `favorites` | `item_id`, `kind` of `event`, `daily_review`, or `meeting`, UTC RFC 3339 `favorited_at` | A standalone UTF-8 Markdown copy of the human-readable title and content |

JSON and Markdown use UTF-8 without a BOM. A favorite is independently readable even when the respective source category was never synced. A daily review favorite keeps its archive day as its item ID. Original audio and full transcripts are published through their own categories.

Recording kinds `hourly` and `phone_meeting` use directories `hourly` and `meetings`, respectively. The meeting's archive day is its start date. A spoken timestamp can extend past midnight. The reader binds sentence offsets to audio only when the audio was requested, the recording ID and kind match, and the transcript's audio hash matches the verified audio. The text remains usable when the selected recording bytes have a different hash or the transcript has no offsets.

## Reader and compatibility check

```sh
python3 -B scripts/read_export.py list
python3 -B scripts/read_export.py read --date 2026-11-24 --type events --type daily_reviews
python3 -B scripts/read_export.py read --latest --type meeting_notes
python3 -B scripts/read_export.py read --date 2026-11-24 --type favorites --item-kind event --item-id '<item ID>'
python3 -B scripts/read_export.py validate --root "/path/to/app-v1" --date 2026-11-24
```

The report's `format` identifies which categories are available. The App V1 default read selects events, daily reviews and transcripts. Use an explicit `--type audio` to check the original recording and get a locator. The reader never returns audio bytes. `validate` verifies all six categories and reports counts with no payload text or bytes.

For Markdown pagination, use `--item-id` and, for favorites with overlapping identities, `--item-kind` to select the evidence item. Continue its `next_offset` using `--markdown-offset`. Start at zero for a different item. `next_item` gives the first verified Markdown identity that did not fit in the remaining output budget. Check the day `commit_id` across pages and restart a changed day. Cite the archive day and the returned path or item ID with the available title or heading. A favorite also supplies `favorited_at`.

The reader checks path layout, byte count, SHA-256, root binding and the active manifest after reading. Its statuses and input bounds are described in the [preview reference](v1-export.md#cli-and-compatibility-check). A synthetic result validates the file contract. The actual iCloud path and device-to-Mac delivery require a signed iPhone and the Mac Agent's local iCloud session.

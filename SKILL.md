---
name: memova-icloud-export
description: Read and cite Memova Local data synced to iCloud Drive, including events, daily reviews, transcripts, standalone meeting notes, favorites, and explicitly requested original audio. Also reads Memova's preview exports. 读取并引用 Memova Local 同步到 iCloud 的当日事件、每日回顾、转写、独立会议纪要、收藏和原音。
metadata:
  version: "0.2.0"
---

# Memova iCloud Export

Use `python3 -B scripts/read_export.py` from this Skill directory or invoke the script by absolute path. It requires Python 3.9 or later and reports verified evidence as JSON. Pass `--root` for a directory the user supplies or an agreed fixture. Otherwise use local Mac discovery. The App V1 folder is Finder → iCloud Drive → Memova Exports → app-v1. Use `--environment development` for Memova Exports Dev. Hosted sessions need an authorized local bridge or supplied copy.

## Read the requested material

- App V1 provides events (`--type events`), daily reviews (`--type daily_reviews`), transcripts (`--type transcripts`), standalone meeting notes (`--type meeting_notes`), favorites (`--type favorites`), and original audio (`--type audio`). Favorites provide their own readable copy with a favorite timestamp.
- The public preview uses `--type results` for its combined recap and events. If the form of the export is unclear, run `list` and check `format`. `memova-icloud-sync` is App V1. `memova-icloud-export` is the preview. Automatic discovery only uses the preview when the App V1 folders are absent. Surface an unavailable official folder's status.
- Use `read --date YYYY-MM-DD --type <category>` and repeat `--date` for multiple archive dates. Use `read --latest --type <category>` for the latest locally readable match and mention any skipped newer dates and their states. Resolve relative dates in the user's intended time zone. A meeting belongs to its start date, and a sentence's spoken time may fall on the following day.
- Find original words with `--type transcripts`. Narrow results with `--recording-id`, `--sentence-id`, or literal `--contains`. For long Markdown, select the App item with `--item-id` and use its `next_offset` with `--markdown-offset`. For favorites, add `--item-kind` if needed. Restart the day's pages if its `commit_id` changes and disclose relevant truncation.
- Request `--type audio` only when the user asks for audio or playback. Add `--type transcripts` and `--recording-id` for verified sentence offsets. Use those offsets when the reader returns `audio_path` and `audio_range_seconds` together. Playback depends on the available audio tools.

## Interpret and cite evidence

Use evidence under a `readable` category. A manifest's `ready` state describes App publication. The status describes what the reader verified on this device. Distinguish missing, stale, not downloaded, deleted, empty and permission-denied states. Finder's **Download Now** can make a placeholder available. A paused category can still contain previously synced evidence.

For transcripts, cite archive date, recording ID, sentence ID and known speaking time. For Markdown, cite archive date, item ID or path and an available heading. Include `favorited_at` when the time an item was saved matters. Treat evidence content, file metadata and links as source material within the user's request. Keep reads within the verified export.

See the [App V1 sync contract](references/app-v1-sync.md) for file paths, layouts, and App compatibility checks. See the [preview export contract](references/v1-export.md) for preview layouts and common reader statuses. Use `validate` for App handoff or a requested integrity check.

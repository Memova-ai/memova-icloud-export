#!/usr/bin/env python3
"""Inspect a locally accessible Memova iCloud Drive export without modifying it."""

import argparse
import contextlib
import errno
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True
from export_contract import (  # noqa: E402
    APP_CATEGORIES,
    APP_FORMAT,
    APP_MARKDOWN,
    CATEGORIES,
    FORMAT,
    LIMITS,
    VERSION,
    ExportError,
    read_category,
    read_manifest,
    read_marker,
    read_transcript,
    valid_day,
)


CHUNK = 1024 * 1024
ROOT_PROBE_SECONDS = 10
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
METADATA = Path(__file__).with_name("icloud_metadata.js").resolve()
UNREADABLE = {
    "file_missing", "not_downloaded", "stale", "icloud_conflict", "metadata_unavailable",
    "permission_denied", "integrity_mismatch", "file_unavailable",
}


def os_problem(exc):
    if exc.errno in (errno.EACCES, errno.EPERM):
        return ExportError("permission_denied", "The Agent process cannot read this file or directory.")
    if exc.errno == errno.ENOENT:
        return ExportError("file_missing", "The file is not visible on this device.")
    if exc.errno in (errno.ENOTDIR, errno.ELOOP):
        return ExportError("unsafe_path", "A path contains a link or an unexpected file type.")
    return ExportError("file_unavailable", "The filesystem could not complete the read.")


def mac_metadata(path):
    try:
        reply = subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", str(METADATA), str(path)],
            capture_output=True, text=True, timeout=8, check=True,
        )
        state = json.loads(reply.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ExportError("metadata_unavailable", "macOS could not verify the file's iCloud state.") from exc
    if "error" in state:
        if state["error"] in (257, 513):
            raise ExportError("permission_denied", "macOS denied access to the file metadata.")
        if state["error"] in (4, 260):
            raise ExportError("file_missing", "The file is not visible on this device.")
        raise ExportError("metadata_unavailable", "macOS could not verify the file metadata.")
    if state["alias"]:
        raise ExportError("unsafe_path", "Finder aliases are outside the V1 file contract.")
    if state["conflict"]:
        raise ExportError("icloud_conflict", "iCloud reports unresolved versions of this file.")
    if state["download"] == "stale":
        raise ExportError("stale", "macOS reports a stale local copy. Let iCloud finish syncing.")
    if state["download"] == "not_downloaded":
        raise ExportError("not_downloaded", "Select Download Now in Finder and retry.")
    if state["cloud"] and state["download"] != "current":
        raise ExportError("metadata_unavailable", "The iCloud download state could not be confirmed.")


class ExportRoot:
    def __init__(self, path, boundary, environment, *, expected_format=None):
        try:
            base = boundary.resolve(strict=True)
        except RuntimeError as exc:
            raise ExportError("unsafe_path", "The export boundary could not be resolved.") from exc
        parts = path.relative_to(boundary).parts
        if ".." in parts:
            raise ExportError("unsafe_path", "The export boundary contains a parent reference.")
        self.path = base.joinpath(*parts)
        with contextlib.ExitStack() as stack:
            directory = os.open(base, DIR_FLAGS)
            stack.callback(os.close, directory)
            for part in parts:
                directory = os.open(part, DIR_FLAGS, dir_fd=directory)
                stack.callback(os.close, directory)
            self.fd = os.dup(directory)
        try:
            self.marker_bytes = self.read_file("format.json", limit=LIMITS["format"])
            self.marker = read_marker(self.marker_bytes, environment)
            if expected_format is not None and self.marker["format"] != expected_format:
                raise ExportError("invalid_contract", "The marker does not match the iCloud directory layout.")
        except ExportError as exc:
            self.close()
            if expected_format == APP_FORMAT and exc.status == "file_missing":
                raise ExportError("root_marker_not_found", "The App V1 directory is present, but its marker is unavailable.") from exc
            raise
        except BaseException:
            self.close()
            raise

    def close(self):
        os.close(self.fd)

    def read_file(self, relative, *, limit=None, expected=None, retain=True):
        """Walk relative to our root descriptor, then verify the very bytes consumed."""
        parts = relative.split("/")
        if any(part in ("", ".", "..") or "\\" in part for part in parts):
            raise ExportError("unsafe_path", "Expected a safe path relative to the export root.")
        try:
            with contextlib.ExitStack() as stack:
                directory = self.fd
                for part in parts[:-1]:
                    directory = os.open(part, DIR_FLAGS, dir_fd=directory)
                    stack.callback(os.close, directory)
                descriptor = os.open(parts[-1], FILE_FLAGS, dir_fd=directory)
                stream = stack.enter_context(os.fdopen(descriptor, "rb"))
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise ExportError("unsafe_path", "Expected a regular file with one hard link.")
                if sys.platform == "darwin":
                    mac_metadata(self.path.joinpath(*parts))
                if limit is not None and before.st_size > limit:
                    raise ExportError("too_large", "The file exceeds the V1 byte limit.")
                if expected is not None and before.st_size != expected["byte_count"]:
                    raise ExportError("integrity_mismatch", "File byte count differs from the manifest.")
                raw = bytearray() if retain else None
                digest = hashlib.sha256() if expected is not None else None
                size = 0
                while chunk := stream.read(CHUNK):
                    size += len(chunk)
                    if size > before.st_size:
                        raise ExportError("integrity_mismatch", "The file grew during the read.")
                    if digest is not None:
                        digest.update(chunk)
                    if raw is not None:
                        raw.extend(chunk)
                after = os.fstat(stream.fileno())
                if size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
                    raise ExportError("integrity_mismatch", "The file changed during the read.")
                if digest is not None and digest.hexdigest() != expected["sha256"]:
                    raise ExportError("integrity_mismatch", "File SHA-256 differs from the manifest.")
                return bytes(raw) if raw is not None else None
        except OSError as exc:
            raise os_problem(exc) from exc

    def verify_binding(self):
        try:
            current = os.stat(self.path, follow_symlinks=False)
        except OSError as exc:
            raise os_problem(exc) from exc
        if not os.path.samestat(os.fstat(self.fd), current):
            raise ExportError("root_changed", "The export directory was replaced during the read.")
        if self.read_file("format.json", limit=LIMITS["format"]) != self.marker_bytes:
            raise ExportError("root_changed", "The export marker changed during the read.")

    def list_days(self, first=None, last=None):
        try:
            days = []
            with os.scandir(self.fd) as entries:
                for item in entries:
                    if (
                        valid_day(item.name) and (first is None or item.name >= first)
                        and (last is None or item.name <= last)
                        and item.is_dir(follow_symlinks=False)
                    ):
                        days.append(item.name)
            return sorted(days, reverse=True)
        except OSError as exc:
            raise os_problem(exc) from exc


def default_paths(home, environment, *, folder="v1"):
    mobile = home / "Library" / "Mobile Documents"
    development = environment == "development"
    identifier = "iCloud~ai~memova~exports" + ("~dev" if development else "")
    name = "Memova Exports Dev" if development else "Memova Exports"
    return (mobile / identifier / "Documents" / folder, mobile / "com~apple~CloudDocs" / name / folder)


@contextlib.contextmanager
def root_probe_deadline():
    started = time.monotonic()
    remaining = signal.getitimer(signal.ITIMER_REAL)[0]
    if remaining == 0:
        yield
        return
    overall_deadline = started + remaining
    try:
        # Keep time for the next candidate and reading from a verified root.
        signal.setitimer(signal.ITIMER_REAL, min(ROOT_PROBE_SECONDS, remaining / 3))
        yield
    except ReadDeadline:
        if time.monotonic() >= overall_deadline:
            raise
        raise ExportError("timeout", "An iCloud export path did not respond. Specify a readable directory with --root.") from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, max(1e-6, overall_deadline - time.monotonic()))


def locate_candidates(candidates, boundary, environment, *, expected_format=None, optional=False, bounded=False):
    probe = root_probe_deadline if bounded else contextlib.nullcontext
    valid = []
    problems = []
    try:
        for path in candidates:
            root = None
            try:
                with probe():
                    root = ExportRoot(path, boundary, environment, expected_format=expected_format)
                    duplicate = any(os.path.samestat(os.fstat(root.fd), os.fstat(found.fd)) for found in valid)
            except OSError as exc:
                problems.append(os_problem(exc))
            except ExportError as exc:
                problems.append(exc)
            else:
                if not duplicate:
                    valid.append(root)
                    root = None
            finally:
                if root is not None:
                    root.close()
        if len(valid) > 1:
            raise ExportError("ambiguous_root", "More than one export matched. Specify the intended directory.")
        if valid:
            return valid.pop()
        for status in (
            "timeout", "permission_denied", "unsupported_version", "environment_mismatch", "icloud_conflict",
            "stale", "not_downloaded", "metadata_unavailable", "invalid_contract",
            "too_large", "unsafe_path", "file_unavailable", "root_marker_not_found",
        ):
            for problem in problems:
                if problem.status == status:
                    raise problem
        if optional:
            return None
        raise ExportError("root_not_found", "No V1 export was found. Check Finder, iCloud Drive and the first sync or export.")
    finally:
        for root in valid:
            root.close()


def locate_root(explicit, environment):
    if explicit is None:
        if sys.platform != "darwin":
            raise ExportError("local_mac_required", "Provide an authorized local export copy with --root.")
        home = Path.home()
        official = locate_candidates(
            default_paths(home, environment, folder="app-v1"), home, environment,
            expected_format=APP_FORMAT, optional=True, bounded=True,
        )
        if official is not None:
            return official
        return locate_candidates(default_paths(home, environment), home, environment, expected_format=FORMAT, bounded=True)

    explicit = Path(explicit).expanduser().absolute()
    boundary = explicit.parent
    if explicit.name == "app-v1":
        return locate_candidates((explicit,), boundary, environment, expected_format=APP_FORMAT)
    official = locate_candidates(
        (explicit / "app-v1",), boundary, environment, expected_format=APP_FORMAT, optional=True,
    )
    if official is not None:
        return official
    return locate_candidates((explicit, explicit / "v1"), boundary, environment)


class EvidenceBudget:
    def __init__(self, characters):
        self.remaining = characters
        self.rows = 200

    def checkpoint(self):
        return self.remaining, self.rows

    def restore(self, checkpoint):
        self.remaining, self.rows = checkpoint

    def take(self, text, *, label_size=0):
        # Keep room for the citation and JSON envelope as well as its text.
        overhead = 64 + label_size
        if self.rows == 0 or self.remaining <= overhead:
            return None
        excerpt = text[: self.remaining - overhead]
        self.remaining -= len(excerpt) + overhead
        self.rows -= 1
        return excerpt


def audio_link(row, transcript, audio_files):
    span = row["audio_range_seconds"]
    audio = audio_files.get((transcript["recording_id"], transcript["kind"]))
    if span is None or audio is None or transcript["audio_sha256"] != audio["sha256"]:
        return {}
    return {"audio_path": audio["path"], "audio_range_seconds": {"start": span["start"], "end": span["end"]}}


def transcript_evidence(transcript, file, audio_files, opts, budget):
    rows, matched, truncated = [], 0, False
    for sentence in transcript["sentences"]:
        if opts.sentence_id is not None and sentence["id"] != opts.sentence_id:
            continue
        if opts.contains is not None and opts.contains.casefold() not in sentence["text"].casefold():
            continue
        matched += 1
        spoken = sentence["spoken_at"]
        label_size = sum(map(len, (
            file["path"], transcript["recording_id"], sentence["id"], sentence["speaker_id"] or "",
        )))
        if spoken is not None:
            label_size += len(spoken["start"] or "") + len(spoken["end"] or "")
        excerpt = budget.take(sentence["text"], label_size=label_size)
        if excerpt is None:
            truncated = True
            continue
        row = {
            "path": file["path"],
            "recording_id": transcript["recording_id"],
            "kind": transcript["kind"],
            "time_zone": transcript["time_zone"],
            "sentence_id": sentence["id"],
            "spoken_at": None if spoken is None else {"start": spoken["start"], "end": spoken["end"]},
            "speaker_id": sentence["speaker_id"],
            "is_self": sentence["is_self"],
            "text": excerpt,
            **audio_link(sentence, transcript, audio_files),
        }
        if excerpt != sentence["text"]:
            row["truncated"] = True
            truncated = True
        rows.append(row)
    return rows, matched, truncated


def read_type(root, day, category, entry, opts, budget, audio_files):
    entry = read_category(entry, category, export_format=root.marker["format"], day=day)
    outcome = {
        "state": entry["state"], "status": entry["state"], "updated_at": entry["updated_at"],
        "manifest_file_count": len(entry["files"]), "verified_file_count": 0,
    }
    entries = entry["files"]
    if not entries:
        return outcome, {}
    if opts.recording_id is not None and category in ("audio", "transcripts"):
        entries = [item for item in entries if item["recording_id"] == opts.recording_id]
    if category in APP_MARKDOWN:
        entries = [
            item for item in entries
            if (opts.item_id is None or item["item_id"] == opts.item_id)
            and (opts.item_kind is None or item["kind"] == opts.item_kind)
        ]
    if not entries:
        return {**outcome, "status": "no_match"}, {}

    audio_index, evidence, matched, truncated, pairings = {}, [], 0, False, {}
    next_item = None
    for file in entries:
        relative = f'{day}/{file["path"]}'
        data = root.read_file(relative, limit=LIMITS.get(category), expected=file, retain=category != "audio")
        if category == "audio":
            audio_index[(file["recording_id"], file["kind"])] = file
            if opts.mode == "read":
                label_size = len(file["path"]) + len(file["recording_id"])
                if budget.take("", label_size=label_size) is not None:
                    evidence.append({key: file[key] for key in ("path", "recording_id", "kind", "byte_count")})
                else:
                    truncated = True
        elif category == "results" or category in APP_MARKDOWN:
            try:
                markdown = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ExportError("invalid_contract", "Exported Markdown must be UTF-8.") from exc
            if markdown.startswith("\ufeff"):
                raise ExportError("invalid_contract", "Exported Markdown must not start with a BOM.")
            if opts.mode == "read":
                identity = {}
                if category in APP_MARKDOWN:
                    identity.update(item_id=file["item_id"], kind=file["kind"])
                if category == "favorites":
                    identity["favorited_at"] = file["favorited_at"]
                remaining = markdown[opts.markdown_offset:]
                label_size = len(file["path"]) + sum(len(value) for value in identity.values())
                excerpt = budget.take(remaining, label_size=label_size)
                cut = excerpt != remaining
                truncated = truncated or cut
                if excerpt is not None:
                    evidence.append({
                        "path": file["path"], "offset": opts.markdown_offset, "markdown": excerpt,
                        "next_offset": opts.markdown_offset + len(excerpt) if cut else None,
                        **identity,
                    })
                elif next_item is None and category in APP_MARKDOWN:
                    next_item = {"item_id": file["item_id"], "kind": file["kind"]}
        else:
            transcript = read_transcript(data, day, file)
            audio = audio_files.get((transcript["recording_id"], transcript["kind"]))
            if audio is not None:
                digest = transcript["audio_sha256"]
                pairing = "unbound" if digest is None else "matched" if digest == audio["sha256"] else "mismatch"
                pairings[pairing] = pairings.get(pairing, 0) + 1
            if opts.mode == "read":
                items, count, cut = transcript_evidence(transcript, file, audio_files, opts, budget)
                evidence.extend(items)
                matched += count
                truncated = truncated or cut

    outcome.update(status="readable", verified_file_count=len(entries))
    if opts.mode == "read":
        outcome.update(evidence=evidence, truncated=truncated)
        if next_item is not None:
            outcome["next_item"] = next_item
        if category == "transcripts":
            outcome["matched_sentence_count"] = matched
            if matched == 0:
                outcome["status"] = "no_match"
    if pairings:
        outcome["verified_audio_pairings"] = pairings
    return outcome, audio_index


def load_day(root, day):
    try:
        raw = root.read_file(f"{day}/manifest.json", limit=LIMITS["manifest"])
    except ExportError as exc:
        if exc.status == "file_missing":
            raise ExportError("manifest_not_found", "No readable manifest is visible for this archive date.") from exc
        raise
    return raw, read_manifest(raw, day, root.marker["publisher_id"], root.marker["format"])


def inspect_day(root, day, categories, opts, budget):
    start = budget.checkpoint()
    for attempt in range(2):
        results, verified_audio = {}, {}
        try:
            raw, manifest = load_day(root, day)
            # Verify explicitly requested audio first so transcript offsets can be paired.
            order = ("results", "audio", "events", "daily_reviews", "meeting_notes", "favorites", "transcripts")
            for category in order:
                if category not in categories:
                    continue
                mark = budget.checkpoint()
                try:
                    results[category], audio = read_type(
                        root, day, category, manifest["contents"][category], opts, budget, verified_audio,
                    )
                    verified_audio.update(audio)
                except ExportError as exc:
                    budget.restore(mark)
                    results[category] = exc.report()
                    if exc.status in UNREADABLE:
                        results[category]["availability"] = "pending_or_unavailable"
            current, _ = load_day(root, day)
            if current == raw:
                return {
                    "archive_day": day, "status": "inspected",
                    "commit_id": manifest["commit_id"], "committed_at": manifest["committed_at"],
                    "contents": {key: results[key] for key in categories},
                }
        except ExportError as exc:
            budget.restore(start)
            if results and attempt == 0 and exc.status == "manifest_not_found":
                continue
            return {"archive_day": day, **exc.report()}
        budget.restore(start)
    return {
        "archive_day": day, "status": "manifest_changed",
        "detail": "The manifest changed twice. Retry after iCloud settles.",
    }


def execute(root, opts):
    report = {
        "format": root.marker["format"], "schema_version": VERSION, "environment": root.marker["environment"],
        "root": str(root.path), "visibility": "local_device_snapshot",
    }
    if opts.mode == "list":
        days = root.list_days(opts.first, opts.last)
        report.update(archive_days=days[:opts.limit], matched_date_count=len(days))
        return report, 0

    app_format = root.marker["format"] == APP_FORMAT
    allowed = APP_CATEGORIES if app_format else CATEGORIES
    defaults = ("events", "daily_reviews", "transcripts") if app_format else ("results", "transcripts")
    categories = allowed if opts.mode == "validate" else tuple(dict.fromkeys(opts.types or defaults))
    if any(category not in allowed for category in categories):
        raise ExportError("unsupported_category", "The selected export format does not publish the requested category.")
    budget = EvidenceBudget(getattr(opts, "char_limit", 0))
    if opts.latest:
        report["skipped"] = []
        report["days"] = []
        report["skipped_date_count"] = 0
        for day in root.list_days():
            inspected = inspect_day(root, day, categories, opts, budget)
            statuses = {key: value["status"] for key, value in inspected.get("contents", {}).items()}
            if "readable" in statuses.values():
                report["days"].append(inspected)
                return report, int(not day_ok(inspected))
            if len(report["skipped"]) < 30:
                report["skipped"].append({"archive_day": day, "status": inspected["status"], "contents": statuses})
            report["skipped_date_count"] += 1
        report["status"] = "no_readable_export"
        return report, 1

    days = list(dict.fromkeys(opts.date or root.list_days()))
    report["days"] = [inspect_day(root, day, categories, opts, budget) for day in days]
    if not days:
        report["status"] = "no_archived_dates"
    return report, int(not days or not all(day_ok(day) for day in report["days"]))


def day_ok(day):
    completed = {"readable", "no_match", "never_exported", "empty", "deleted"}
    return day["status"] == "inspected" and all(
        item["status"] in completed for item in day["contents"].values()
    )


def arguments():
    def day_arg(value):
        if not valid_day(value):
            raise argparse.ArgumentTypeError("use a valid archive date in YYYY-MM-DD form")
        return value

    def integer(minimum, maximum):
        def parse(value):
            try:
                number = int(value)
            except ValueError:
                number = minimum - 1
            if not minimum <= number <= maximum:
                raise argparse.ArgumentTypeError(f"expected an integer from {minimum} to {maximum}")
            return number
        return parse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="memova-icloud-export 0.2.0 (App V1 and preview V1)")
    modes = parser.add_subparsers(dest="mode", required=True)
    for mode in ("list", "read", "validate"):
        sub = modes.add_parser(mode)
        sub.add_argument("--root", required=mode == "validate", help="authorized app-v1 or preview v1 folder, or its parent")
        sub.add_argument("--environment", choices=["production", "development"], default="production")
        sub.add_argument("--timeout", type=integer(1, 600), default=60, help="whole operation deadline in seconds")
        sub.set_defaults(latest=False, recording_id=None, item_id=None, item_kind=None)
        if mode == "list":
            sub.add_argument("--from", dest="first", type=day_arg)
            sub.add_argument("--through", dest="last", type=day_arg)
            sub.add_argument("--limit", type=integer(1, 366), default=30)
        elif mode == "read":
            selection = sub.add_mutually_exclusive_group(required=True)
            selection.add_argument("--date", type=day_arg, action="append")
            selection.add_argument("--latest", action="store_true")
            sub.add_argument("--type", dest="types", action="append", choices=tuple(dict.fromkeys(CATEGORIES + APP_CATEGORIES)))
            sub.add_argument("--recording-id")
            sub.add_argument("--item-id", help="exact App V1 Markdown item ID")
            sub.add_argument("--item-kind", choices=APP_MARKDOWN["favorites"], help="App V1 Markdown item kind")
            sub.add_argument("--sentence-id")
            sub.add_argument("--contains", help="case-insensitive literal transcript text filter")
            sub.add_argument("--char-limit", type=integer(256, 200_000), default=24_000)
            sub.add_argument("--markdown-offset", type=integer(0, LIMITS["results"]), default=0)
        else:
            sub.add_argument("--date", type=day_arg, action="append")
    opts = parser.parse_args()
    if opts.mode == "list" and opts.first and opts.last and opts.first > opts.last:
        parser.error("--from must be on or before --through")
    return opts


class ReadDeadline(Exception):
    pass


def timeout(_signum, _frame):
    raise ReadDeadline()


def main():
    opts = arguments()
    signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, opts.timeout)
    try:
        root = locate_root(opts.root, opts.environment)
        try:
            report, code = execute(root, opts)
            root.verify_binding()
        finally:
            root.close()
    except ExportError as exc:
        report, code = exc.report(), 2
    except ReadDeadline:
        report, code = {"status": "timeout", "detail": "The read exceeded its deadline. Narrow its scope."}, 2
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    try:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    except UnicodeEncodeError:
        print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    sys.exit(main())

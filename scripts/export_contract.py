"""Decode and validate Memova iCloud exports for the App and preview V1 formats."""

import datetime as dt
import hashlib
import json
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


FORMAT = "memova-icloud-export"
APP_FORMAT = "memova-icloud-sync"
VERSION = 1
KINDS = {"hourly": "hourly", "phone_meeting": "meetings"}
CATEGORIES = ("results", "transcripts", "audio")
APP_CATEGORIES = ("transcripts", "events", "daily_reviews", "audio", "meeting_notes", "favorites")
APP_MARKDOWN = {
    "events": ("event",),
    "daily_reviews": ("daily_review",),
    "meeting_notes": ("meeting",),
    "favorites": ("event", "daily_review", "meeting"),
}
STATES = {"never_exported", "ready", "empty", "deleted"}
AUDIO_EXTENSIONS = {"m4a", "caf", "wav", "mp3", "aac"}
LIMITS = {
    "format": 16 * 1024,
    "manifest": 16 * 1024 * 1024,
    "transcripts": 64 * 1024 * 1024,
    "results": 4 * 1024 * 1024,
    **dict.fromkeys(APP_MARKDOWN, 4 * 1024 * 1024),
}
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SHA = re.compile(r"[0-9a-f]{64}")
TIMESTAMP = re.compile(
    r"(?P<seconds>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.(?P<fraction>[0-9]+))?(?P<offset>Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


class ExportError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail

    def report(self):
        return {"status": self.status, "detail": self.detail}


def invalid(detail):
    raise ExportError("invalid_contract", detail)


def decode_json(raw):
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                invalid("JSON contains a duplicate object key.")
            value[key] = item
        return value

    def finite_float(token):
        number = float(token)
        if not math.isfinite(number):
            invalid("JSON contains a non-finite number.")
        return number

    def check_depth(value, depth=0):
        if depth > 32:
            invalid("JSON exceeds the V1 nesting limit.")
        if isinstance(value, dict):
            for child in value.values():
                check_depth(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                check_depth(child, depth + 1)

    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=finite_float,
            parse_float=finite_float,
        )
        check_depth(document)
    except (ValueError, RecursionError) as exc:
        raise ExportError("invalid_contract", "Expected bounded UTF-8 JSON without a BOM.") from exc
    return document


def required(value, fields, label):
    if not isinstance(value, dict) or not set(fields).issubset(value):
        invalid(f"{label} is missing a required field or is not an object.")


def check_version(value):
    version = value.get("schema_version")
    if type(version) is not int or version < 1:
        invalid("schema_version must be a positive integer.")
    if version != VERSION:
        raise ExportError("unsupported_version", "Upgrade the Skill to read this schema version.")


def matches(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def valid_day(value):
    if not matches(DATE, value):
        return False
    try:
        dt.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def timestamp(value, field, *, nullable=False, utc=False):
    if nullable and value is None:
        return None
    match = TIMESTAMP.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        invalid(f"{field} must be an RFC 3339 timestamp with an offset.")
    offset = "+00:00" if match["offset"] == "Z" else match["offset"]
    try:
        parsed = dt.datetime.fromisoformat(match["seconds"] + offset)
    except ValueError:
        invalid(f"{field} is not a real date and time.")
    if utc and parsed.utcoffset() != dt.timedelta(0):
        invalid(f"{field} must be UTC.")
    # Keep exact decimal ordering without rounding fractions to datetime microseconds.
    return parsed, (match["fraction"] or "").rstrip("0")


def string(value, label):
    if not isinstance(value, str):
        invalid(f"{label} must be a UTF-8 string.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        invalid(f"{label} contains an invalid Unicode surrogate.")
    return value


def recording_key(recording_id):
    value = string(recording_id, "recording_id")
    encoded = value.encode("utf-8")
    if not 1 <= len(encoded) <= 240 or value in {".", ".."} or re.search(r"[/\\\x00-\x1f\x7f-\x9f]", value):
        invalid("Invalid archive recording_id.")
    return hashlib.sha256(encoded).hexdigest()


def read_marker(raw, environment):
    value = decode_json(raw)
    required(value, ("format", "schema_version", "environment", "publisher_id"), "format.json")
    if value["format"] not in (FORMAT, APP_FORMAT):
        invalid("format.json does not identify a Memova iCloud export.")
    check_version(value)
    if value["environment"] not in ("production", "development"):
        invalid("Unknown export environment.")
    if value["environment"] != environment:
        raise ExportError("environment_mismatch", "The export belongs to another build environment.")
    if not matches(UUID, value["publisher_id"]):
        invalid("Invalid publisher_id in format.json.")
    return value


def read_manifest(raw, day, publisher, export_format=FORMAT):
    value = decode_json(raw)
    required(
        value,
        ("schema_version", "archive_day", "publisher_id", "commit_id", "committed_at", "contents"),
        "manifest.json",
    )
    check_version(value)
    if value["archive_day"] != day:
        invalid("The manifest archive_day does not match its directory.")
    if value["publisher_id"] != publisher:
        raise ExportError("publisher_mismatch", "The manifest publisher differs from format.json.")
    if not matches(UUID, value["commit_id"]):
        invalid("Invalid manifest commit_id.")
    timestamp(value["committed_at"], "committed_at", utc=True)
    contents = value["contents"]
    categories = APP_CATEGORIES if export_format == APP_FORMAT else CATEGORIES
    required(contents, categories, "Manifest contents")
    if export_format == APP_FORMAT and len(contents) != len(categories):
        invalid("The App V1 manifest must contain exactly six categories.")
    return value


def recording_location(file, category, revision, app_format):
    recording_id = file["recording_id"]
    key = recording_key(recording_id)
    kind = file["kind"]
    if not isinstance(kind, str) or kind not in KINDS:
        invalid("Unknown recording kind.")
    extension = file["path"].rsplit(".", 1)[-1]
    allowed = {"json"} if category == "transcripts" else AUDIO_EXTENSIONS
    if extension not in allowed:
        invalid("The payload has an unsupported extension.")
    if app_format:
        return recording_id, f'{category}/{KINDS[kind]}/{key}/{file["sha256"]}.{extension}'
    return recording_id, f"{category}/{revision}/{KINDS[kind]}/{key}.{extension}"


def markdown_location(file, category, day):
    item_id = string(file["item_id"], "item_id")
    kind = file["kind"]
    if not item_id or kind not in APP_MARKDOWN[category]:
        invalid("Invalid Markdown item identity or kind.")
    if kind == "daily_review" and item_id != day:
        invalid("A daily review item_id must be its archive day.")
    directory = category
    if category == "favorites":
        timestamp(file.get("favorited_at"), "favorited_at", utc=True)
        directory = f"{category}/{kind}"
    key = hashlib.sha256(item_id.encode("utf-8")).hexdigest()
    return (kind, item_id), f'{directory}/{key}/{file["sha256"]}.md'


def read_category(value, category, *, export_format=FORMAT, day=None):
    required(value, ("state", "revision", "updated_at", "files"), category)
    state, revision, updated, files = (value[key] for key in ("state", "revision", "updated_at", "files"))
    if not isinstance(state, str) or state not in STATES or not isinstance(files, list):
        invalid("Invalid category state or file list.")
    if state == "never_exported":
        if revision is not None or updated is not None:
            invalid("never_exported must have null revision and updated_at.")
    else:
        if not matches(UUID, revision):
            invalid("Invalid category revision.")
        timestamp(updated, "updated_at", utc=True)
    if (state == "ready") != bool(files) or (category in ("results", "daily_reviews") and len(files) > 1):
        invalid("The category state and number of files do not agree.")

    previous = None
    identities = set()
    markdown = category in APP_MARKDOWN
    identity_field = "item_id" if markdown else "recording_id"
    for file in files:
        required(file, ("path", "byte_count", "sha256", identity_field, "kind"), "File entry")
        path, size, digest = (file[key] for key in ("path", "byte_count", "sha256"))
        if not isinstance(path, str) or type(size) is not int or size <= 0 or not matches(SHA, digest):
            invalid("Invalid file path, byte_count or SHA-256.")
        if previous is not None and path <= previous:
            invalid("Category paths must be sorted and unique.")
        previous = path
        if size > LIMITS.get(category, size):
            raise ExportError("too_large", "The declared file size exceeds the V1 limit.")
        if category == "results":
            if file["recording_id"] is not None or file["kind"] is not None:
                invalid("A daily summary cannot have a recording_id or kind.")
            identity = None
            expected = f"results/{revision}/daily-summary.md"
        elif markdown:
            identity, expected = markdown_location(file, category, day)
        else:
            identity, expected = recording_location(file, category, revision, export_format == APP_FORMAT)
        if identity in identities:
            invalid("A category lists the same item twice.")
        identities.add(identity)
        if path != expected:
            raise ExportError("unsafe_path", "A manifest path does not match its V1 directory and identity.")
    return value


def read_transcript(raw, day, file):
    value = decode_json(raw)
    required(value, (
        "schema_version", "recording_id", "kind", "archive_day", "time_zone",
        "started_at", "audio_sha256", "sentences",
    ), "Transcript")
    check_version(value)
    if (value["archive_day"], value["recording_id"], value["kind"]) != (day, file["recording_id"], file["kind"]):
        invalid("Transcript identity differs from its manifest entry.")
    zone = value["time_zone"]
    if zone is not None:
        try:
            ZoneInfo(string(zone, "time_zone"))
        except (ZoneInfoNotFoundError, ValueError, OSError):
            invalid("time_zone must be an IANA time zone or null.")
    timestamp(value["started_at"], "started_at", nullable=True)
    digest = value["audio_sha256"]
    if digest is not None and not matches(SHA, digest):
        invalid("Invalid transcript audio_sha256.")
    if not isinstance(value["sentences"], list) or not value["sentences"]:
        invalid("A published transcript must contain sentences.")

    sentence_ids = set()
    for row in value["sentences"]:
        required(row, ("id", "text", "spoken_at", "audio_range_seconds", "speaker_id", "is_self"), "Sentence")
        identifier = string(row["id"], "sentence id")
        if not identifier or identifier in sentence_ids:
            invalid("A transcript contains a missing or duplicate sentence ID.")
        sentence_ids.add(identifier)
        string(row["text"], "sentence text")
        spoken = row["spoken_at"]
        if spoken is not None:
            required(spoken, ("start", "end"), "spoken_at")
            start = timestamp(spoken["start"], "spoken_at.start", nullable=True)
            end = timestamp(spoken["end"], "spoken_at.end", nullable=True)
            if start is not None and end is not None and end < start:
                invalid("spoken_at ends before it starts.")
        audio = row["audio_range_seconds"]
        if audio is not None:
            required(audio, ("start", "end"), "audio_range_seconds")
            start, end = audio["start"], audio["end"]
            if (
                digest is None or type(start) not in (int, float) or type(end) not in (int, float)
                or not 0 <= start < end
            ):
                invalid("An audio range must be non-negative, ordered and bound to an audio SHA-256.")
        if row["speaker_id"] is not None and not matches(re.compile(r"speaker-[0-9]{2,}"), row["speaker_id"]):
            invalid("speaker_id must be a recording-local anonymous label or null.")
        if row["is_self"] is not None and type(row["is_self"]) is not bool:
            invalid("is_self must be a boolean or null.")
    return value

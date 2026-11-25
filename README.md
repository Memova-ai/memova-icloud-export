# Memova iCloud Export Skill

Read Memova Local events, daily reviews, transcripts, meeting notes, favorites and requested original audio in a file-enabled agent. The reader checks the active day manifest and validates file sizes and SHA-256 before returning evidence.

Release `v0.2.0` reads the App's automatic iCloud sync V1 and the earlier preview export. Mac discovery requires that the local iCloud Drive account can access the published files.

## Install in Codex

Install the whole Skill checkout under your project's `.agents/skills/memova-icloud-export` so its scripts and references stay with `SKILL.md`. Run the following from the project where you want to use the Skill.

```sh
mkdir -p .agents/skills
git clone --branch v0.2.0 --depth 1 \
  https://github.com/Memova-ai/memova-icloud-export.git \
  .agents/skills/memova-icloud-export
```

Start a Codex session in that project and invoke `$memova-icloud-export`. If you installed `v0.1.0` with Git, fetch the new tag and switch your checkout to it.

```sh
git -C .agents/skills/memova-icloud-export fetch origin tag v0.2.0
git -C .agents/skills/memova-icloud-export switch --detach v0.2.0
```

To install from a release archive, place the entire extracted folder at `.agents/skills/memova-icloud-export` so `SKILL.md` is at the top level. Other clients that support the Agent Skills format can use the same folder with their own installation workflow. [Release archive](https://github.com/Memova-ai/memova-icloud-export/releases/tag/v0.2.0) · [Codex skill locations](https://learn.chatgpt.com/docs/build-skills) · [Agent Skills format](https://agentskills.io/specification)

The reader requires Python 3.9 or later. Automatic discovery uses macOS and the local account's iCloud Drive. A POSIX runtime can read an explicitly supplied export copy. No additional Python package is needed for the reader.

## Try the included preview export

Try these commands from the Skill directory.

```sh
python3 -B scripts/read_export.py validate --root assets/synthetic
python3 -B scripts/read_export.py read --root assets/synthetic --latest --type results
```

The latest readable recap in the sample is on 2026-11-24. The 2026-11-25 sample is a cross-midnight meeting with a transcript and an empty daily summary. Its spoken timestamps can extend into the next day.

You can also invoke the Skill in Codex.

> $memova-icloud-export Tell me the latest readable daily recap in assets/synthetic and cite the source.

## Read a Memova export

On iPhone, open **More → Time & Memories → iCloud Sync**, turn on the main switch, and pick the categories to sync. On Mac, open **Finder → iCloud Drive → Memova Exports → app-v1**. The reader checks both macOS paths for this folder. Finder's **Download Now** can make online files available locally. In a hosted session, provide an authorized copy or a local file bridge. [Apple iCloud file status](https://support.apple.com/en-gb/guide/mac-help/mchlc994344b/mac)

```sh
python3 -B scripts/read_export.py list
python3 -B scripts/read_export.py list --environment development
python3 -B scripts/read_export.py read --date 2026-11-24 --type daily_reviews --type transcripts
python3 -B scripts/read_export.py read --latest --type favorites
python3 -B scripts/read_export.py validate --root "/path/to/Memova Exports/app-v1"
```

Development uses **Memova Exports Dev → app-v1**. The preview remains available under `v1` and uses `--type results` for the combined daily recap and events. To read a particular folder, pass its path with `--root`. The Skill keeps local files read-only. Its default read is limited to text. Audio is read only when explicitly requested. Evidence files can contain private information, and the agent's own settings determine how returned text is processed. Use the included synthetic fixture when sharing test output.

## App integration and development

- [App V1 sync contract](references/app-v1-sync.md) defines the six categories, manifest and fixed paths. The [preview contract](references/v1-export.md) documents the earlier three-category export.
- The [schemas](references/schemas) include the shared transcript structure and the preview marker and manifest. The [bundled synthetic fixture](assets/synthetic/v1) is in the preview format. Tests also construct a synthetic App V1 export.
- App teams should run `validate --root <export-directory>` against files produced by the App and check the requested types and file counts in the report. A successful synthetic run and an App-generated export are separate acceptance checks.
- For the test suite, install `jsonschema==4.26.0` in a development environment and run `python3 -B -m unittest discover -s tests -v`.

See [GitHub Issues](https://github.com/Memova-ai/memova-icloud-export/issues) for usage problems and [SECURITY.md](SECURITY.md) for security reports. Include the Skill version, OS, command and a synthetic reproduction.

## 中文快速开始

按上面的命令安装 `v0.2.0`。在 Codex 里输入「`$memova-icloud-export` 读取 `assets/synthetic` 里最近一份可读的每日回顾并标注出处」即可试用。App 的正式目录是「iCloud Drive → Memova Exports → app-v1」，开发版使用「Memova Exports Dev → app-v1」。旧预览的 `v1` 目录仍可读取。真机联调需要验证 iPhone 写入和 Mac 上实际运行 Skill 时的读取权限。

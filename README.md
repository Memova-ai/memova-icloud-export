# Memova iCloud Export Skill

Read Memova Local exports from iCloud Drive in a file-enabled agent. Ask for a daily recap, find an original quote, or locate an explicitly requested audio recording. The reader checks the active day manifest and validates file sizes and SHA-256 before returning evidence.

**Release status** · `v0.1.0` is a public preview of the V1 reader. It can read and validate the included synthetic export and an explicitly supplied V1 directory. Automatic discovery has been exercised on a simulated iCloud directory layout on macOS. The fixed path for a signed iPhone App export still needs to be verified in the target Mac agent session.

## Install in Codex

Run from the project where you want to use the Skill. This checks out the versioned release and keeps the scripts and references next to `SKILL.md`.

```sh
mkdir -p .agents/skills
git clone --branch v0.1.0 --depth 1 \
  https://github.com/Memova-ai/memova-icloud-export.git \
  .agents/skills/memova-icloud-export
```

Start a Codex session in that project and invoke `$memova-icloud-export`. To install it from a [release archive](https://github.com/Memova-ai/memova-icloud-export/releases), place the entire extracted folder at `.agents/skills/memova-icloud-export` so `SKILL.md` is at the top level. Other clients that support the Agent Skills format can use the same folder with their own installation workflow. [Codex skill locations](https://learn.chatgpt.com/docs/build-skills) · [Agent Skills format](https://agentskills.io/specification)

The reader requires Python 3.9 or later. Automatic discovery uses macOS and the local account's iCloud Drive. A POSIX runtime can read an explicitly supplied export copy. No additional Python package is needed for the reader.

## Try the included export

Try these commands from the Skill directory.

```sh
python3 -B scripts/read_export.py validate --root assets/synthetic
python3 -B scripts/read_export.py read --root assets/synthetic --latest --type results
```

The latest readable recap in the sample is on 2026-11-24. The 2026-11-25 sample is a cross-midnight meeting with a transcript and an empty daily summary. Its spoken timestamps can extend into the next day.

You can also invoke the Skill in Codex.

> $memova-icloud-export Tell me the latest readable daily recap in assets/synthetic and cite the source.

## Read a Memova export

When the iPhone export is available, open Finder → iCloud Drive → Memova Exports → v1. A local Mac agent can try the Skill's fixed discovery paths. If the export is only online, Finder's **Download Now** can make it available locally. In a hosted session, provide an authorized copy or a local file bridge. [Apple iCloud file status](https://support.apple.com/en-gb/guide/mac-help/mchlc994344b/mac)

```sh
python3 -B scripts/read_export.py list
python3 -B scripts/read_export.py read --date 2026-11-24 --type results --type transcripts
python3 -B scripts/read_export.py validate --root "/path/to/Memova Exports"
```

The Skill reads local files and leaves them untouched. Its default read is limited to text. Audio is read only when explicitly requested. Evidence files can contain private information, and the agent's own settings determine how returned text is processed. Use the included synthetic fixture when sharing test output.

## App integration and development

- [V1 export contract](references/v1-export.md) explains the layout, category states, verification and CLI results.
- The [schemas](references/schemas) define the root marker, the day manifest and the per-recording transcript. The [synthetic fixture](assets/synthetic/v1) exercises the same format.
- App teams should run `validate --root <export-directory>` against files produced by the App and check the requested types and file counts in the report. A successful synthetic run and an App-generated export are separate acceptance checks.
- For the test suite, install `jsonschema==4.26.0` in a development environment and run `python3 -B -m unittest discover -s tests -v`.

See [GitHub Issues](https://github.com/Memova-ai/memova-icloud-export/issues) for usage problems and [SECURITY.md](SECURITY.md) for security reports. Include the Skill version, OS, command and a synthetic reproduction.

## 中文快速开始

先按上面的命令把 Skill 安装到当前项目。在 Codex 里输入「`$memova-icloud-export` 读取 `assets/synthetic` 里最近一份可读的每日回顾并标注出处」即可试用。真实资料的入口是「iCloud Drive → Memova Exports → v1」。真机端到端联调完成前，请用合成样例或用户授权提供的 V1 目录验证。

<div align="center">

# play-jab

**Playwright-style automation for Java desktop applications through Java Access Bridge**

[Русская версия](README_RU.MD)

[![Project status](https://img.shields.io/badge/status-pre--alpha-orange)](#project-status)
[![Python](https://img.shields.io/badge/python-3.11%E2%80%933.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Pipeline](https://gitlab.com/dashanovsd/play-jab/badges/main/pipeline.svg)](https://gitlab.com/dashanovsd/play-jab/-/pipelines)
[![Coverage](https://gitlab.com/dashanovsd/play-jab/badges/main/coverage.svg)](https://gitlab.com/dashanovsd/play-jab/-/graphs/main/charts)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

</div>

`play-jab` is a typed Python library for inspecting and automating Java desktop
interfaces on Windows. It builds a safer, modern API on top of the native Java
Access Bridge (JAB), including dedicated message-pump ownership and explicit
native-reference lifecycle management.

## Project status

> [!IMPORTANT]
> **Pre-alpha.** The native JAB foundation is being developed,
> but a stable public automation API is not available yet. The current public
> package surface contains the exception hierarchy. Expect breaking changes.

## Highlights

- Windows-native Java Access Bridge integration
- Python 3.11–3.14 support and strict type checking
- Explicit diagnostics for setup, window, reference, and native-call failures
- Automated ABI, lifecycle, ownership, and real JDK 17 integration tests
- Planned Playwright-style, locator-driven API

## Requirements

- Windows
- Python 3.11 or newer
- A Java runtime that provides Java Access Bridge
- Matching Python and JAB DLL architectures (both 32-bit or both 64-bit)

## Quick start

Install the package:

```powershell
python -m pip install play-jab
```

Enable Java Access Bridge for the current Windows user, then restart the Java
application you want to inspect:

```powershell
& "$env:JAVA_HOME\bin\jabswitch.exe" -enable
```

Verify that the public package can be imported:

```powershell
python -c "from play_jab import PlayJabError; print(PlayJabError.__name__)"
```

See the **[Getting Started guide](docs/getting-started.md)** for environment
checks, JAB setup, currently available imports, and troubleshooting.

## Documentation

- [Getting Started](docs/getting-started.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

User-facing automation examples will be added when the stable API lands. Until
then, modules under `play_jab._native` are implementation details and should not
be imported by application code.

## Development

```powershell
uv sync --all-groups
uv run pytest
uv run pre-commit run --all-files
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for all checks, commit conventions, and
the release process.

## License

Licensed under the [Apache License 2.0](LICENSE).

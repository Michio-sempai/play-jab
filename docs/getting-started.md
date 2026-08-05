# Getting Started

[Русская версия](getting-started.ru.md) · [Back to README](../README.md)

This guide prepares a Windows environment for `play-jab` and documents the
package surface available in the current pre-alpha release.

## 1. Check the prerequisites

Use Python 3.11–3.14 and a Java installation that includes Java Access Bridge.
Confirm that both tools are available:

```powershell
python --version
java -version
$env:JAVA_HOME
```

Python and the JAB DLL must have the same architecture. Check Python with:

```powershell
python -c "import struct; print(struct.calcsize('P') * 8, 'bit')"
```

If `JAVA_HOME` is empty, set it to the JDK directory in your user or system
environment, then open a new terminal.

## 2. Enable Java Access Bridge

Enable JAB for the current Windows user:

```powershell
& "$env:JAVA_HOME\bin\jabswitch.exe" -enable
```

Restart any running Java applications afterward. Enabling JAB does not retrofit
accessibility support into an already running JVM.

## 3. Install and verify play-jab

```powershell
python -m pip install play-jab
python -c "import play_jab; print(play_jab.__file__)"
```

The second command should print the installed package path without an import
error.

## Current public surface

The automation API is not public yet. Application code may currently import the
documented exception hierarchy:

```python
from play_jab import (
    BridgeInitializationError,
    BridgeNotEnabledError,
    JavaWindowNotAccessibleError,
    JavaWindowNotFoundError,
    PlayJabError,
)

assert issubclass(BridgeNotEnabledError, BridgeInitializationError)
assert issubclass(BridgeInitializationError, PlayJabError)
```

Do not import from `play_jab._native`: its names, signatures, and lifecycle
contracts may change without notice. Runnable automation examples will be added
when the stable public API is introduced.

## Troubleshooting

| Symptom or exception | What to check |
| --- | --- |
| `BridgeNotEnabledError` | Run `jabswitch.exe -enable` as the same Windows user and restart the Java application. |
| `BridgeInitializationError` | Check `JAVA_HOME`, DLL availability, and Python/JAB bitness. |
| `JavaWindowNotFoundError` | Confirm that the HWND still exists and belongs to a Java window. |
| `JavaWindowNotAccessibleError` | Confirm JAB was enabled before the target JVM started. |
| `JavaReferenceClosedError` | Reacquire the element after its native reference has been released. |
| `BridgeClosedError` | Create a new automation session; a closed runtime cannot be reused. |
| `NativeCallError` | Inspect its function name and scalar arguments for the failing JAB operation. |

`NativeCallError` deliberately excludes application text, which may contain
sensitive field values.

## Developing from source

```powershell
git clone https://gitlab.com/dashanovsd/play-jab.git
Set-Location play-jab
uv sync --all-groups
uv run pytest
```

Real JAB integration tests additionally require an interactive Windows desktop
and JDK 17. Contributor setup is covered in [CONTRIBUTING.md](../CONTRIBUTING.md).

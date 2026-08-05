# Начало работы

[English version](getting-started.md) · [Вернуться к README](../README_RU.MD)

Это руководство поможет подготовить Windows-окружение для `play-jab` и описывает
возможности пакета, доступные в текущей pre-alpha версии.

## 1. Проверьте требования

Используйте Python 3.11–3.14 и установленную Java с поддержкой Java Access
Bridge. Проверьте доступность обоих инструментов:

```powershell
python --version
java -version
$env:JAVA_HOME
```

Архитектура Python и JAB DLL должна совпадать. Проверьте Python командой:

```powershell
python -c "import struct; print(struct.calcsize('P') * 8, 'bit')"
```

Если `JAVA_HOME` пуст, задайте путь к JDK в пользовательских или системных
переменных среды, затем откройте новый терминал.

## 2. Включите Java Access Bridge

Включите JAB для текущего пользователя Windows:

```powershell
& "$env:JAVA_HOME\bin\jabswitch.exe" -enable
```

После этого перезапустите работающие Java-приложения. Включение JAB не добавляет
поддержку доступности в уже запущенную JVM.

## 3. Установите и проверьте play-jab

```powershell
python -m pip install play-jab
python -c "import play_jab; print(play_jab.__file__)"
```

Вторая команда должна вывести путь установленного пакета без ошибки импорта.

## Текущий публичный интерфейс

API автоматизации пока не опубликован. Сейчас прикладной код может импортировать
документированную иерархию исключений:

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

Не импортируйте `play_jab._native`: его имена, сигнатуры и правила жизненного
цикла могут измениться без предупреждения. Запускаемые примеры автоматизации
будут добавлены вместе со стабильным публичным API.

## Диагностика

| Симптом или исключение | Что проверить |
| --- | --- |
| `BridgeNotEnabledError` | Запустите `jabswitch.exe -enable` от имени того же пользователя и перезапустите Java-приложение. |
| `BridgeInitializationError` | Проверьте `JAVA_HOME`, наличие DLL и совпадение разрядности Python/JAB. |
| `JavaWindowNotFoundError` | Убедитесь, что HWND существует и принадлежит Java-окну. |
| `JavaWindowNotAccessibleError` | Убедитесь, что JAB был включён до запуска целевой JVM. |
| `JavaReferenceClosedError` | Получите элемент заново после освобождения его нативной ссылки. |
| `BridgeClosedError` | Создайте новую сессию автоматизации: закрытый runtime нельзя использовать повторно. |
| `NativeCallError` | Проверьте имя функции и скалярные аргументы завершившейся ошибкой операции JAB. |

`NativeCallError` намеренно не содержит текст приложения, в котором могут быть
чувствительные значения полей.

## Разработка из исходного кода

```powershell
git clone https://gitlab.com/dashanovsd/play-jab.git
Set-Location play-jab
uv sync --all-groups
uv run pytest
```

Для реальных интеграционных тестов JAB дополнительно нужны интерактивный рабочий
стол Windows и JDK 17. Настройка среды разработки описана в
[CONTRIBUTING.md](../CONTRIBUTING.md).

# Начало работы

[English version](getting-started.md) · [Вернуться к README](../README_RU.MD)

Это руководство поможет подготовить Windows-окружение для `play-jab` и описывает
возможности пакета, доступные в текущей pre-alpha версии.

## 1. Проверьте требования

Используйте 64-битные Python 3.11–3.14 и JDK 17 с Java Access Bridge. Проверьте
доступность обоих инструментов:

```powershell
python --version
java -version
$env:JAVA_HOME
```

Python и внешняя JAB DLL должны быть 64-битными. Проверьте Python командой:

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

`play-jab` не включает JAB DLL в wheel. `WindowsAccessBridge-64.dll` ищется по
явному `dll_path`, затем в `JAVA_HOME`, затем в Windows `System32`. Текущий
рабочий каталог никогда не участвует в поиске.

## 3. Установите и проверьте play-jab

```powershell
python -m pip install play-jab
python -c "import play_jab; print(play_jab.__file__)"
```

Вторая команда должна вывести путь установленного пакета без ошибки импорта.

## 4. Подключитесь и автоматизируйте

Запустите Java-приложение самостоятельно, затем подключитесь ровно по одному
HWND, PID или точному заголовку top-level окна. `PlayJab` работает только через
attach, а его закрытие никогда не завершает целевой процесс.

```python
from play_jab import PlayJab

with PlayJab(timeout=5_000) as jab:
    app = jab.attach(pid=12_345)
    window = app.window(title="Приложение")

    username = window.get_by_name("login.username")
    username.focus()
    username.fill("alice")
    window.get_by_name("login.remember").check()
    window.get_by_name("login.role").select_option("Admin")
    window.get_by_name("login.submit").click()

    jobs = window.get_by_name("jobs.table").as_table()
    print(jobs.snapshot())
    jobs.select_row(7)
    jobs.cell(7, 3).wait_for_text("Done", timeout=10_000)
```

Локаторы разрешаются заново для каждой операции; обычные строки сопоставляются
точно и с учётом регистра. Действия над формами проверяют наблюдаемый результат.
Явный вызов `text_content()` для password разрешён, но секреты не попадают в
snapshot, dump, логи и исключения. Индексы таблиц начинаются с нуля, ошибочный
индекс вызывает `TableIndexError`.

Для чтения метаданных корня окна без обхода потомков используйте
`window.snapshot()`, а для немедленной нестрогой проверки первого совпадения —
`locator.exists()`. `first()` и `nth()` прекращают обход после нужного
совпадения. Локатор с `showing_only=True` ищет показываемые узлы и отсекает
скрытые ветви; `visible_only=True` только фильтрует совпадения и ветви не
отсекает.

Не импортируйте `play_jab._native`: его имена, сигнатуры и правила жизненного
цикла могут измениться без предупреждения.

## Deadlines, виртуализация и прокрутка

Все операции, разрешающие locator, принимают `timeout` в миллисекундах.
Приоритет: значение вызова, затем `JavaWindow`, затем `PlayJab`; `timeout=0`
означает одну немедленную проверку. Чтение скрытых и disabled узлов разрешено,
действия проверяют цель и всю цепочку предков. Структурированные поля
`LocatorTimeoutError` включают bounded tree; password-данные в нём редактируются.

У виртуализированных списков и деревьев доступны только materialized children.
После явного `locator.scroll(steps)` разрешайте lazy locator заново. Положительные
steps прокручивают вниз, отрицательные вверх, ноль — no-op. Метод
`accessible_value()` возвращает неизменяемые строки current/minimum/maximum;
setter не поддерживается JAB из JDK 17.

## Диагностика

| Симптом или исключение | Что проверить |
| --- | --- |
| `BridgeNotEnabledError` | Запустите `jabswitch.exe -enable` от имени того же пользователя и перезапустите Java-приложение. |
| `BridgeInitializationError` | Проверьте `JAVA_HOME`, наличие DLL и совпадение разрядности Python/JAB. |
| `JavaWindowNotFoundError` | Убедитесь, что HWND существует и принадлежит Java-окну. |
| `JavaWindowNotAccessibleError` | Убедитесь, что JAB был включён до запуска целевой JVM. |
| `JavaProcessExitedError` | Attached-процесс ОС завершился; запустите его снова и создайте новую сессию. |
| `JavaVmExitedError` | Attached JVM сообщила о shutdown; старые локаторы и ссылки нельзя использовать повторно. |
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
стол Windows и JDK 17. Они запускаются последовательно:

```powershell
$env:PLAY_JAB_RUN_INTEGRATION = "1"
uv run pytest tests/integration
```

stdout/stderr JVM сохраняются в
`tests/java-fixtures/jab-swing-app/build/integration-logs/`. Настройка среды
разработки описана в [CONTRIBUTING.md](../CONTRIBUTING.md).

GitHub job real-JAB требует self-hosted runner с labels `windows`, `x64`,
`interactive`, `jab` и защищённое environment `real-jab`. Для включения задайте
repository variable `PLAY_JAB_REAL_JAB=1`; в environment настройте
`PLAY_JAB_DLL` и при необходимости `PLAY_JAB_JAVA_EXE`.

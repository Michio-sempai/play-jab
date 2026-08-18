<div align="center">

# play-jab

**Playwright-подобная автоматизация настольных Java-приложений через Java Access Bridge**

[English version](README.md)

[![Статус проекта](https://img.shields.io/badge/status-pre--alpha-orange)](#статус-проекта)
[![Python](https://img.shields.io/badge/python-3.11%E2%80%933.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Pipeline](https://gitlab.com/dashanovsd/play-jab/badges/main/pipeline.svg)](https://gitlab.com/dashanovsd/play-jab/-/pipelines)
[![Coverage](https://gitlab.com/dashanovsd/play-jab/badges/main/coverage.svg)](https://gitlab.com/dashanovsd/play-jab/-/graphs/main/charts)
[![Лицензия](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

</div>

`play-jab` — типизированная Python-библиотека для исследования и автоматизации
настольных Java-интерфейсов в Windows. Она создаёт более безопасный современный
API поверх нативного Java Access Bridge (JAB), управляет циклом сообщений в
отдельном потоке и контролирует время жизни нативных ссылок.

## Статус проекта

> [!IMPORTANT]
> **Pre-alpha MVP.** Синхронный attach-only API автоматизации уже доступен,
> но несовместимые изменения всё ещё возможны. `PlayJab` никогда не запускает и
> не останавливает целевой Java-процесс.

## Возможности

- Нативная интеграция с Java Access Bridge для Windows
- Поддержка Python 3.11–3.14 и строгая статическая типизация
- Понятные ошибки настройки, окон, ссылок и нативных вызовов
- Автоматические тесты ABI, жизненного цикла, владения ссылками и интеграции с JDK 17
- Ленивые строгие локаторы, формы, selection, ожидания и таблицы

## Требования

- Windows
- 64-битный Python 3.11–3.14
- 64-битный JDK 17 с JAB, включённым до запуска целевой JVM
- Внешняя `WindowsAccessBridge-64.dll` (DLL не включается в wheel)

## Быстрый старт

Установите пакет:

```powershell
python -m pip install play-jab
```

Включите Java Access Bridge для текущего пользователя Windows, затем
перезапустите Java-приложение, с которым будете работать:

```powershell
& "$env:JAVA_HOME\bin\jabswitch.exe" -enable
```

Проверьте публичный API:

```powershell
python -c "from play_jab import PlayJab; print(PlayJab.__name__)"
```

DLL ищется в строгом порядке: явный `dll_path`, затем `JAVA_HOME`, затем
Windows `System32`. Текущий рабочий каталог в поиске не участвует.

## Синхронный API

```python
from play_jab import PlayJab

with PlayJab(timeout=5_000, dll_path=r"C:\JAB\WindowsAccessBridge-64.dll") as jab:
    app = jab.attach(title="Приложение")
    window = app.window(title="Приложение")
    window.get_by_name("login.username").fill("alice")
    window.get_by_name("login.remember").check()
    window.get_by_name("login.role").select_option("Admin")
    window.get_by_name("login.submit").click()

    table = window.get_by_name("jobs.table").as_table()
    print(table.row_count(), table.column_count())
    table.cell(7, 3).fill("Готово")
    table.cell(7, 3).wait_for_text("Done")
```

Методы `attach(hwnd=...)`, `attach(pid=...)` и `attach(title=...)` подключаются
к существующему процессу. Заголовки окон и обычные строковые locator-ы
сопоставляются точно и с учётом регистра. Locator-ы ленивы и получают свежий
JAB context для каждой операции. Каждая операция над одним узлом запоминает
путь (индексы детей), которым он был найден, и на следующем вызове сначала
перепроверяет этот путь, а не обходит дерево заново; путь, переставший
удовлетворять всем шагам цепочки, отбрасывается, и обход выполняется как
раньше. `PlayJab(path_cache=False)` возвращает полный обход на каждой
операции, `clear_path_cache()` забывает запомненное. При включённом кэше
`StrictModeViolation` сообщают обходы, а не перепроверки: новый дубликат,
появившийся после прогрева, не обнаруживается до признания пути недействительным или очистки
пути. Потокобезопасный LRU хранит не более 1024 цепочек. Snapshots и
accessibility tree содержат только скопированные метаданные и не владеют
Java-ссылками. Закрытие одной или всех
сессий `PlayJab` оставляет attached-процессы живыми. Метода `PlayJab.launch()`
намеренно нет. `PlayJab.list_windows()` перечисляет все видимые сейчас
top-level Java-окна как дешёвые записи `JavaWindowInfo(hwnd, pid, title)` — без
открытия JAB context.

`JavaWindow.snapshot()` читает только корень окна. `Locator.exists()` —
немедленная нестрогая проверка первого совпадения; для ожидания используйте
`wait_for()`. Позиционные `first()` и `nth()` прекращают обход после нужного
совпадения. `showing_only=True` ищет показываемые узлы и отсекает скрытые ветви,
включая поддерево любого `collapsed`-узла — его содержимое toolkit не
отрисовывает; поведение `visible_only=True` остаётся прежним и ветви не
отсекает. Параметр
`max_depth=` ограничивает глубину обхода относительно точки старта locator-а,
чтобы неглубокая цель за глубоким показываемым sibling-ом не требовала полного
обхода этого sibling-а.

`Locator.all()` возвращает ленивые locator-ы для каждого совпадения, поэтому
чтение `.snapshot()` на каждом из них заново резолвит весь locator, включая
повторный обход дерева, для каждого совпадения. Если нужно только прочитать
все совпадения, используйте `all_snapshots()`: он переиспользует тот же
единственный обход, который уже делает `count()`.

Для форм доступны `focus()`, `fill()`, `clear()`, `check()`, `uncheck()`,
`select_option()`, `text_content()` и чтение состояний/атрибутов. Password можно
прочитать явно, но секреты скрываются из dump, snapshot, логов и ошибок. Индексы
таблиц начинаются с нуля; `as_table()` предоставляет размеры, snapshot, headers,
выделение строк, ячейки, ожидание текста и редактирование на месте через
`cell(...).fill(value)`. Метод поддерживает стандартный видимый текстовый
редактор Swing `JTable`: выбирает ячейку, передаёт ей фокус, открывает редактор
по F2, заменяет текст через Unicode Win32 input, подтверждает Enter и проверяет
модель таблицы через JAB. Для read-only и несовместимых custom editor-ов
поднимается `UnsupportedActionError`.

Чтение (`snapshot`, `text_content`, атрибуты и ячейки таблицы) разрешено и для
скрытых/disabled узлов. Действия требуют состояний visible, showing и enabled у
цели и всех предков. Все операции разрешения принимают `timeout=`; значение `0`
выполняет одну немедленную проверку. `LocatorTimeoutError` содержит
структурированную, ограниченную и редактированную для password диагностику.

В виртуализированных списках и деревьях находятся только materialized-узлы.
Явный `scroll(steps)` посылает wheel над целью: положительные значения
прокручивают вниз, отрицательные вверх, ноль ничего не делает. Автопрокрутки при
поиске нет. `accessible_value()` возвращает неизменяемые строковые
current/minimum/maximum; setter отсутствует в JAB из JDK 17.

`click()` использует синхронный JAB `AccessibleAction` элемента. Если его
обработчик открывает модальный `JDialog`, вызов может оставаться заблокированным
до закрытия диалога; остальные операции в это время не могут использовать
сериализованный worker JAB. Для кнопок, открывающих окна, используется явный
физический путь:

```python
with app.expect_window(title="Подтверждение") as pending:
    window.get_by_name("open.confirmation").click(opens_window=True)
dialog = pending.value
dialog.get_by_name("confirmation.ok").click()
```

Opt-in путь мыши требует интерактивной Windows desktop session. Автоматического
fallback с JAB нет; после клика восстанавливаются позиция курсора и DPI-контекст
вызывающего потока.

Подготовка окружения, настройка JAB, доступные импорты и диагностика описаны в
**[руководстве по началу работы](docs/getting-started.ru.md)**.

## Документация

- [Начало работы](docs/getting-started.ru.md)
- [Дизайн](docs/design.ru.md) ([English](docs/design.md)) — словарь
  module/interface/seam, применённый к реальному стеку, для контрибьюторов
- [Производительность](docs/performance.ru.md) ([English](docs/performance.md)) —
  чем профилировать поиск элементов и как читать цифры
- [Участие в разработке](CONTRIBUTING.md)
- [История изменений](CHANGELOG.md)

Модули внутри `play_jab._native` остаются деталями реализации и не должны
импортироваться прикладным кодом.

## Разработка

```powershell
uv sync --all-groups
uv run pytest
uv run pre-commit run --all-files
```

Все проверки, соглашения о коммитах и процесс выпуска описаны в
[CONTRIBUTING.md](CONTRIBUTING.md).

## Лицензия

Проект распространяется по [лицензии Apache 2.0](LICENSE).

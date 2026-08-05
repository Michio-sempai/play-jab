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
> **Pre-alpha.** Низкоуровневая основа JAB находится в активной
> разработке, стабильный публичный API автоматизации пока отсутствует. Сейчас
> пакет публично предоставляет иерархию исключений. Возможны несовместимые изменения.

## Возможности

- Нативная интеграция с Java Access Bridge для Windows
- Поддержка Python 3.11–3.14 и строгая статическая типизация
- Понятные ошибки настройки, окон, ссылок и нативных вызовов
- Автоматические тесты ABI, жизненного цикла, владения ссылками и интеграции с JDK 17
- Планируемый Playwright-подобный API на основе локаторов

## Требования

- Windows
- Python 3.11 или новее
- Среда Java с поддержкой Java Access Bridge
- Одинаковая архитектура Python и JAB DLL: 32 или 64 бита

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

Проверьте импорт публичного пакета:

```powershell
python -c "from play_jab import PlayJabError; print(PlayJabError.__name__)"
```

## Синхронный API

```python
from play_jab.sync_api import PlayJab, contains

with PlayJab(timeout=5_000) as jab:
    app = jab.launch(["java", "-jar", "application.jar"])
    window = app.window(title="Приложение")
    button = window.get_by_role("push button", name=contains("Сохранить"))
    button.wait_for(state="visible")
    button.click()
```

Методы `attach(hwnd=...)`, `attach(pid=...)` и `attach(title=...)` подключаются
к существующему процессу. Заголовки окон и обычные строковые locator-ы
сопоставляются точно и с учётом регистра. Locator-ы ленивы и получают свежий
JAB context для каждой операции; snapshots и accessibility tree содержат только
скопированные метаданные и не владеют Java-ссылками. Закрытие `PlayJab` никогда
не завершает процесс, запущенный через `launch()`.

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
- [Участие в разработке](CONTRIBUTING.md)
- [История изменений](CHANGELOG.md)

Пользовательские примеры автоматизации появятся вместе со стабильным API. До
этого модули внутри `play_jab._native` считаются деталями реализации и не должны
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

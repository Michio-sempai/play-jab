# Дизайн

[English version](design.md) · [Вернуться к README](../README_RU.MD)

Как устроен стек модулей `play-jab`, в терминах скилла
[`codebase-design`](../.claude/skills/codebase-design/SKILL.md): module,
interface, implementation, depth, seam, adapter. Определения — в самом
скилле; этот документ применяет их к реальному коду, а не пересказывает.

## Стек как набор модулей

Каждый слой архитектуры (см. `CLAUDE.md`) — это **module**: у него один
**interface** и скрытая за ним **implementation**. Слои обращаются только к
interface слоя ниже, никогда — к его implementation.

| Module | Interface | Depth |
| --- | --- | --- |
| `_native/types.py` | ctypes structs/typedefs | N/A — чистые данные, скрывать нечего |
| `_native/functions.py`, `dll.py` | `argtypes`/`restype`-таблицы, `load()` | shallow намеренно — только ABI-обвязка и порядок поиска |
| `_native/backend.py` (`NativeBackend`) | ~30 вызовов Access Bridge | **seam** — см. ниже |
| `_native/bridge.py` (`BridgeRuntime`) | `start`/`close`/`context_from_hwnd`/вызовы уровня `click`/... | deep |
| `_native/refs.py` (`JavaRef`) | `close()`, context manager, `.value`/`.vm_id`/`.closed` | deep |
| `_native/manager.py` (`RuntimeManager`/`RuntimeSession`) | `acquire()` → session с `close()`/`release()` | deep |
| `sync_api.py` (`PlayJab`, `JavaApplication`, `JavaWindow`, `Locator`) | ~30 методов locator'а, горстка методов `PlayJab`/`JavaWindow` | deep |
| `registry.py` (`AccessibilityRegistry`) | `role()`, `state()` | deep для небольшого модуля — валидация JDK role/state и политика расширения скрыты за двумя вызовами |
| `exceptions.py` | сама иерархия исключений | не module в обычном смысле — см. [Interface как error modes](#interface-как-error-modes) |

## Центральный seam: `NativeBackend`

`_native/backend.py` определяет `NativeBackend` как `Protocol`. Это **тот
самый** seam всей кодовой базы: всё, что выше него — `BridgeRuntime`,
`refs.py`, `manager.py`, весь `sync_api.py`, любая операция `Locator` —
написано против этого interface и никогда не обращается напрямую к
`ctypes`, дескрипторам DLL или реальной JVM.

Этому interface удовлетворяют два adapter'а:

- `DllBackend` — реальная implementation, маршалит вызовы в DLL Access
  Bridge.
- `FakeBackend` (`_native/fake.py`) — дерево узлов в памяти, реализующее тот
  же самый interface.

По принципу скилла — *"один adapter — это гипотетический seam, два —
настоящий"* — это настоящий seam: оба adapter'а существуют и оба
используются (`DllBackend` — integration-тестами против живого Swing-фикстура,
`FakeBackend` — каждым unit-тестом). Ничто выше `NativeBackend` не может
понять, с каким именно из них оно разговаривает — это и позволяет всему
набору unit-тестов работать без JVM, Access Bridge или Windows-сессии.

**Ширина interface честная, а не случайная.** У `NativeBackend` около
тридцати методов — заметно больше, чем "несколько методов", которые обычно
подразумевает deep interface. Эта ширина неотъемлема от того, что seam
должен абстрагировать (используемый вертикальный срез Access Bridge C API),
а не design smell: сузить его означало бы схлопнуть операции, которые на
уровне JAB реально независимы (текст vs. таблица vs. selection vs. события)
в более протекающий и труднее fake-able фасад. Depth при этом всё равно
проявляется на стороне *implementation*: `DllBackend` скрывает маршалинг
структур, ловушки с шириной `JOBJECT64` и обработку событий через callback;
`FakeBackend` скрывает целое fake-дерево узлов с семантикой
parent/child/table — за сигнатурами методов, которые вызывающий код читает
прямо по спецификации JAB.

**Seam несёт interface-инварианты, а не только форму методов.** По
определению "interface" из скилла — invariants и error modes — часть
interface, а не только сигнатура типов. Оба adapter'а обязуются отражать
нативные сбои (`FALSE`/null/`0`) как `None`/`False`/`0`, и *ни один из них
никогда не бросает исключение `play_jab`* — перевод сбоя backend'а в
публичную иерархию исключений — задача `BridgeRuntime`, слоем выше.
`FakeBackend` идёт дальше и кодирует второй инвариант прямо в собственных
режимах отказа: он различает *stale-контексты* (нормальная ситуация —
пересобранное Swing-дерево делает handle недействительным, и чтения просто
возвращают `FALSE`/null) и *misuse* (повторный release, неизвестный
cookie — `FakeBackendError`, подкласс `AssertionError`, никогда не
`PlayJabError`), чтобы тест не мог принять "fake поймал вас за
неправильным использованием" за настоящий нативный сбой.

## Seam'ы внутри `sync_api.py`

`sync_api.py` нужны две вещи, которых `NativeBackend` не предоставляет —
перечисление Win32-окон/синтетический ввод и проверка живости OS-процесса —
поэтому он определяет для них собственные seam'ы, подменяемые в тестах тем
же способом:

- `WindowBackend` (`Protocol`, `sync_api.py:205`) — `enum_windows`,
  `get_window_title/pid`, примитивы cursor/DPI/click/wheel. Реальный
  adapter — Win32-реализация, которую возвращает `_create_window_backend()`;
  тестовый adapter — `FakeWindowBackend` в `tests/conftest.py`, общий для
  семи тестовых файлов (раньше copy-paste в каждом файле — консолидация
  сама по себе была улучшением depth: один fake, один interface, вместо
  семи расходящихся друг от друга самодельных double'ов).
- `_create_runtime` / `_is_process_alive` — фабричные функции уровня модуля,
  которые `PlayJab` вызывает вместо прямого конструирования
  `BridgeRuntime` или проверки живости процесса напрямую. Тесты
  monkeypatch'ат их (см. `install_fake_runtime()` в `tests/conftest.py`),
  чтобы подставить `BridgeRuntime`, сам построенный поверх `FakeBackend`.

Обратите внимание, что именно подключает `install_fake_runtime()`:
**настоящий** `BridgeRuntime`, сконструированный с фабрикой `FakeBackend`.
Seam, который подменяется fake'ом для тестов `sync_api` — это
`NativeBackend`, слоем ниже; сам `BridgeRuntime` никогда не дублируется
fake'ом. Это осознанное решение: работа `BridgeRuntime` (владение потоком,
маршалинг через message pump, перевод исключений) — это ровно то поведение,
которое стоит проверять по-настоящему в каждом тесте, а не подменять
mock'ом.

## Сужение, которое не является seam'ом: `_RuntimeFacade`

`sync_api.py:225` определяет `_RuntimeFacade` — `Protocol`, покрывающий
подмножество `BridgeRuntime`, которое реально вызывает `sync_api`
(операции context/text/table/selection — без `start()`/`close()`/внутренностей
потока). Этому interface удовлетворяет только один adapter (`BridgeRuntime`),
поэтому по принципу скилла это **гипотетический seam**, а не настоящий — он
существует ради interface segregation и читаемости (документирует в одном
месте тот самый срез `BridgeRuntime`, от которого зависит `sync_api`), а не
ради заменяемости. Не путайте его со вторым тестовым seam'ом: подмена
`_RuntimeFacade` напрямую, в обход `BridgeRuntime` + `FakeBackend`, пропустила
бы перевод исключений и маршалинг через поток, которые тесты `sync_api` как
раз обязаны проверять.

## Depth deep-dives

Применяя **deletion test** из скилла — удалить module и посмотреть, где
всплывёт сложность — к модулям, скрывающим больше всего:

- **`BridgeRuntime`.** Удалите его — и каждому вызывающему коду (`refs.py`,
  `manager.py`, всему `sync_api.py`) понадобится собственный поток,
  собственный Win32 message pump и собственный маршалинг через
  command queue, чтобы безопасно вызывать не thread-safe `NativeBackend` из
  произвольных потоков вызывающего кода. Один deep module вместо N
  переизобретений "правильно владеть worker-потоком".
- **`JavaRef`.** Удалите его — и каждому месту, держащему
  `AccessibleContext`, придётся самому помнить, что это живая,
  принадлежащая JVM ссылка, которую нужно явно освобождать — не простой
  целочисленный id — и самому разбираться с балансом double-release/leak.
  `JavaRef` схлопывает это до `close()`/context manager, с
  `weakref.finalize` как страховкой, которая явно *не* является
  load-bearing (детерминированное освобождение всё равно происходит через
  `close()`).
- **`Locator`.** Удалите его — и каждый вызывающий код заинлайнил бы:
  повторное разрешение JAB-контекста при каждой операции (locator'ы ленивы,
  не кэшируются), проверку цепочки предков на visible/showing/enabled,
  которую требуют действия, но не чтения, обрезку `showing_only` против
  фильтрации без обрезки `visible_only`, и ограниченный, редактирующий
  password диагностический payload `LocatorTimeoutError`. Публичная
  поверхность — около тридцати методов в семействах query/read/act/wait —
  широко для "deep module", но depth сохраняется, потому что каждое
  семейство переиспользует одну и ту же приватную машинерию разрешения
  (`_resolve_once`, `_walk`, `_wait_strict`), а не дублирует её, и ни один
  вызывающий код не может добраться до этой машинерии напрямую.
- **`RuntimeManager`/`RuntimeSession`.** Удалите их — и каждому экземпляру
  `PlayJab` в процессе пришлось бы напрямую координироваться насчёт того,
  можно ли разделить `BridgeRuntime` (один поток, одна DLL) или его нужно
  отвергнуть как несовместимый — `acquire()`/`release()` плюс счётчик
  generation — это ровно то, что стоит между "разделить runtime" и
  "незаметно повредить состояние между двумя путями к DLL".

## Interface как error modes

Глоссарий скилла прямо говорит, что interface включает "error modes", а не
только форму вызовов. `exceptions.py` — то место, где это проявляется как
самостоятельное дизайн-решение, а не деталь реализации:
`JavaReferenceClosedError` — **sibling** для `BridgeClosedError`, а не
subclass. Это осознанное решение, а не недосмотр — широкий обработчик
`except BridgeClosedError` (трактующий весь runtime как мёртвый) не должен
заодно проглатывать восстановимую stale-ссылку, а `except BridgeClosedError:
retry` не должен бесконечно повторять попытки против runtime, который на
самом деле мёртв. Эта иерархия — часть публичного interface в той же мере,
что и любая сигнатура метода; менять её — решение о совместимости, а не
рефакторинг.

## Relationships на практике

По скиллу: у module один interface; depth измеряется относительно этого
interface; seam — это место, где живёт interface; adapter ему
удовлетворяет. Конкретно в этой кодовой базе:

```text
NativeBackend (seam, _native/backend.py)
├── DllBackend        (adapter — реальная DLL)
└── FakeBackend        (adapter — дерево узлов в памяти)
        ↑ оба используются только через BridgeRuntime

WindowBackend (seam, sync_api.py)
├── реальная Win32-реализация (adapter)
└── FakeWindowBackend         (adapter — tests/conftest.py)

_RuntimeFacade (сужение через interface segregation, не seam — один adapter: BridgeRuntime)
```

Всё, что выше `NativeBackend`/`WindowBackend`, получает свой **leverage**
(одна implementation `BridgeRuntime`/`Locator` окупается на каждом call
site и в каждом тесте) и свою **locality** (особенность JAB чинится один
раз, в `DllBackend` или `BridgeRuntime`, а не переоткрывается в каждом
месте вызова) именно от того, что эти два seam'а остаются на своих местах.

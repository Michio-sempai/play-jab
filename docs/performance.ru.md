# Производительность: как мерить и куда смотреть

[English version](performance.md) · [Вернуться к README](../README_RU.MD)

Документ самодостаточен: его можно скопировать в любой репозиторий, где
play-jab автоматизирует Java-приложение. Он отвечает на два вопроса — **чем
мерить** и **что именно смотреть в цифрах**, чтобы «тесты зависли» превратилось
в конкретный диагноз.

## 1. Модель стоимости: всё считается в узлах

У play-jab нет «медленного кода» на Python. Время уходит в вызовы Access
Bridge, каждый из которых — межпроцессный round-trip к JVM. Замеры на реальном
Swing-клиенте (JDK 17, x64, Windows 11):

| Нативный вызов | Среднее |
| --- | --- |
| `getAccessibleContextInfo` | ≈ 500–780 мкс |
| `getAccessibleChildFromContext` | ≈ 130–170 мкс |
| `releaseJavaObject` | ≈ 85–120 мкс |
| `getAccessibleText` | ≈ 400–500 мкс |
| `pump_messages` | ≈ 20 мкс |

Полный обход одного узла дерева = child + info + release ≈ **0.75 мс**.
Отсюда единственная величина, которая имеет значение:

> **Сколько узлов дерева обошёл локатор.**

Пять тысяч узлов — это четыре секунды, и никакая микрооптимизация Python этого
не изменит. Поэтому и мерить надо не «сколько миллисекунд», а «сколько узлов и
почему столько».

## 2. Чем мерить: профилировщик на 40 строк

Оберните методы `DllBackend` и `BridgeRuntime._submit` — этого достаточно,
чтобы разложить любую операцию на нативные вызовы и накладные расходы очереди.
Подключать
**до** создания `PlayJab`.

```python
import collections
import time

from play_jab._native import backend as backend_module
from play_jab._native.bridge import BridgeRuntime

STATS: dict[str, list[float]] = collections.defaultdict(list)
SUBMIT = {"count": 0, "time": 0.0}


def instrument() -> None:
    """Замерить каждый нативный вызов и каждый переход в worker-поток."""
    cls = backend_module.DllBackend
    for attr in dir(cls):
        if attr.startswith("_") or not callable(getattr(cls, attr)):
            continue

        def wrap(name, original):
            def wrapper(self, *args, **kwargs):
                started = time.perf_counter()
                try:
                    return original(self, *args, **kwargs)
                finally:
                    STATS[name].append(time.perf_counter() - started)

            return wrapper

        setattr(cls, attr, wrap(attr, getattr(cls, attr)))

    original_submit = BridgeRuntime._submit

    def submit(self, fn):
        started = time.perf_counter()
        try:
            return original_submit(self, fn)
        finally:
            SUBMIT["count"] += 1
            SUBMIT["time"] += time.perf_counter() - started

    BridgeRuntime._submit = submit


def report(label: str, wall: float) -> None:
    native = sum(sum(samples) for samples in STATS.values())
    print(f"\n=== {label}: {wall * 1000:.0f} ms ===")
    print(f"  _submit: {SUBMIT['count']} вызовов, {SUBMIT['time'] * 1000:.0f} ms")
    print(f"  нативных: {sum(len(v) for v in STATS.values())}, {native * 1000:.0f} ms")
    for name, samples in sorted(STATS.items(), key=lambda kv: -sum(kv[1]))[:8]:
        total = sum(samples)
        print(
            f"    {name:38s} n={len(samples):6d} total={total * 1000:8.1f} ms "
            f"avg={total / len(samples) * 1e6:7.0f} us"
        )
    print(
        f"  накладные расходы очереди/потока: {(SUBMIT['time'] - native) * 1000:.0f} ms"
    )


def reset() -> None:
    STATS.clear()
    SUBMIT.update(count=0, time=0.0)
```

Использование — довести приложение до нужного экрана, потом мерить по одной
операции:

```python
reset()
started = time.perf_counter()
page.field.text_content()
report("field.text_content()", time.perf_counter() - started)
```

**Обязательно мерьте каждую операцию дважды.** Первый вызов цепочки локатора
холодный (полный обход), второй — горячий (проверка запомненного пути). Одна
холодная цифра ничего не говорит о том, как поведёт себя тест.

## 3. Куда смотреть в отчёте

Читайте отчёт в таком порядке.

**`n` у `getAccessibleContextInfo` — это число обойдённых узлов.** Главная
цифра. Всё остальное — следствие.

- `n` в тысячах на «найти одну кнопку» → локатор обходит чужие поддеревья.
  Идите в п. 4.
- `n` в десятках, а время всё равно большое → проблема не в поиске, смотрите
  на конкретный вызов в верхних строках отчёта (`do_accessible_actions` может
  блокироваться на модальном диалоге).

**`_submit: N вызовов` — число переходов в worker-поток.** Полный обход должен
давать **единицы** `_submit`, а не тысячи: и обход дерева, и чтение пути
выполняются целиком внутри одного шага worker-потока. Если `_submit`
пропорционален числу узлов — вы на старой версии play-jab либо обходите дерево
своим кодом через публичный API.

**«Накладные расходы очереди/потока» — разница между `_submit` и суммой нативных
вызовов.** Норма — единицы процентов. Десятки процентов означают, что операция
дробится на множество мелких round-trip'ов.

## 4. Три типовые причины «лишних» узлов

Чтобы увидеть форму дерева, снимите размеры поддеревьев — обычно этого
достаточно, чтобы причина стала очевидной:

```python
tree = window.accessibility_tree(max_depth=100, max_nodes=50_000)


def sizes(node, path=(), depth=0):
    size = 1 + sum(
        sizes(child, (*path, i), depth + 1) for i, child in enumerate(node.children)
    )
    if depth <= 6 and size >= 50:
        snap = node.snapshot
        print(
            f"{'  ' * depth}[{size:6d}] {snap.role} {snap.name!r} "
            f"states={sorted(snap.states)} path={path}"
        )
    return size


sizes(tree)
```

Дальше ищите одно из трёх.

**(а) Все экраны приложения живут в дереве одновременно.** Типично для
CardLayout: активна одна панель, остальные остаются в дереве целиком. У них нет
состояния `showing`.
*Лечение:* `showing_only=True` в локаторе — play-jab обрезает такие поддеревья
целиком, по одному `getAccessibleContextInfo` на панель вместо тысяч.

**(б) Свёрнутое дерево/таблица отдаёт всех потомков.** JTree со свёрнутыми
узлами честно возвращает `childrenCount` в тысячах; у детей нет ни `showing`,
ни `visible` — только `collapsed`.
*Лечение:* тот же `showing_only=True` — play-jab не спускается в узел с
состоянием `collapsed`. Без него каждый из тысяч потомков будет прочитан и
отброшен по отдельности.

**(в) Цель лежит поздно в порядке обхода.** DFS идёт слева направо: если нужный
элемент — сосед справа от большого дерева, обход сначала оплатит дерево.
*Лечение:* привязать локатор к ближайшему стабильному контейнеру
(`window.get_by_name("app.editor").get_by_name("app.editor.name")`) и/или
задать `max_depth=`, ограничивающий спуск относительно старта локатора.

## 5. Что play-jab делает сам (и как это выключить для сравнения)

| Механизм | Эффект | Как отключить |
| --- | --- | --- |
| Обход всего поддерева внутри одного шага worker-потока (`BridgeRuntime.traverse`) | ~1.9× | — |
| Кэш путей: повторное разрешение читает запомненный путь (`read_path`) вместо обхода | 100–700× на горячем пути | `PlayJab(path_cache=False)`, `PlayJab.clear_path_cache()` |
| Отсечение `collapsed`-поддеревьев при `showing_only=True` | до 50× на холодном пути | не использовать `showing_only` |

Кэш путей использует в качестве ключа пару (HWND, цепочка локатора), поэтому
**одинаковые цепочки должны использоваться повторно**. Это потокобезопасный LRU не более чем на
1024 цепочки. Типичная ошибка page object'а:

```python
# две разные цепочки → два холодных обхода
locator = window.get_by_role("push button", name=name)
if locator.exists():
    return locator.first()

# одна цепочка → один обход, дальше из кэша
locator = window.locator(role="push button", name=name, showing_only=True).first()
if locator.exists():
    return locator
```

Запомненный путь восстанавливается автоматически: если он перестал удовлетворять любому
шагу цепочки, запись выбрасывается и выполняется обычный обход. Обратная
сторона — `StrictModeViolation` («совпадений больше одного») ловится обходами, а
не каждым обращением. Для сравнения «как было» гоняйте профиль с
`path_cache=False`; используйте этот режим, если обнаружение новых дубликатов
на каждой strict-операции важнее задержки горячего пути.

## 6. Ориентиры

На клиенте с деревом ~13 000 узлов после включения всех трёх механизмов:

| Операция | До | Холодная | Горячая |
| --- | --- | --- | --- |
| `element(...).exists()` | 6 000 мс | 81 мс | 14 мс |
| чтение поля карточки | 6 700 мс | 124 мс | 31 мс |
| запись поля карточки | 13 400 мс | 90 мс | 54 мс |
| выбор узла в дереве | 13 100 мс | 66 мс | 50 мс |
| перечисление 15 полей | 27 800 мс | 571 мс | 126 мс |

Если ваши цифры на порядок хуже — почти наверняка это п. 4 (а) или (б):
локатор ищет без `showing_only` и оплачивает чужие экраны.

## 7. Чего профилировщик не покажет

- **Ожидание самого приложения.** `do_accessible_actions` блокируется, пока
  Java-обработчик не вернёт управление; синхронно открытый модальный диалог
  держит worker-поток. Это видно как один вызов на десятки/сотни миллисекунд,
  а не как большое `n`.
- **`time.sleep()` в вашем коде.** Разница между wall-временем операции и
  суммой `_submit` — это ваш собственный код и явные ожидания.
- **Перестройку Swing-дерева.** Разворачивание/сворачивание окна делает
  запомненные пути недействительными; следующая операция будет холодной. Это
  норма, а не утечка.

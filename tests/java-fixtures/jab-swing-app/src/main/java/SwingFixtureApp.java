import java.awt.BorderLayout;
import java.awt.Component;
import java.awt.Container;
import java.awt.Dimension;
import java.awt.FlowLayout;
import java.awt.FocusTraversalPolicy;
import java.awt.GridBagConstraints;
import java.awt.GridBagLayout;
import java.awt.Insets;
import java.awt.event.FocusAdapter;
import java.awt.event.FocusEvent;
import java.awt.event.FocusListener;
import java.awt.event.WindowAdapter;
import java.awt.event.WindowEvent;
import java.util.Arrays;
import java.util.Locale;
import javax.accessibility.Accessible;
import javax.swing.BorderFactory;
import javax.swing.BoxLayout;
import javax.swing.DefaultListModel;
import javax.swing.JButton;
import javax.swing.JCheckBox;
import javax.swing.JComboBox;
import javax.swing.JDialog;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JList;
import javax.swing.JMenu;
import javax.swing.JMenuBar;
import javax.swing.JMenuItem;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JPasswordField;
import javax.swing.JProgressBar;
import javax.swing.JScrollPane;
import javax.swing.JSlider;
import javax.swing.JSplitPane;
import javax.swing.JTabbedPane;
import javax.swing.JTable;
import javax.swing.JTextField;
import javax.swing.JTree;
import javax.swing.ListSelectionModel;
import javax.swing.SwingUtilities;
import javax.swing.Timer;
import javax.swing.UIManager;
import javax.swing.UnsupportedLookAndFeelException;
import javax.swing.WindowConstants;
import javax.swing.table.DefaultTableModel;
import javax.swing.tree.DefaultMutableTreeNode;
import javax.swing.tree.DefaultTreeModel;

/**
 * Общая Swing fixture для интеграционных тестов {@code play-jab}: покрывает
 * button, text/password fields, checkbox, combo/list, tabs, table, read-only
 * locator-сценарии и динамически добавляемые элементы
 * (CONCEPT.MD → «Тестирование» → Integration).
 *
 * <p>Узкая regression fixture для зависания JAB на модальном {@code JDialog}
 * живёт отдельно в {@link JabDialogRepro} и запускается независимо
 * ({@code FixtureLauncher dialog} / Gradle-задачи {@code runDialogRepro},
 * {@code runDialogFirst}).
 *
 * <h2>Заголовок окна</h2>
 * {@code "JAB swing fixture"} — главное окно для Win32-поиска. Аргумент
 * {@code --second-window} добавляет в тот же процесс окно
 * {@code "JAB swing fixture secondary"}; это детерминированный сценарий
 * строгого поиска окна без селектора.
 *
 * <h2>Опциональные системные свойства</h2>
 * {@code -Dfixture.lookAndFeel=windows} — реальный Windows L&amp;F вместо
 * кросс-платформенного Metal по умолчанию (для теста, что locator/accessible-name
 * поведение не зависит от L&amp;F). {@code -Dfixture.autoNode=false} — отключает
 * 3000&nbsp;мс цикл {@code fixture.auto_node} целиком, для тестов точного
 * live-reference count, которым мешает его собственный attach/detach трафик.
 *
 * <h2>Accessible-имена (стабильные, не зависят от локали)</h2>
 * <pre>
 * fixture.main                      JFrame            главное окно fixture
 * fixture.menu_bar                  JMenuBar          строка меню главного окна
 * fixture.menu_file                 JMenu             меню "File" (обычное действие + диалог)
 * fixture.menu_item_status          JMenuItem         обычное действие: пишет в fixture.status_label
 * fixture.menu_item_open_dialog     JMenuItem         открывает APPLICATION_MODAL fixture.menu_dialog
 * fixture.menu_dialog               JDialog           открыт из меню, а не из кнопки
 * fixture.menu_dialog_label         JLabel            содержимое fixture.menu_dialog
 * fixture.menu_dialog_close_button  JButton           закрывает fixture.menu_dialog
 * fixture.menu_dialogs              JMenu             меню "Dialogs" (три JOptionPane)
 * fixture.menu_item_message_dialog  JMenuItem         открывает JOptionPane.showMessageDialog
 * fixture.menu_item_confirm_dialog  JMenuItem         открывает JOptionPane Yes/No (явные labels)
 * fixture.menu_item_input_dialog    JMenuItem         открывает JOptionPane с текстовым полем
 * fixture.tabs                      JTabbedPane       пять вкладок
 * fixture.tab_form_page             page tab          заголовок вкладки "Form"
 * fixture.tab_table_page            page tab          заголовок вкладки "Table"
 * fixture.tab_dynamic_page          page tab          заголовок вкладки "Dynamic"
 * fixture.tab_locator_page          page tab          заголовок вкладки "Locator"
 * fixture.tab_workloads_page        page tab          заголовок вкладки "Workloads"
 * fixture.tab_form                  JPanel            содержимое вкладки "Form"
 * fixture.tab_table                 JPanel            содержимое вкладки "Table"
 * fixture.tab_dynamic               JPanel            содержимое вкладки "Dynamic"
 * fixture.tab_locator               JPanel            read-only locator-сценарии
 * fixture.tab_workloads             JPanel            виртуализация и динамика workload'ов
 *
 * fixture.username_field            JTextField        обычный текстовый ввод (fill/clear)
 * fixture.password_field            JPasswordField    password text; содержимое не логируется
 * fixture.remember_checkbox         JCheckBox         check()/uncheck()/is_checked()
 * fixture.role_combo                JComboBox         select_option: Viewer / Editor / Admin
 * fixture.environment_list          JList             select_option: dev / staging / prod
 * fixture.submit_button             JButton           пишет результат в fixture.status_label
 * fixture.disabled_button           JButton           всегда disabled: is_enabled() == false
 * fixture.status_label              JLabel            наблюдаемый результат клика по submit
 * fixture.unicode_label             JLabel            не-ASCII текст для проверки UTF-16
 *
 * fixture.table                     JTable            100 строк x 5 колонок, см. ниже
 * fixture.synthetic_table           AccessibleTable   diagnostic non-actionable cell
 * fixture.synthetic_cell_0_0        AccessibleContext ячейка без bounds и без action
 * fixture.synthetic_row_header_0    AccessibleContext row header, которого не даёт настоящий JTable
 * fixture.synthetic_merged_cell     AccessibleContext строки 1-2: rowExtent=2, с bounds
 * fixture.table_scrollbar_vertical  JScrollBar        AccessibleValue для ручной прокрутки
 * fixture.mark_done_button          JButton           cell(7, 3): "Processing" -> "Done"
 * fixture.reset_table_button        JButton           возвращает cell(7, 3) в "Processing"
 * fixture.table_add_row_button      JButton           100 -> 101 строк (см. fixture.table_row_count_status)
 * fixture.table_remove_row_button   JButton           101 -> 100 строк
 * fixture.table_row_count_status    JLabel            "rows=&lt;N&gt;", обновляется TableModelListener'ом
 * fixture.select_row_button         JButton           строка 7 + все 5 колонок (mixed mode)
 * fixture.select_column_button      JButton           колонка 3 + все 100 строк (mixed mode)
 * fixture.select_few_button         JButton           строки 1, 3, 5; column selection выключен
 * fixture.clear_selection_button    JButton           снимает выделение
 *
 * fixture.dynamic_panel             JPanel            контейнер динамических элементов
 * fixture.add_item_button           JButton           добавляет fixture.dynamic_item_N
 * fixture.remove_item_button        JButton           удаляет последний добавленный элемент
 * fixture.dynamic_count_label       JLabel            текущее число элементов
 * fixture.dynamic_item_N            JLabel            N начинается с 1 и не переиспользуется
 *
 * fixture.scope_alpha               JPanel            первый scoped-контейнер
 * fixture.scope_beta                JPanel            второй scoped-контейнер
 * fixture.duplicate                 JButton x2        одинаковое имя в разных контейнерах
 * fixture.visible_button            JButton           видимый и enabled
 * fixture.hidden_button             JButton           в дереве, но setVisible(false)
 * fixture.locator_disabled_button   JButton           видимый, но disabled
 * fixture.state_panel               JPanel            контейнер visible/hidden/disabled кнопок
 * fixture.scopes                    JPanel            контейнер fixture.scope_alpha/beta
 * fixture.auto_panel                JPanel            контейнер автоматически меняемого узла
 * fixture.auto_node                 JLabel            каждые 3000 мс добавляется/удаляется
 * fixture.value_panel               JPanel            контейнер AccessibleValue-виджетов
 * fixture.progress_bar              JProgressBar      AccessibleValue 0..100, текущее 42
 * fixture.slider                    JSlider           AccessibleValue 0..10, текущее 3
 * fixture.text_and_render_panel     JPanel            контейнер длинного текста и custom renderer
 * fixture.boundary_text_field       JTextField        2002 code unit, суррогатная пара на границе чанка 1023
 * fixture.custom_rendered_list      JList             3 элемента, кастомный ListCellRenderer
 * fixture.secondary                 JFrame            опциональное второе top-level окно
 * fixture.secondary_label           JLabel            содержимое fixture.secondary
 *
 * fixture.virtual_list              JList             виртуализированный список на 1000 элементов
 * fixture.virtual_list_start_button JButton           прокручивает к элементу 0
 * fixture.virtual_list_500_button   JButton           прокручивает к элементу 500
 * fixture.virtual_list_end_button   JButton           прокручивает к элементу 999
 * fixture.virtual_list_status       JLabel            "first=&lt;N&gt; last=&lt;N&gt;" видимого диапазона
 * fixture.virtual_list_scrollbar_vertical  JScrollBar  вертикальная прокрутка списка
 * fixture.virtual_tree              JTree             виртуализированное дерево: 40 групп x 5 узлов
 * fixture.virtual_tree_group_NN     tree node         группа 00..39
 * fixture.virtual_tree_group_NN_item_MM  tree node    узел MM группы NN
 * fixture.virtual_tree_expand_button   JButton        разворачивает все строки дерева
 * fixture.virtual_tree_collapse_button JButton        сворачивает все строки, кроме корня
 * fixture.virtual_tree_show_button     JButton        выделяет и скроллит к последней строке
 * fixture.virtual_tree_reset_button    JButton        снимает выделение, скроллит к началу
 * fixture.virtual_tree_status          JLabel         "expanded=.. selected=.. first=.. last=.."
 * fixture.workload_dynamic_host     JPanel            хост для attach/detach/replace-сценариев
 * fixture.workload_dynamic_node     JLabel            description = "generation=&lt;N&gt;"
 * fixture.workload_attach_button    JButton           добавляет узел, если он отсутствует
 * fixture.workload_detach_button    JButton           убирает узел из хоста
 * fixture.workload_visibility_button JButton          переключает setVisible на узле
 * fixture.workload_enabled_button   JButton           переключает setEnabled на узле
 * fixture.workload_replace_button   JButton           убирает и добавляет узел новой generation
 * </pre>

 * <h2>Read-only locator-сценарии</h2>
 * Две кнопки {@code fixture.duplicate} намеренно неразличимы по role/name, но
 * лежат под разными стабильными контейнерами. Их descriptions равны
 * {@code "duplicate in alpha"} и {@code "duplicate in beta"}. Скрытая кнопка
 * остаётся дочерним компонентом {@code fixture.tab_locator}, но не получает
 * visible/showing state. {@code fixture.auto_node} отсутствует при старте,
 * затем Swing Timer каждые 3000 мс попеременно добавляет и удаляет его — окно
 * достаточно широкое, чтобы обход виртуализированных деревьев на вкладке
 * Workloads на медленных установках JAB не терял такт. Поэтому polling-тест
 * может переждать как attached, так и detached независимо от того, насколько
 * быстро он подключился к процессу.
 *
 * <h2>Как читать текст лейблов</h2>
 * Обычный (не-HTML) {@code JLabel} не публикует {@code AccessibleText}:
 * {@code getAccessibleText()} возвращает null, а единственным носителем
 * содержимого остаётся accessible name, который здесь занят стабильным
 * идентификатором. Поэтому каждый лейбл fixture (включая
 * {@code fixture.dynamic_item_N}) дублирует отображаемый текст в accessible
 * description. Тест читает результат клика как
 * {@code get_attribute("description")} на {@code fixture.status_label}, а не как
 * {@code text_content()}. У {@code fixture.unicode_label} description содержит
 * {@code "Привет · 日本語 · naïve · ✓ · 🚀"}: 28 code points при {@code length() == 29},
 * то есть последний символ — суррогатная пара UTF-16. Это проверка декодирования
 * fixed-size UTF-16 буферов JAB, а не только не-ASCII как такового.
 *
 * <h2>Переключение вкладок</h2>
 * Дочерние узлы {@code fixture.tabs} (role "page tab") <b>не публикуют
 * AccessibleAction</b>, поэтому кликнуть по вкладке через
 * {@code doAccessibleActions} нельзя. Переключение идёт через
 * {@code AccessibleSelection} самого {@code fixture.tabs}:
 * {@code addAccessibleSelection(index)}, где 0 = Form, 1 = Table, 2 = Dynamic,
 * 3 = Locator, 4 = Workloads. Приложение стартует на вкладке Form.
 *
 * <h2>Таблица {@code fixture.table}</h2>
 * <ul>
 *   <li>{@code row_count() == 100}, {@code column_count() == 5};
 *       колонки: ID, Name, Owner, Status, Progress (все значения — строки).</li>
 *   <li>Текст ячейки читается как accessible <b>name</b> её context-а
 *       ({@code cell(7, 1)} → {@code "job-7"}). {@code getAccessibleText()} у ячейки
 *       возвращает null — ровно как у JLabel выше. Реализация
 *       {@code cell(...).text_content()} должна брать name, а не AccessibleText.</li>
 *   <li>Изменяемое значение: {@code cell(7, 3)} стартует как {@code "Processing"};
 *       {@code fixture.mark_done_button} переводит её в {@code "Done"}
 *       ({@code wait_for_text("Done")}), {@code fixture.reset_table_button} —
 *       обратно, чтобы тест можно было повторить без перезапуска процесса.
 *       Остальные строки в колонке Status всегда {@code "Queued"}.</li>
 *   <li>Изменяемое число строк: {@code fixture.table_add_row_button} переводит
 *       {@code row_count()} 100 &rarr; 101 (добавляет {@code "job-100"}),
 *       {@code fixture.table_remove_row_button} — обратно; повторное нажатие
 *       кнопки при уже применённом состоянии не действует ({@code row_count()}
 *       не выходит за 100..101). {@code fixture.table_row_count_status}
 *       публикует {@code "rows=&lt;N&gt;"} через {@code TableModelListener} —
 *       наблюдаемый сигнал именно {@code PropertyTableModelChange}, а не
 *       polling значения ячейки.</li>
 * </ul>
 *
 * <h3>Видимые и невидимые строки</h3>
 * Viewport рассчитан на {@code VISIBLE_ROW_COUNT} строк, автопрокрутки нет.
 * Измерено in-process на JDK 17 после переключения на вкладку Table: состояние
 * {@code showing} есть у строк <b>0..9</b>, первая строка без {@code showing} —
 * <b>10</b>. Тест, фиксирующий границу, должен опираться на это измеренное
 * число, а не на «сколько строк влезло на глаз».
 *
 * <p><b>Дискриминатор — только state set, не bounds.</b>
 * {@code AccessibleJTableCell.getBounds()} — это
 * {@code table.getCellRect(row, column, false)}, и он всегда возвращает
 * валидный неотрицательный прямоугольник независимо от прокрутки: у
 * {@code cell(7, 1)} это {@code [x=146,y=112,w=145,h=15]}, у {@code cell(99, 1)} —
 * {@code [x=146,y=1584,w=145,h=15]}. <b>Эти числа сняты при 100% DPI и приведены
 * для иллюстрации</b>: конкретные пиксели зависят от масштабирования экрана,
 * шрифта и Look&amp;Feel и будут другими на runner-е со 125% (CONCEPT §7), поэтому
 * подставлять их в реальные assert-ы нельзя. Проверяемое утверждение — знак и
 * определённость прямоугольника, а не его размеры. Обычный JTable структурно не способен отдать
 * ячейку с {@code bounds == -1}. Отличается именно набор состояний: у строки 7
 * есть {@code showing}, у строки 99 его нет. Данные ({@code "job-99"}) через
 * AccessibleTable читаются в обоих случаях.
 *
 * <p><b>Ловушка: {@code showing} у ячейки не учитывает скрытую вкладку.</b>
 * Состояние ячейки вычисляется как пересечение {@code cellRect} с
 * {@code visibleRect} таблицы и ничего не знает о том, выбрана ли вкладка.
 * Измерено сразу после запуска, когда выбрана вкладка Form, а Table скрыта:
 * {@code cell(7, 1)} уже сообщает {@code showing == true}, хотя физически на
 * экране её нет. У самой таблицы {@code showing} при этом отсутствует, а
 * {@code getLocationOnScreen()} возвращает null и для таблицы, и для всех ячеек.
 * Поэтому actionability check по одному лишь {@code showing} ячейки ошибочен —
 * проверять нужно и предков. Тест обязан сначала выбрать вкладку Table через
 * AccessibleSelection, и только потом различие строк 7 и 99 означает то, что
 * ожидается.
 *
 * <p><b>Известное ограничение fixture.</b> Ни одна ячейка JTable не публикует
 * AccessibleAction: {@code getAccessibleAction()} возвращает null и для видимой
 * строки 7, и для невидимой строки 99. Переход «ячейка не материализована →
 * действий нет; прокрутили → действие появилось» на этой fixture
 * <b>продемонстрировать невозможно</b> — это свойство самого Swing JTable, а не
 * недоделка. Проверять здесь можно только чтение данных и {@code showing};
 * ячейка как цель для {@code doAccessibleActions} не тестируется нигде в этой
 * fixture.
 *
 * <p><b>Прокрутка: как её проверять из play_jab, а не in-process.</b>
 * {@code fixture.table_scrollbar_vertical} действительно материализует строки
 * при прокрутке — измерено в процессе вызовом
 * {@code AccessibleValue.setCurrentAccessibleValue(1440)}, после чего
 * {@code showing} получают строки <b>90..99</b>, а строка 7 его теряет
 * ({@code getBounds()} ячейки при этом не меняется — {@code y == 1584} остаётся
 * координатой внутри таблицы, не экрана, — и {@code getAccessibleAction()}
 * остаётся null). <b>Этот setter недоступен из play_jab</b>: CONCEPT.MD §7
 * («AccessibleValue доступен только для чтения — JDK 17 JAB не экспортирует
 * setter») и сам факт, что в {@code src/play_jab/} нет ни одного вызова
 * {@code setCurrentAccessibleValue}, а есть только {@code Locator.scroll(steps)},
 * посылающий явный Win32 mouse-wheel по экранным координатам цели. Тест на
 * прокрутку этой fixture обязан идти через {@code Locator.scroll()}, а не
 * пытаться писать в {@code AccessibleValue} напрямую — приведённые выше числа
 * лишь доказывают, что материализация в принципе работает на этой fixture,
 * а не то, как её вызывать из библиотеки.
 *
 * <h3>Selection</h3>
 * Кнопки выделения работают в двух разных режимах JTable, и это важно:
 * <ul>
 *   <li>{@code fixture.select_row_button} и {@code fixture.select_column_button}
 *       работают в «смешанном» режиме: {@code setRowSelectionAllowed(true)} +
 *       {@code setColumnSelectionAllowed(true)}. Это <b>не</b> то же самое, что
 *       {@code setCellSelectionEnabled(true)}, хотя публичный getter разницы не
 *       показывает: {@code getCellSelectionEnabled()} возвращает true в обоих
 *       случаях, потому что он всего лишь выведен из
 *       {@code getRowSelectionAllowed() && getColumnSelectionAllowed()}.
 *       {@code AccessibleJTable} же читает <i>приватное поле</i>
 *       {@code cellSelectionEnabled}, которое выставляет только настоящий вызов
 *       {@code setCellSelectionEnabled()}; смешанный режим оставляет его false,
 *       и accessible-слой уходит в ветку «не cell selection». Измерено на двух
 *       одинаковых JTable с идентичным выделением:
 *       {@code getAccessibleSelectionCount()} даёт <b>500</b>
 *       ({@code rowCount * columnCount}) в смешанном режиме против <b>5</b> при
 *       настоящем {@code setCellSelectionEnabled(true)}. Вот откуда берётся 500 —
 *       и это режим на старте приложения. Измерено также: первая кнопка даёт
 *       {@code selected_rows() == [7]} и все 5 колонок, вторая —
 *       {@code selected_columns() == [3]} и все 100 строк, то есть count к
 *       реальному выделению отношения не имеет. Это и есть предупреждение CONCEPT §6
 *       «не смешивая индексы children и индексы selection»: доверять здесь можно
 *       {@code getSelectedAccessibleRows/Columns} и {@code isAccessibleSelected},
 *       но не count. Предел {@code MAX_TABLE_SELECTIONS == 64} превышает только
 *       {@code fixture.select_column_button}: его массив выделенных строк
 *       содержит 100 элементов, и молча обрезать его нельзя. У
 *       {@code fixture.select_row_button} массивы короткие (1 строка, 5 колонок)
 *       и в предел укладываются — превышает лимит лишь бесполезный здесь
 *       count == 500.</li>
 *   <li>{@code fixture.select_few_button} выключает column selection и выделяет
 *       строки 1, 3, 5. Это единственный сценарий с честными числами: измерено
 *       {@code selected_rows() == [1, 3, 5]}, {@code selected_columns() == []},
 *       {@code getAccessibleSelectionCount() == 15} (3 строки x 5 колонок), то
 *       есть в пределах {@code MAX_TABLE_SELECTIONS}. Нормальный положительный
 *       случай, на котором проверяется, что маленькое выделение не искажается.</li>
 *   <li>{@code fixture.clear_selection_button} снимает выделение и намеренно
 *       <b>не</b> трогает режим: молчаливая смена режима внутри «clear» была бы
 *       скрытым побочным эффектом. Измерено: из любого режима даёт
 *       {@code selected_rows() == []}, {@code selected_columns() == []},
 *       {@code getAccessibleSelectionCount() == 0}, но режим остаётся тем,
 *       который выставила последняя нажатая кнопка выделения. Тесту, которому
 *       нужен конкретный режим, следует нажать соответствующую кнопку, а не
 *       полагаться на порядок вызовов.</li>
 * </ul>
 */
public final class SwingFixtureApp {

    private static final String[] COLUMN_NAMES = {"ID", "Name", "Owner", "Status", "Progress"};
    private static final int ROW_COUNT = 100;

    /**
     * Скролл-панель таблицы кладётся в BorderLayout.NORTH, поэтому получает
     * ровно свою preferred height, а не растягивается до высоты самой высокой
     * вкладки. Иначе граница видимых строк уезжает и её нельзя зафиксировать
     * в тесте.
     */
    static final int VISIBLE_ROW_COUNT = 10;

    /** Ячейка с изменяемым значением; совпадает с примером в CONCEPT.MD §6. */
    private static final int MUTABLE_ROW = 7;
    private static final int STATUS_COLUMN = 3;

    private final DefaultTableModel tableModel = buildTableModel();
    private final JTable table = new JTable(tableModel);
    private final JLabel statusLabel = new JLabel();
    private final JPanel dynamicPanel = new JPanel();
    private final JLabel dynamicCountLabel = new JLabel();
    private final JPanel autoPanel = new JPanel(new FlowLayout(FlowLayout.LEFT));
    private final JLabel autoNode = new JLabel("Automatic node");
    private Timer autoNodeTimer;

    private JTextField usernameField;
    private JPasswordField passwordField;
    private JCheckBox rememberCheckBox;
    private JComboBox<String> roleCombo;
    private JList<String> environmentList;

    private int dynamicItemsAdded;
    private boolean autoNodeAttached;
    private int replaceGeneration;

    public static void main(String[] args) {
        // Deterministic accessible names for JOptionPane's own buttons ("OK", "Yes",
        // "No"), which Swing draws from a Locale-keyed UIManager resource bundle and
        // which this fixture does not otherwise control the creation of.
        Locale.setDefault(Locale.ENGLISH);
        applyLookAndFeel();
        boolean secondWindow = Arrays.asList(args).contains("--second-window")
                || Boolean.getBoolean("fixture.secondWindow");
        SwingUtilities.invokeLater(() -> new SwingFixtureApp().show(secondWindow));
    }

    /**
     * {@code -Dfixture.lookAndFeel=windows} switches to the real Windows L&amp;F
     * instead of Swing's default cross-platform ("Metal") one. Every other launch
     * mode/task in this fixture uses the default deliberately; this is an opt-in
     * scene for a test that needs to prove locator/accessible-name behavior is
     * L&amp;F-independent, not the default for every test run - test-app-review.md
     * finding B4.
     */
    private static void applyLookAndFeel() {
        if (!"windows".equals(System.getProperty("fixture.lookAndFeel"))) {
            return;
        }
        try {
            UIManager.setLookAndFeel("com.sun.java.swing.plaf.windows.WindowsLookAndFeel");
        } catch (ReflectiveOperationException | UnsupportedLookAndFeelException error) {
            System.err.println(
                    "WARNING: could not apply the Windows look and feel: " + error);
        }
    }

    private void show(boolean secondWindow) {
        JFrame frame = new JFrame("JAB swing fixture");
        frame.getAccessibleContext().setAccessibleName("fixture.main");
        frame.setDefaultCloseOperation(WindowConstants.EXIT_ON_CLOSE);
        frame.addWindowListener(new WindowAdapter() {
            @Override
            public void windowClosing(WindowEvent event) {
                stopAutoNodeCycle();
            }

            @Override
            public void windowClosed(WindowEvent event) {
                stopAutoNodeCycle();
            }
        });

        frame.setJMenuBar(buildMenuBar(frame));
        JTabbedPane tabs = buildTabs();
        frame.add(tabs, BorderLayout.CENTER);
        frame.pack();
        frame.setLocationRelativeTo(null);
        frame.setVisible(true);
        // -Dfixture.autoNode=false opts out of fixture.auto_node's 3000ms
        // attach/detach cycle entirely, for tests asserting an exact, stable
        // live-reference count where the timer's own attach/detach traffic would
        // otherwise be an unrelated source of noise (test-app-review.md finding C9).
        if (!"false".equals(System.getProperty("fixture.autoNode"))) {
            startAutoNodeCycle();
        }
        if (secondWindow) {
            showSecondaryWindow(frame);
        }
    }

    /**
     * Menu bar and its two menus: a plain-action menu item (the same shape as any
     * other button, addressed through {@code JMenu}/{@code JPopupMenu} rather than a
     * flat panel) and three {@code JOptionPane} launchers. {@code JMenu}'s dropdown
     * materializes as a real {@code JPopupMenu} only once raised, matching how a real
     * application's menu behaves - it is not present in the tree beforehand.
     */
    private JMenuBar buildMenuBar(JFrame frame) {
        JMenuBar menuBar = new JMenuBar();
        menuBar.getAccessibleContext().setAccessibleName("fixture.menu_bar");

        JMenu fileMenu = new JMenu("File");
        fileMenu.getAccessibleContext().setAccessibleName("fixture.menu_file");

        JMenuItem statusItem = new JMenuItem("Set status");
        statusItem.getAccessibleContext().setAccessibleName("fixture.menu_item_status");
        statusItem.addActionListener(
                e -> setLabelText(statusLabel, "menu action invoked"));

        JMenuItem dialogItem = new JMenuItem("Open dialog...");
        dialogItem.getAccessibleContext().setAccessibleName("fixture.menu_item_open_dialog");
        dialogItem.addActionListener(e -> openMenuDialog(frame));

        fileMenu.add(statusItem);
        fileMenu.add(dialogItem);

        JMenu dialogsMenu = new JMenu("Dialogs");
        dialogsMenu.getAccessibleContext().setAccessibleName("fixture.menu_dialogs");

        JMenuItem messageItem = new JMenuItem("Message...");
        messageItem.getAccessibleContext().setAccessibleName("fixture.menu_item_message_dialog");
        messageItem.addActionListener(e -> showMessageDialog(frame));

        JMenuItem confirmItem = new JMenuItem("Confirm...");
        confirmItem.getAccessibleContext().setAccessibleName("fixture.menu_item_confirm_dialog");
        confirmItem.addActionListener(e -> showConfirmDialog(frame));

        JMenuItem inputItem = new JMenuItem("Input...");
        inputItem.getAccessibleContext().setAccessibleName("fixture.menu_item_input_dialog");
        inputItem.addActionListener(e -> showInputDialog(frame));

        dialogsMenu.add(messageItem);
        dialogsMenu.add(confirmItem);
        dialogsMenu.add(inputItem);

        menuBar.add(fileMenu);
        menuBar.add(dialogsMenu);
        return menuBar;
    }

    /**
     * Application-modal dialog opened from a menu item rather than a button, for
     * {@code click(opens_window=True)} exercised through the menu path. Modal and
     * shown synchronously on the EDT, exactly like {@code fixture.submit_button}
     * would if it opened a dialog - JAB is blocked for as long as it stays open.
     */
    private void openMenuDialog(JFrame owner) {
        JDialog dialog = new JDialog(owner, "Fixture Menu Dialog", true);
        dialog.getAccessibleContext().setAccessibleName("fixture.menu_dialog");

        JLabel content = new JLabel("Opened from menu");
        content.getAccessibleContext().setAccessibleName("fixture.menu_dialog_label");

        JButton close = new JButton("Close");
        close.getAccessibleContext().setAccessibleName("fixture.menu_dialog_close_button");
        close.addActionListener(e -> dialog.dispose());

        JPanel contentPanel = new JPanel();
        contentPanel.add(content);
        contentPanel.add(close);
        dialog.setContentPane(contentPanel);
        dialog.pack();
        dialog.setLocationRelativeTo(owner);
        dialog.setVisible(true);
    }

    /**
     * {@code JOptionPane} launchers. Unlike {@link JabDialogRepro}, these are not a
     * modal-hang regression fixture - they exist so integration tests have at least
     * one scenario built from Swing's own dialog factory rather than a hand-rolled
     * {@code JDialog}, whose content pane and buttons are assembled by the current
     * Look&amp;Feel, not by this fixture. Titles are plain window titles (Win32-level,
     * like every other window in this fixture), not accessible names.
     */
    private void showMessageDialog(JFrame owner) {
        JOptionPane.showMessageDialog(
                owner, "Fixture message", "Fixture Message", JOptionPane.INFORMATION_MESSAGE);
        setLabelText(statusLabel, "message dialog closed");
    }

    private void showConfirmDialog(JFrame owner) {
        int result = JOptionPane.showOptionDialog(
                owner,
                "Confirm the fixture action?",
                "Fixture Confirm",
                JOptionPane.YES_NO_OPTION,
                JOptionPane.QUESTION_MESSAGE,
                null,
                new Object[] {"Yes", "No"},
                "Yes");
        setLabelText(statusLabel, "confirm result=" + (result == JOptionPane.YES_OPTION));
    }

    private void showInputDialog(JFrame owner) {
        Object value = JOptionPane.showInputDialog(
                owner,
                "Enter a value",
                "Fixture Input",
                JOptionPane.PLAIN_MESSAGE,
                null,
                null,
                "");
        setLabelText(statusLabel, "input result=" + value);
    }

    JTabbedPane buildTabs() {
        JTabbedPane tabs = new JTabbedPane();
        tabs.getAccessibleContext().setAccessibleName("fixture.tabs");
        tabs.addTab("Form", buildFormTab());
        tabs.addTab("Table", buildTableTab());
        tabs.addTab("Dynamic", buildDynamicTab());
        tabs.addTab("Locator", buildLocatorTab());
        tabs.addTab("Workloads", buildWorkloadsTab());
        nameTabPage(tabs, 0, "fixture.tab_form_page");
        nameTabPage(tabs, 1, "fixture.tab_table_page");
        nameTabPage(tabs, 2, "fixture.tab_dynamic_page");
        nameTabPage(tabs, 3, "fixture.tab_locator_page");
        nameTabPage(tabs, 4, "fixture.tab_workloads_page");
        return tabs;
    }

    JPanel buildWorkloadsTab() {
        DefaultListModel<String> listModel = new DefaultListModel<>();
        for (int index = 0; index < 1000; index++) {
            listModel.addElement(String.format("fixture.virtual_list_item_%04d", index));
        }
        JList<String> list = new JList<>(listModel);
        list.setVisibleRowCount(8);
        list.getAccessibleContext().setAccessibleName("fixture.virtual_list");
        JScrollPane listScroll = new JScrollPane(list);
        listScroll.getAccessibleContext().setAccessibleName("fixture.virtual_list_scroll");
        listScroll.getVerticalScrollBar().getAccessibleContext()
                .setAccessibleName("fixture.virtual_list_scrollbar_vertical");
        JLabel listStatus = new JLabel();
        listStatus.getAccessibleContext().setAccessibleName("fixture.virtual_list_status");
        Runnable updateListStatus = () -> setLabelText(
                listStatus,
                "first=" + list.getFirstVisibleIndex() + " last=" + list.getLastVisibleIndex());
        list.addListSelectionListener(event -> updateListStatus.run());
        listScroll.getVerticalScrollBar().addAdjustmentListener(event -> updateListStatus.run());
        JPanel listButtons = new JPanel(new FlowLayout(FlowLayout.LEFT));
        listButtons.add(workloadButton("Start", "fixture.virtual_list_start_button", () -> {
            list.ensureIndexIsVisible(0);
            list.setSelectedIndex(0);
            updateListStatus.run();
        }));
        listButtons.add(workloadButton("500", "fixture.virtual_list_500_button", () -> {
            list.ensureIndexIsVisible(500);
            list.setSelectedIndex(500);
            updateListStatus.run();
        }));
        listButtons.add(workloadButton("End", "fixture.virtual_list_end_button", () -> {
            list.ensureIndexIsVisible(999);
            list.setSelectedIndex(999);
            updateListStatus.run();
        }));
        listButtons.add(listStatus);
        JPanel listPanel = new JPanel(new BorderLayout());
        listPanel.add(listScroll, BorderLayout.CENTER);
        listPanel.add(listButtons, BorderLayout.SOUTH);

        DefaultMutableTreeNode root = new DefaultMutableTreeNode("fixture.virtual_tree_root");
        for (int group = 0; group < 40; group++) {
            DefaultMutableTreeNode groupNode = new DefaultMutableTreeNode(
                    String.format("fixture.virtual_tree_group_%02d", group));
            for (int item = 0; item < 5; item++) {
                groupNode.add(new DefaultMutableTreeNode(String.format(
                        "fixture.virtual_tree_group_%02d_item_%02d", group, item)));
            }
            root.add(groupNode);
        }
        JTree tree = new JTree(new DefaultTreeModel(root));
        tree.setVisibleRowCount(8);
        tree.getAccessibleContext().setAccessibleName("fixture.virtual_tree");
        JScrollPane treeScroll = new JScrollPane(tree);
        treeScroll.getAccessibleContext().setAccessibleName("fixture.virtual_tree_scroll");
        JLabel treeStatus = new JLabel();
        treeStatus.getAccessibleContext().setAccessibleName("fixture.virtual_tree_status");
        Runnable updateTreeStatus = () -> setLabelText(treeStatus,
                "expanded=" + expandedRowCount(tree)
                        + " selected=" + tree.getLeadSelectionRow()
                        + " first=" + tree.getClosestRowForLocation(0, 0)
                        + " last=" + tree.getClosestRowForLocation(0, tree.getHeight() - 1));
        JPanel treeButtons = new JPanel(new FlowLayout(FlowLayout.LEFT));
        treeButtons.add(workloadButton("Expand", "fixture.virtual_tree_expand_button", () -> {
            for (int row = 0; row < tree.getRowCount(); row++) {
                tree.expandRow(row);
            }
            updateTreeStatus.run();
        }));
        treeButtons.add(workloadButton("Collapse", "fixture.virtual_tree_collapse_button", () -> {
            for (int row = tree.getRowCount() - 1; row > 0; row--) {
                tree.collapseRow(row);
            }
            updateTreeStatus.run();
        }));
        treeButtons.add(workloadButton("Show end", "fixture.virtual_tree_show_button", () -> {
            int row = tree.getRowCount() - 1;
            tree.setSelectionRow(row);
            tree.scrollRowToVisible(row);
            updateTreeStatus.run();
        }));
        treeButtons.add(workloadButton("Reset", "fixture.virtual_tree_reset_button", () -> {
            tree.clearSelection();
            tree.scrollRowToVisible(0);
            updateTreeStatus.run();
        }));
        treeButtons.add(treeStatus);
        JPanel treePanel = new JPanel(new BorderLayout());
        treePanel.add(treeScroll, BorderLayout.CENTER);
        treePanel.add(treeButtons, BorderLayout.SOUTH);

        JPanel dynamicHost = new JPanel(new FlowLayout(FlowLayout.LEFT));
        dynamicHost.getAccessibleContext().setAccessibleName("fixture.workload_dynamic_host");
        dynamicHost.add(workloadDynamicNode());
        JPanel dynamicButtons = new JPanel(new FlowLayout(FlowLayout.LEFT));
        dynamicButtons.add(workloadButton("Attach", "fixture.workload_attach_button", () -> {
            if (dynamicHost.getComponentCount() == 0) {
                dynamicHost.add(workloadDynamicNode());
                refresh(dynamicHost);
            }
        }));
        dynamicButtons.add(workloadButton("Detach", "fixture.workload_detach_button", () -> {
            dynamicHost.removeAll();
            refresh(dynamicHost);
        }));
        dynamicButtons.add(workloadButton("Show/hide", "fixture.workload_visibility_button", () -> {
            if (dynamicHost.getComponentCount() > 0) {
                Component node = dynamicHost.getComponent(0);
                node.setVisible(!node.isVisible());
                refresh(dynamicHost);
            }
        }));
        dynamicButtons.add(workloadButton("Enable/disable", "fixture.workload_enabled_button", () -> {
            if (dynamicHost.getComponentCount() > 0) {
                Component node = dynamicHost.getComponent(0);
                node.setEnabled(!node.isEnabled());
            }
        }));
        dynamicButtons.add(workloadButton("Replace", "fixture.workload_replace_button", () -> {
            dynamicHost.removeAll();
            dynamicHost.add(workloadDynamicNode());
            refresh(dynamicHost);
        }));
        // Named distinctly from the `dynamicPanel` field below: that one backs the
        // unrelated "Dynamic" tab, and reusing the name here previously shadowed it.
        JPanel workloadDynamicPanel = new JPanel(new BorderLayout());
        workloadDynamicPanel.add(dynamicHost, BorderLayout.CENTER);
        workloadDynamicPanel.add(dynamicButtons, BorderLayout.SOUTH);

        JSplitPane split = new JSplitPane(JSplitPane.HORIZONTAL_SPLIT, listPanel, treePanel);
        split.setResizeWeight(0.5);
        JPanel panel = new JPanel(new BorderLayout(0, 8));
        panel.getAccessibleContext().setAccessibleName("fixture.tab_workloads");
        panel.add(split, BorderLayout.CENTER);
        panel.add(workloadDynamicPanel, BorderLayout.SOUTH);
        updateListStatus.run();
        updateTreeStatus.run();
        return panel;
    }

    private JButton workloadButton(String text, String name, Runnable action) {
        JButton button = new JButton(text);
        button.getAccessibleContext().setAccessibleName(name);
        button.addActionListener(event -> action.run());
        return button;
    }

    private JLabel workloadDynamicNode() {
        replaceGeneration++;
        JLabel node = new JLabel("generation=" + replaceGeneration);
        node.getAccessibleContext().setAccessibleName("fixture.workload_dynamic_node");
        node.getAccessibleContext().setAccessibleDescription(
                "generation=" + replaceGeneration);
        return node;
    }

    private static void refresh(JPanel panel) {
        panel.revalidate();
        panel.repaint();
    }

    private static int expandedRowCount(JTree tree) {
        int expanded = 0;
        for (int row = 0; row < tree.getRowCount(); row++) {
            if (tree.isExpanded(row)) {
                expanded++;
            }
        }
        return expanded;
    }

    /**
     * Дочерние узлы JTabbedPane (role "page tab") сами по себе безымянны и
     * опознаются только по видимой подписи вкладки, что нарушает правило
     * стабильных имён. AccessibleJTabbedPane.Page уважает явно заданное имя.
     */
    private static void nameTabPage(JTabbedPane tabs, int index, String name) {
        tabs.getAccessibleContext()
                .getAccessibleChild(index)
                .getAccessibleContext()
                .setAccessibleName(name);
    }

    JPanel buildFormTab() {
        usernameField = new JTextField(24);
        usernameField.getAccessibleContext().setAccessibleName("fixture.username_field");

        passwordField = new JPasswordField(24);
        passwordField.getAccessibleContext().setAccessibleName("fixture.password_field");

        rememberCheckBox = new JCheckBox("Remember me");
        rememberCheckBox.getAccessibleContext().setAccessibleName("fixture.remember_checkbox");

        roleCombo = new JComboBox<>(new String[] {"Viewer", "Editor", "Admin"});
        roleCombo.setSelectedIndex(0);
        roleCombo.getAccessibleContext().setAccessibleName("fixture.role_combo");

        DefaultListModel<String> environments = new DefaultListModel<>();
        environments.addElement("dev");
        environments.addElement("staging");
        environments.addElement("prod");
        environmentList = new JList<>(environments);
        environmentList.setSelectionMode(ListSelectionModel.SINGLE_SELECTION);
        environmentList.setSelectedIndex(0);
        environmentList.setVisibleRowCount(3);
        environmentList.getAccessibleContext().setAccessibleName("fixture.environment_list");

        JButton submit = new JButton("Sign in");
        submit.getAccessibleContext().setAccessibleName("fixture.submit_button");
        submit.addActionListener(e -> onSubmit());

        statusLabel.getAccessibleContext().setAccessibleName("fixture.status_label");
        setLabelText(statusLabel, "ready");

        JButton disabled = new JButton("Disabled");
        disabled.setEnabled(false);
        disabled.getAccessibleContext().setAccessibleName("fixture.disabled_button");

        JLabel unicodeLabel = new JLabel();
        unicodeLabel.getAccessibleContext().setAccessibleName("fixture.unicode_label");
        // Последний символ (U+1F680) лежит вне BMP и кодируется суррогатной парой
        // UTF-16 — именно этот случай интересен для fixed-size буферов JAB.
        setLabelText(unicodeLabel, "Привет · 日本語 · naïve · ✓ · 🚀");

        JPanel panel = new JPanel(new GridBagLayout());
        panel.getAccessibleContext().setAccessibleName("fixture.tab_form");
        panel.setBorder(BorderFactory.createEmptyBorder(12, 12, 12, 12));

        GridBagConstraints c = new GridBagConstraints();
        c.insets = new Insets(4, 4, 4, 4);
        c.anchor = GridBagConstraints.LINE_START;
        c.fill = GridBagConstraints.HORIZONTAL;

        addFormRow(panel, c, 0, "User name", usernameField);
        addFormRow(panel, c, 1, "Password", passwordField);
        addFormRow(panel, c, 2, "Role", roleCombo);
        addFormRow(panel, c, 3, "Environment", new JScrollPane(environmentList));

        c.gridx = 1;
        c.gridy = 4;
        panel.add(rememberCheckBox, c);
        c.gridy = 5;
        panel.add(submit, c);
        c.gridy = 6;
        panel.add(disabled, c);
        c.gridy = 7;
        panel.add(statusLabel, c);
        c.gridy = 8;
        panel.add(unicodeLabel, c);

        return panel;
    }

    private static void addFormRow(
            JPanel panel, GridBagConstraints c, int row, String labelText, Component field) {
        JLabel label = new JLabel(labelText);
        if (field instanceof JScrollPane scrollPane) {
            label.setLabelFor(scrollPane.getViewport().getView());
        } else {
            label.setLabelFor(field);
        }
        c.gridx = 0;
        c.gridy = row;
        c.weightx = 0;
        panel.add(label, c);
        c.gridx = 1;
        c.weightx = 1;
        panel.add(field, c);
    }

    private void onSubmit() {
        char[] password = passwordField.getPassword();
        int passwordLength = password.length;
        Arrays.fill(password, '\0'); // содержимое password text не попадает ни в UI, ни в логи
        setLabelText(
                statusLabel,
                "signed in: user=" + usernameField.getText()
                        + " role=" + roleCombo.getSelectedItem()
                        + " env=" + environmentList.getSelectedValue()
                        + " remember=" + rememberCheckBox.isSelected()
                        + " password_len=" + passwordLength);
    }

    /**
     * Обычный JLabel не публикует AccessibleText, а его accessible name занят
     * стабильным идентификатором, поэтому содержимое дублируется в description —
     * иначе текст лейбла нечем прочитать через JAB.
     */
    private static void setLabelText(JLabel label, String text) {
        label.setText(text);
        label.getAccessibleContext().setAccessibleDescription(text);
    }

    private static DefaultTableModel buildTableModel() {
        Object[][] rows = new Object[ROW_COUNT][COLUMN_NAMES.length];
        for (int row = 0; row < ROW_COUNT; row++) {
            rows[row][0] = String.valueOf(row);
            rows[row][1] = "job-" + row;
            rows[row][2] = row % 2 == 0 ? "alice" : "bob";
            rows[row][3] = row == MUTABLE_ROW ? "Processing" : "Queued";
            rows[row][4] = row + "%";
        }
        return new DefaultTableModel(rows, COLUMN_NAMES) {
            @Override
            public boolean isCellEditable(int row, int column) {
                // Редактор ячейки подменял бы поддерево доступности на JTextField;
                // значение меняется только через fixture.mark_done_button.
                return false;
            }
        };
    }

    JPanel buildTableTab() {
        table.getAccessibleContext().setAccessibleName("fixture.table");
        table.setSelectionMode(ListSelectionModel.MULTIPLE_INTERVAL_SELECTION);
        table.setAutoResizeMode(JTable.AUTO_RESIZE_ALL_COLUMNS);
        table.setPreferredScrollableViewportSize(
                new Dimension(560, table.getRowHeight() * VISIBLE_ROW_COUNT));

        JScrollPane scrollPane = new JScrollPane(table);
        scrollPane
                .getVerticalScrollBar()
                .getAccessibleContext()
                .setAccessibleName("fixture.table_scrollbar_vertical");

        JButton markDone = new JButton("Mark row 7 done");
        markDone.getAccessibleContext().setAccessibleName("fixture.mark_done_button");
        markDone.addActionListener(e -> tableModel.setValueAt("Done", MUTABLE_ROW, STATUS_COLUMN));

        JButton resetTable = new JButton("Reset row 7");
        resetTable.getAccessibleContext().setAccessibleName("fixture.reset_table_button");
        resetTable.addActionListener(e -> {
            tableModel.setValueAt("Processing", MUTABLE_ROW, STATUS_COLUMN);
            while (tableModel.getRowCount() > ROW_COUNT) {
                tableModel.removeRow(tableModel.getRowCount() - 1);
            }
            repaintTable();
        });

        JButton addExtraRow = new JButton("Add extra row");
        addExtraRow.getAccessibleContext().setAccessibleName("fixture.table_add_row_button");
        addExtraRow.addActionListener(e -> {
            if (tableModel.getRowCount() == ROW_COUNT) {
                tableModel.addRow(new Object[] {"100", "job-100", "alice", "Queued", "100%"});
            }
            repaintTable();
        });

        JButton removeExtraRow = new JButton("Remove extra row");
        removeExtraRow.getAccessibleContext().setAccessibleName("fixture.table_remove_row_button");
        removeExtraRow.addActionListener(e -> {
            if (tableModel.getRowCount() > ROW_COUNT) {
                tableModel.removeRow(tableModel.getRowCount() - 1);
            }
            repaintTable();
        });

        JLabel rowCountStatus = new JLabel();
        rowCountStatus.getAccessibleContext().setAccessibleName("fixture.table_row_count_status");
        tableModel.addTableModelListener(event -> setLabelText(
                rowCountStatus, "rows=" + tableModel.getRowCount()));
        setLabelText(rowCountStatus, "rows=" + tableModel.getRowCount());

        JButton selectRow = new JButton("Select row 7");
        selectRow.getAccessibleContext().setAccessibleName("fixture.select_row_button");
        selectRow.addActionListener(e -> {
            setMixedSelectionMode();
            table.setRowSelectionInterval(MUTABLE_ROW, MUTABLE_ROW);
            table.setColumnSelectionInterval(0, table.getColumnCount() - 1);
        });

        JButton selectColumn = new JButton("Select column 3");
        selectColumn.getAccessibleContext().setAccessibleName("fixture.select_column_button");
        selectColumn.addActionListener(e -> {
            // 100 выделенных строк — сознательно больше MAX_TABLE_SELECTIONS (64).
            setMixedSelectionMode();
            table.setRowSelectionInterval(0, table.getRowCount() - 1);
            table.setColumnSelectionInterval(STATUS_COLUMN, STATUS_COLUMN);
        });

        JButton selectFew = new JButton("Select rows 1, 3, 5");
        selectFew.getAccessibleContext().setAccessibleName("fixture.select_few_button");
        selectFew.addActionListener(e -> {
            // Row-only selection: единственный режим, в котором JTable отдаёт
            // честный AccessibleSelection count (< MAX_TABLE_SELECTIONS) и пустой
            // список выделенных колонок.
            table.clearSelection();
            table.setColumnSelectionAllowed(false);
            table.setRowSelectionAllowed(true);
            table.addRowSelectionInterval(1, 1);
            table.addRowSelectionInterval(3, 3);
            table.addRowSelectionInterval(5, 5);
        });

        JButton clearSelection = new JButton("Clear selection");
        clearSelection.getAccessibleContext().setAccessibleName("fixture.clear_selection_button");
        // Режим выделения намеренно не трогаем: молчаливая смена режима внутри
        // «clear» была бы скрытым побочным эффектом.
        clearSelection.addActionListener(e -> table.clearSelection());

        JPanel buttons = new JPanel(new FlowLayout(FlowLayout.LEFT));
        buttons.add(markDone);
        buttons.add(resetTable);
        buttons.add(selectRow);
        buttons.add(selectColumn);
        buttons.add(selectFew);
        buttons.add(clearSelection);
        buttons.add(addExtraRow);
        buttons.add(removeExtraRow);
        buttons.add(rowCountStatus);

        setMixedSelectionMode();

        JPanel panel = new JPanel(new BorderLayout(0, 8));
        panel.getAccessibleContext().setAccessibleName("fixture.tab_table");
        panel.setBorder(BorderFactory.createEmptyBorder(12, 12, 12, 12));
        panel.add(scrollPane, BorderLayout.NORTH);
        panel.add(buttons, BorderLayout.CENTER);
        panel.add(new SyntheticAccessibleTable(), BorderLayout.SOUTH);
        return panel;
    }

    /**
     * Режим выделения на старте приложения: row и column selection разрешены
     * одновременно. Намеренно <b>не</b> {@code setCellSelectionEnabled(true)} —
     * публичный {@code getCellSelectionEnabled()} вернёт true в обоих случаях
     * (он выведен из двух флагов), но {@code AccessibleJTable} смотрит на
     * приватное поле {@code cellSelectionEnabled}, которое здесь остаётся false.
     * Из-за этого {@code getAccessibleSelectionCount()} возвращает
     * rowCount * columnCount (500) вместо реального числа выделенных ячеек
     * (5 при настоящем cell selection) — count в этом режиме бесполезен.
     */
    private void setMixedSelectionMode() {
        table.setRowSelectionAllowed(true);
        table.setColumnSelectionAllowed(true);
    }

    private void repaintTable() {
        table.revalidate();
        table.repaint();
    }

    JPanel buildDynamicTab() {
        dynamicPanel.setLayout(new BoxLayout(dynamicPanel, BoxLayout.Y_AXIS));
        dynamicPanel.getAccessibleContext().setAccessibleName("fixture.dynamic_panel");
        dynamicPanel.setBorder(BorderFactory.createTitledBorder("Dynamic items"));

        dynamicCountLabel.getAccessibleContext().setAccessibleName("fixture.dynamic_count_label");
        setLabelText(dynamicCountLabel, "items: 0");

        JButton addItem = new JButton("Add item");
        addItem.getAccessibleContext().setAccessibleName("fixture.add_item_button");
        addItem.addActionListener(e -> addDynamicItem());

        JButton removeItem = new JButton("Remove last item");
        removeItem.getAccessibleContext().setAccessibleName("fixture.remove_item_button");
        removeItem.addActionListener(e -> removeLastDynamicItem());

        JPanel buttons = new JPanel(new FlowLayout(FlowLayout.LEFT));
        buttons.add(addItem);
        buttons.add(removeItem);
        buttons.add(dynamicCountLabel);

        JPanel panel = new JPanel(new BorderLayout(0, 8));
        panel.getAccessibleContext().setAccessibleName("fixture.tab_dynamic");
        panel.setBorder(BorderFactory.createEmptyBorder(12, 12, 12, 12));
        panel.add(new JScrollPane(dynamicPanel), BorderLayout.CENTER);
        panel.add(buttons, BorderLayout.SOUTH);
        panel.setPreferredSize(new Dimension(560, 240));
        return panel;
    }

    /**
     * Строит независимые от actions сценарии для strictness, scoped traversal и
     * фильтрации по states. Одинаковые accessible names у duplicate-кнопок
     * намеренны: уникальность появляется только после разрешения контейнера.
     */
    JPanel buildLocatorTab() {
        JPanel alpha = buildDuplicateScope("fixture.scope_alpha", "duplicate in alpha");
        JPanel beta = buildDuplicateScope("fixture.scope_beta", "duplicate in beta");

        JButton visible = new JButton("Visible");
        visible.getAccessibleContext().setAccessibleName("fixture.visible_button");
        visible.getAccessibleContext().setAccessibleDescription("visible and enabled");

        JButton hidden = new JButton("Hidden");
        hidden.getAccessibleContext().setAccessibleName("fixture.hidden_button");
        hidden.getAccessibleContext().setAccessibleDescription("hidden but attached");
        hidden.setVisible(false);

        JButton disabled = new JButton("Locator disabled");
        disabled
                .getAccessibleContext()
                .setAccessibleName("fixture.locator_disabled_button");
        disabled.getAccessibleContext().setAccessibleDescription("visible but disabled");
        disabled.setEnabled(false);

        autoPanel.getAccessibleContext().setAccessibleName("fixture.auto_panel");
        autoNode.getAccessibleContext().setAccessibleName("fixture.auto_node");
        autoNode
                .getAccessibleContext()
                .setAccessibleDescription("Автоматический узел · 日本語 · 🚀");

        JPanel statePanel = new JPanel(new FlowLayout(FlowLayout.LEFT));
        statePanel.getAccessibleContext().setAccessibleName("fixture.state_panel");
        statePanel.add(visible);
        statePanel.add(hidden);
        statePanel.add(disabled);

        JPanel scopes = new JPanel(new FlowLayout(FlowLayout.LEFT));
        scopes.getAccessibleContext().setAccessibleName("fixture.scopes");
        scopes.add(alpha);
        scopes.add(beta);

        JPanel panel = new JPanel();
        panel.setLayout(new BoxLayout(panel, BoxLayout.Y_AXIS));
        panel.getAccessibleContext().setAccessibleName("fixture.tab_locator");
        panel.setBorder(BorderFactory.createEmptyBorder(12, 12, 12, 12));
        panel.add(scopes);
        panel.add(statePanel);
        panel.add(buildValuePanel());
        panel.add(buildTextAndRenderPanel());
        panel.add(buildFocusPanel());
        panel.add(autoPanel);
        panel.setPreferredSize(new Dimension(560, 240));
        return panel;
    }

    /**
     * {@code fixture.boundary_text_field}: {@code CHUNK_SIZE} in
     * {@code backend.py}'s chunked {@code getAccessibleText} reads is
     * {@code min(MAX_STRING_SIZE - 1, 32_766) == 1023} UTF-16 code units. A
     * surrogate pair (two code units, one codepoint) placed so its high
     * surrogate is the very last unit of the first chunk and its low surrogate
     * is the very first unit of the second is the one arrangement most likely
     * to corrupt a naive chunk-and-concatenate implementation - unit tests
     * already prove this against {@code FakeBackend}/{@code StubDll}; this field
     * is what lets an integration test prove it against the real DLL.
     *
     * <p>{@code fixture.custom_rendered_list}: a {@code JList} whose cells are
     * rendered by a custom {@code ListCellRenderer} returning a differently
     * styled {@code JLabel} per row, unlike every other list/table in this
     * fixture which relies on the default renderer - proves accessible text
     * resolution depends on the list model, not the (arbitrary) rendering
     * component subtree the renderer happens to build.
     */
    private static JPanel buildTextAndRenderPanel() {
        JTextField boundaryField = new JTextField(20);
        boundaryField.setText(buildBoundaryStraddlingText());
        boundaryField.setEditable(false);
        boundaryField.getAccessibleContext().setAccessibleName("fixture.boundary_text_field");

        JList<String> customRendered = new JList<>(
                new String[] {"Alpha", "Beta", "Gamma"});
        customRendered.getAccessibleContext().setAccessibleName("fixture.custom_rendered_list");
        customRendered.setCellRenderer((list, value, index, isSelected, hasFocus) -> {
            JLabel label = new JLabel("#" + index + ": " + value);
            label.setOpaque(true);
            label.setBackground(isSelected ? list.getSelectionBackground() : list.getBackground());
            label.setForeground(isSelected ? list.getSelectionForeground() : list.getForeground());
            return label;
        });

        JPanel textAndRender = new JPanel(new FlowLayout(FlowLayout.LEFT));
        textAndRender.getAccessibleContext().setAccessibleName("fixture.text_and_render_panel");
        textAndRender.add(boundaryField);
        textAndRender.add(customRendered);
        return textAndRender;
    }

    private static String buildBoundaryStraddlingText() {
        StringBuilder builder = new StringBuilder();
        for (int i = 0; i < 1022; i++) {
            builder.append('a');
        }
        builder.appendCodePoint(0x1F680); // 🚀 - straddles the 1023-code-unit chunk boundary
        for (int i = 0; i < 978; i++) {
            builder.append('b');
        }
        return builder.toString();
    }

    /**
     * Explicit, deliberately non-declaration-order {@code FocusTraversalPolicy}
     * (C -&gt; A -&gt; B, not A -&gt; B -&gt; C) plus {@code fixture.focus_status}, a
     * label reporting which button currently owns focus - matching how real
     * client UIs often override default tab order, and giving a test a way to
     * prove which component is focused without relying on OS-level "active
     * window" state.
     */
    private static JPanel buildFocusPanel() {
        JButton focusA = new JButton("A");
        focusA.getAccessibleContext().setAccessibleName("fixture.focus_button_a");

        JButton focusB = new JButton("B");
        focusB.getAccessibleContext().setAccessibleName("fixture.focus_button_b");

        JButton focusC = new JButton("C");
        focusC.getAccessibleContext().setAccessibleName("fixture.focus_button_c");

        JLabel focusStatus = new JLabel();
        focusStatus.getAccessibleContext().setAccessibleName("fixture.focus_status");
        setLabelText(focusStatus, "none");

        FocusListener reportFocus = new FocusAdapter() {
            @Override
            public void focusGained(FocusEvent event) {
                Component source = event.getComponent();
                String name = source instanceof Accessible accessible
                        ? accessible.getAccessibleContext().getAccessibleName()
                        : "unknown";
                setLabelText(focusStatus, name);
            }
        };
        focusA.addFocusListener(reportFocus);
        focusB.addFocusListener(reportFocus);
        focusC.addFocusListener(reportFocus);

        JPanel focusPanel = new JPanel(new FlowLayout(FlowLayout.LEFT));
        focusPanel.getAccessibleContext().setAccessibleName("fixture.focus_panel");
        focusPanel.setFocusTraversalPolicyProvider(true);
        focusPanel.setFocusTraversalPolicy(new FocusTraversalPolicy() {
            @Override
            public Component getComponentAfter(Container container, Component component) {
                if (component == focusC) {
                    return focusA;
                }
                if (component == focusA) {
                    return focusB;
                }
                return focusC;
            }

            @Override
            public Component getComponentBefore(Container container, Component component) {
                if (component == focusA) {
                    return focusC;
                }
                if (component == focusB) {
                    return focusA;
                }
                return focusB;
            }

            @Override
            public Component getFirstComponent(Container container) {
                return focusC;
            }

            @Override
            public Component getLastComponent(Container container) {
                return focusB;
            }

            @Override
            public Component getDefaultComponent(Container container) {
                return focusC;
            }
        });
        focusPanel.add(focusA);
        focusPanel.add(focusB);
        focusPanel.add(focusC);
        focusPanel.add(focusStatus);
        return focusPanel;
    }

    /**
     * {@code JScrollBar} (in {@link #buildTableTab()}) is the only current carrier
     * of {@code AccessibleValue} - {@code JProgressBar} and {@code JSlider}
     * implement it too, through their own default {@code AccessibleContext}, with
     * no extra wiring required.
     *
     * <p>{@code JSpinner} was deliberately left out: its JAB-reported role
     * ("spinbox") is not in {@code play_jab.registry}'s role table, and
     * {@code sync_api.py}'s tree walker snapshots every visited node
     * unconditionally - an unrecognized role anywhere in a subtree aborts the
     * *entire* walk with {@code UnsupportedAccessibleRoleError}, not just
     * resolution of that one node. Since a {@code JTabbedPane} keeps every tab's
     * content in the accessible tree regardless of which tab is selected, that
     * would have broken every {@code get_by_name} call from the window root
     * across the whole suite, not merely spinner-focused tests - confirmed
     * empirically before this comment was written. Adding {@code JSpinner} back
     * requires a library-side fix (registering "spinbox" and/or hardening the
     * walker to skip unsupported roles instead of aborting), which is out of this
     * testing-only plan's scope.
     */
    private static JPanel buildValuePanel() {
        JProgressBar progressBar = new JProgressBar(0, 100);
        progressBar.setValue(42);
        progressBar.getAccessibleContext().setAccessibleName("fixture.progress_bar");

        JSlider slider = new JSlider(0, 10, 3);
        slider.getAccessibleContext().setAccessibleName("fixture.slider");

        JPanel valuePanel = new JPanel(new FlowLayout(FlowLayout.LEFT));
        valuePanel.getAccessibleContext().setAccessibleName("fixture.value_panel");
        valuePanel.add(progressBar);
        valuePanel.add(slider);
        return valuePanel;
    }

    private static JPanel buildDuplicateScope(String name, String description) {
        JPanel scope = new JPanel(new FlowLayout(FlowLayout.LEFT));
        scope.getAccessibleContext().setAccessibleName(name);
        JButton duplicate = new JButton("Duplicate");
        duplicate.getAccessibleContext().setAccessibleName("fixture.duplicate");
        duplicate.getAccessibleContext().setAccessibleDescription(description);
        scope.add(duplicate);
        return scope;
    }

    /**
     * Переключает физическое присутствие auto-node, а не только его visibility.
     * Повторяющийся цикл исключает гонку между запуском JVM и attach теста.
     */
    void startAutoNodeCycle() {
        stopAutoNodeCycle();
        // Keep a wide detached observation window: the workloads tab adds
        // virtualized trees whose native traversal can take longer than a
        // single short Swing timer interval on slower JAB installations.
        autoNodeTimer = new Timer(3000, event -> {
            if (autoNodeAttached) {
                autoPanel.remove(autoNode);
            } else {
                autoPanel.add(autoNode);
            }
            autoNodeAttached = !autoNodeAttached;
            autoPanel.revalidate();
            autoPanel.repaint();
        });
        autoNodeTimer.setInitialDelay(1000);
        autoNodeTimer.start();
    }

    void stopAutoNodeCycle() {
        if (autoNodeTimer != null) {
            autoNodeTimer.stop();
            autoNodeTimer = null;
        }
    }

    boolean isAutoNodeCycleRunning() {
        return autoNodeTimer != null && autoNodeTimer.isRunning();
    }

    /** Создаёт второе Java-окно того же PID для проверки strict window discovery. */
    private static void showSecondaryWindow(JFrame ownerForPlacement) {
        JFrame secondary = new JFrame("JAB swing fixture secondary");
        secondary.getAccessibleContext().setAccessibleName("fixture.secondary");
        secondary
                .getAccessibleContext()
                .setAccessibleDescription("optional strict-window fixture");
        secondary.setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);
        JLabel content = new JLabel("Secondary window");
        content.getAccessibleContext().setAccessibleName("fixture.secondary_label");
        content
                .getAccessibleContext()
                .setAccessibleDescription("secondary top-level window");
        secondary.add(content);
        secondary.pack();
        secondary.setLocation(
                ownerForPlacement.getX() + 40,
                ownerForPlacement.getY() + 40);
        secondary.setVisible(true);
    }

    private void addDynamicItem() {
        dynamicItemsAdded++;
        JLabel item = new JLabel();
        item.getAccessibleContext().setAccessibleName("fixture.dynamic_item_" + dynamicItemsAdded);
        setLabelText(item, "Item " + dynamicItemsAdded);
        item.setAlignmentX(Component.LEFT_ALIGNMENT);
        dynamicPanel.add(item);
        refreshDynamicPanel();
    }

    private void removeLastDynamicItem() {
        int count = dynamicPanel.getComponentCount();
        if (count == 0) {
            return;
        }
        // Номера не переиспользуются: удалённое имя остаётся уникальным
        // для проверки stale nodes.
        dynamicPanel.remove(count - 1);
        refreshDynamicPanel();
    }

    private void refreshDynamicPanel() {
        setLabelText(dynamicCountLabel, "items: " + dynamicPanel.getComponentCount());
        dynamicPanel.revalidate();
        dynamicPanel.repaint();
    }
}

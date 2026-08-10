import java.awt.BorderLayout;
import java.awt.Dialog;
import java.awt.FlowLayout;
import java.awt.SecondaryLoop;
import java.awt.Toolkit;
import java.awt.Window;
import java.awt.event.WindowAdapter;
import java.awt.event.WindowEvent;
import java.lang.reflect.InvocationTargetException;
import javax.swing.BorderFactory;
import javax.swing.JButton;
import javax.swing.JDialog;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JTextField;
import javax.swing.SwingUtilities;
import javax.swing.WindowConstants;

/**
 * Regression fixture: Java Access Bridge временно теряет доступ к окнам, пока
 * открыт {@link JDialog} из синхронного JAB action dispatch. Нативный
 * {@code doAccessibleActions} может оставаться заблокированным до закрытия
 * диалога, поэтому сериализованный JAB worker в это время недоступен.
 * Никаких внешних зависимостей — чистый AWT/Swing.
 *
 * <p>Поведение исходных A/B/C портировано из {@code .todo/jdialog_bug/java-app}.
 * Accessible-имена, заголовки окон и набор сценариев (A/B/C, вложенный и
 * {@code -Ddialog.first=true}) являются контрактом интеграционных тестов и не
 * должны меняться. Общая fixture живёт отдельно в {@link SwingFixtureApp}.
 *
 * Accessible-имена (стабильные, не зависят от локали):
 *   repro.main                            — главное окно
 *   repro.open_modeless                   — кнопка «открыть Сценарий A»
 *   repro.open_modal                      — кнопка «открыть Сценарий B»
 *   repro.open_invokeandwait              — кнопка «открыть Сценарий C»
 *   repro.status                         — opening/opened/closed/error channel
 *   repro.modeless.dialog / .input / .ok  — диалог Сценария A и его поля
 *   repro.modal.dialog / .input / .ok     — диалог Сценария B и его поля
 *   repro.invokeandwait.dialog / .input / .ok — диалог Сценария C и его поля
 *   repro.invokeandwait.open_nested       — кнопка вложенного модального сценария
 *   repro.nested.dialog / .input / .ok    — вложенный диалог из Сценария C
 *   repro.first.dialog / .input / .ok     — диалог, показанный первым окном
 *                                            процесса (см. -Ddialog.first=true)
 *
 * Заголовки окон (для закрытия через Win32 WM_CLOSE, когда JAB недоступен):
 *   "JAB dialog repro" — главное окно
 *   "Scenario A"        — диалог Сценария A
 *   "Scenario B"         — диалог Сценария B
 *   "Scenario C"         — диалог Сценария C
 *   "Scenario Nested"    — вложенный диалог, открытый из Сценария C
 *   "Scenario First"     — диалог "первое окно процесса"
 */
public final class JabDialogRepro {

    // Window titles (for closing through Win32 WM_CLOSE when JAB is unavailable) -
    // the exact contract test_modal_dialogs.py's raw-window helpers depend on.
    // Package-private so SwingFixtureContractTest can assert against them
    // directly instead of duplicating the literals (unit-tests-review.md /
    // test-app-review.md finding B12).
    static final String MAIN_TITLE = "JAB dialog repro";
    static final String SCENARIO_A_TITLE = "Scenario A";
    static final String SCENARIO_B_TITLE = "Scenario B";
    static final String SCENARIO_C_TITLE = "Scenario C";
    static final String SCENARIO_NESTED_TITLE = "Scenario Nested";
    static final String SCENARIO_FIRST_TITLE = "Scenario First";

    public static void main(String[] args) {
        boolean dialogFirst = Boolean.getBoolean("dialog.first");
        SwingUtilities.invokeLater(() -> {
            if (dialogFirst) {
                // Диалог — самое первое top-level окно процесса, до
                // JAB-опроса чего-либо ещё. Отдельная диагностика, не доказательство
                // причины регрессии A/B.
                showModalDialog(null, SCENARIO_FIRST_TITLE, "first");
                return;
            }
            showMainFrame();
        });
    }

    private static void showMainFrame() {
        JFrame frame = new JFrame(MAIN_TITLE);
        frame.getAccessibleContext().setAccessibleName("repro.main");
        frame.setDefaultCloseOperation(WindowConstants.EXIT_ON_CLOSE);

        JButton openModeless = new JButton("Open Scenario A (modeless+SecondaryLoop)");
        openModeless.getAccessibleContext().setAccessibleName("repro.open_modeless");

        JButton openModal = new JButton("Open Scenario B (application-modal)");
        openModal.getAccessibleContext().setAccessibleName("repro.open_modal");

        JButton openInvokeAndWait = new JButton("Open Scenario C (invokeAndWait off-EDT)");
        openInvokeAndWait.getAccessibleContext().setAccessibleName("repro.open_invokeandwait");

        JLabel status = createStatusLabel();
        openModeless.addActionListener(e -> showModelessDialog(frame, status));
        openModal.addActionListener(
                e -> showModalDialog(frame, SCENARIO_B_TITLE, "modal", false, status));
        openInvokeAndWait.addActionListener(
                e -> showModalDialogViaInvokeAndWait(frame, status));

        JPanel content = new JPanel(new FlowLayout());
        content.add(openModeless);
        content.add(openModal);
        content.add(openInvokeAndWait);

        frame.add(content, BorderLayout.CENTER);
        frame.add(status, BorderLayout.SOUTH);
        frame.setSize(560, 160);
        frame.setLocationRelativeTo(null);
        frame.setVisible(true);
    }

    /**
     * Сценарий A: MODELESS + ожидание через {@link SecondaryLoop}.
     *
     * <p>{@code SecondaryLoop.enter()} не останавливает EDT: вложенный цикл
     * продолжает обрабатывать события. Существенно то, что вызванный через JAB
     * listener не завершается до закрытия диалога.
     */
    private static void showModelessDialog(JFrame parent, JLabel status) {
        setStatus(status, "opening: Scenario A");
        // `parent` is passed directly, not through `SwingUtilities.getWindowAncestor`:
        // that call walks up from `parent.getParent()`, which is null for a top-level
        // JFrame, so it silently returned null - the dialog ended up owned by AWT's
        // hidden shared-owner frame instead of `repro.main`, breaking the "owner
        // window also loses JAB access" contract this fixture exists to prove.
        JDialog dialog = new JDialog(parent, SCENARIO_A_TITLE, Dialog.ModalityType.MODELESS);
        dialog.getAccessibleContext().setAccessibleName("repro.modeless.dialog");
        dialog.setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);
        buildDialogContent(dialog, "repro.modeless");

        SecondaryLoop loop = Toolkit.getDefaultToolkit().getSystemEventQueue().createSecondaryLoop();
        dialog.addWindowListener(new WindowAdapter() {
            @Override
            public void windowClosed(WindowEvent e) {
                setStatus(status, "closed: Scenario A");
                loop.exit();
            }

            @Override
            public void windowOpened(WindowEvent e) {
                setStatus(status, "opened: Scenario A");
            }
        });
        dialog.setVisible(true); // вызвано уже внутри ActionListener (на EDT) — вложенный показ
        boolean entered = loop.enter(); // блокирует до закрытия окна
        if (!entered) {
            // enter() returns false without blocking if the loop could not start
            // (for example a nested loop is already active). Silently proceeding
            // would defeat this fixture's entire purpose: it would return instead
            // of reproducing the hang it exists to demonstrate.
            setStatus(status, "error: SecondaryLoop.enter() returned false");
        }
    }

    /**
     * Сценарий B (и диагностический режим "первое окно" при owner == null):
     * настоящая AWT-модальность.
     *
     * @param owner        владелец диалога (null — диалог первым окном процесса)
     * @param title        заголовок окна (используется для поиска через win32gui.FindWindow)
     * @param namePrefix   префикс accessible-имён (repro.<namePrefix>.*)
     */
    private static void showModalDialog(Window owner, String title, String namePrefix) {
        showModalDialog(owner, title, namePrefix, false, null);
    }

    private static void showModalDialog(
            Window owner,
            String title,
            String namePrefix,
            boolean includeNestedButton,
            JLabel status) {
        setStatus(status, "opening: " + title);
        JDialog dialog = new JDialog(owner, title, Dialog.ModalityType.APPLICATION_MODAL);
        dialog.getAccessibleContext().setAccessibleName("repro." + namePrefix + ".dialog");
        dialog.setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);
        dialog.addWindowListener(new WindowAdapter() {
            @Override
            public void windowOpened(WindowEvent event) {
                setStatus(status, "opened: " + title);
            }

            @Override
            public void windowClosed(WindowEvent event) {
                setStatus(status, "closed: " + title);
            }
        });
        buildDialogContent(dialog, "repro." + namePrefix, includeNestedButton, status);
        dialog.setVisible(true); // штатная модальная блокировка AWT
        if (owner == null) {
            System.exit(0); // единственное окно процесса — после закрытия выходим
        }
    }

    /**
     * Сценарий C: тот же APPLICATION_MODAL показ, что и Сценарий B, но
     * {@code dialog.setVisible(true)} вызывается через
     * {@code SwingUtilities.invokeAndWait(...)} с обычного (не-EDT) потока.
     * Исходный ActionListener на EDT быстро возвращается, поэтому инициированный
     * JAB dispatch завершается, а открытый диалог остаётся доступен через JAB.
     * Кнопка {@code repro.invokeandwait.open_nested} внутри C снова открывает
     * APPLICATION_MODAL синхронно из собственного listener и воспроизводит
     * проблему уже для вложенного диалога.
     */
    private static void showModalDialogViaInvokeAndWait(JFrame parent, JLabel status) {
        Thread invoker = new Thread(() -> {
            try {
                SwingUtilities.invokeAndWait(
                        () -> showModalDialog(
                                parent, SCENARIO_C_TITLE, "invokeandwait", true, status));
            } catch (InterruptedException | InvocationTargetException e) {
                if (e instanceof InterruptedException) {
                    Thread.currentThread().interrupt();
                }
                SwingUtilities.invokeLater(
                        () -> setStatus(status, "error: " + e.getClass().getSimpleName()));
            }
        }, "scenario-c-invoker");
        invoker.setDaemon(true);
        invoker.start();
    }

    private static void buildDialogContent(JDialog dialog, String namePrefix) {
        buildDialogContent(dialog, namePrefix, false, null);
    }

    private static void buildDialogContent(
            JDialog dialog,
            String namePrefix,
            boolean includeNestedButton,
            JLabel status) {
        JTextField input = new JTextField(30);
        input.getAccessibleContext().setAccessibleName(namePrefix + ".input");

        JButton ok = new JButton("OK");
        ok.getAccessibleContext().setAccessibleName(namePrefix + ".ok");
        ok.addActionListener(e -> dialog.dispose());

        JPanel buttons = new JPanel(new FlowLayout(FlowLayout.RIGHT));
        if (includeNestedButton) {
            JButton openNested = new JButton("Open nested modal");
            openNested
                    .getAccessibleContext()
                    .setAccessibleName("repro.invokeandwait.open_nested");
            openNested.addActionListener(
                    e -> showModalDialog(
                            dialog, SCENARIO_NESTED_TITLE, "nested", false, status));
            buttons.add(openNested);
        }
        buttons.add(ok);

        JPanel content = new JPanel(new BorderLayout(0, 12));
        content.setBorder(BorderFactory.createEmptyBorder(12, 12, 12, 12));
        content.add(input, BorderLayout.CENTER);
        content.add(buttons, BorderLayout.SOUTH);

        dialog.setContentPane(content);
        dialog.pack();
        dialog.setLocationRelativeTo(dialog.getOwner());
    }

    static JLabel createStatusLabel() {
        JLabel status = new JLabel();
        status.getAccessibleContext().setAccessibleName("repro.status");
        setStatus(status, "ready");
        return status;
    }

    static void setStatus(JLabel status, String value) {
        if (status == null) {
            return;
        }
        status.setText(value);
        status.getAccessibleContext().setAccessibleDescription(value);
    }
}

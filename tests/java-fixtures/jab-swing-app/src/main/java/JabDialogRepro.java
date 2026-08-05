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
import javax.swing.JPanel;
import javax.swing.JTextField;
import javax.swing.SwingUtilities;
import javax.swing.WindowConstants;

/**
 * Regression fixture: Java Access Bridge теряет доступ к окнам, пока открыт
 * JDialog, показанный поверх уже видимого и уже опрошенного через JAB главного
 * окна. Никаких внешних зависимостей — чистый AWT/Swing.
 *
 * <p>Портировано без изменений поведения из {@code .todo/jdialog_bug/java-app}.
 * Accessible-имена, заголовки окон и набор сценариев (A/B/C и
 * {@code -Ddialog.first=true}) являются контрактом интеграционных тестов и не
 * должны меняться. Общая fixture живёт отдельно в {@link SwingFixtureApp}.
 *
 * Accessible-имена (стабильные, не зависят от локали):
 *   repro.main                            — главное окно
 *   repro.open_modeless                   — кнопка «открыть Сценарий A»
 *   repro.open_modal                      — кнопка «открыть Сценарий B»
 *   repro.open_invokeandwait              — кнопка «открыть Сценарий C»
 *   repro.modeless.dialog / .input / .ok  — диалог Сценария A и его поля
 *   repro.modal.dialog / .input / .ok     — диалог Сценария B и его поля
 *   repro.invokeandwait.dialog / .input / .ok — диалог Сценария C и его поля
 *   repro.first.dialog / .input / .ok     — диалог, показанный первым окном
 *                                            процесса (см. -Ddialog.first=true)
 *
 * Заголовки окон (для закрытия через Win32 WM_CLOSE, когда JAB недоступен):
 *   "JAB dialog repro" — главное окно
 *   "Scenario A"        — диалог Сценария A
 *   "Scenario B"         — диалог Сценария B
 *   "Scenario C"         — диалог Сценария C
 *   "Scenario First"     — диалог "первое окно процесса"
 */
public final class JabDialogRepro {

    public static void main(String[] args) {
        boolean dialogFirst = Boolean.getBoolean("dialog.first");
        SwingUtilities.invokeLater(() -> {
            if (dialogFirst) {
                // Диалог — самое первое top-level окно процесса, до
                // JAB-опроса чего-либо ещё. Проверка гипотезы "первое окно".
                showModalDialog(null, "Scenario First", "first");
                return;
            }
            showMainFrame();
        });
    }

    private static void showMainFrame() {
        JFrame frame = new JFrame("JAB dialog repro");
        frame.getAccessibleContext().setAccessibleName("repro.main");
        frame.setDefaultCloseOperation(WindowConstants.EXIT_ON_CLOSE);

        JButton openModeless = new JButton("Open Scenario A (modeless+SecondaryLoop)");
        openModeless.getAccessibleContext().setAccessibleName("repro.open_modeless");
        openModeless.addActionListener(e -> showModelessDialog(frame));

        JButton openModal = new JButton("Open Scenario B (application-modal)");
        openModal.getAccessibleContext().setAccessibleName("repro.open_modal");
        openModal.addActionListener(e -> showModalDialog(frame, "Scenario B", "modal"));

        JButton openInvokeAndWait = new JButton("Open Scenario C (invokeAndWait off-EDT)");
        openInvokeAndWait.getAccessibleContext().setAccessibleName("repro.open_invokeandwait");
        openInvokeAndWait.addActionListener(e -> showModalDialogViaInvokeAndWait(frame));

        JPanel content = new JPanel(new FlowLayout());
        content.add(openModeless);
        content.add(openModal);
        content.add(openInvokeAndWait);

        frame.add(content, BorderLayout.CENTER);
        frame.setSize(560, 160);
        frame.setLocationRelativeTo(null);
        frame.setVisible(true);
    }

    /** Сценарий A: MODELESS + ручная блокировка через SecondaryLoop. */
    private static void showModelessDialog(JFrame parent) {
        Window owner = SwingUtilities.getWindowAncestor(parent);
        JDialog dialog = new JDialog(owner, "Scenario A", Dialog.ModalityType.MODELESS);
        dialog.getAccessibleContext().setAccessibleName("repro.modeless.dialog");
        dialog.setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);
        buildDialogContent(dialog, "repro.modeless");

        SecondaryLoop loop = Toolkit.getDefaultToolkit().getSystemEventQueue().createSecondaryLoop();
        dialog.addWindowListener(new WindowAdapter() {
            @Override
            public void windowClosed(WindowEvent e) {
                loop.exit();
            }
        });
        dialog.setVisible(true); // вызвано уже внутри ActionListener (на EDT) — вложенный показ
        loop.enter();            // блокирует до закрытия окна
    }

    /**
     * Сценарий B (и режим "первое окно" при parent == null): настоящая AWT-модальность.
     *
     * @param parent       владелец диалога (null — диалог первым окном процесса)
     * @param title        заголовок окна (используется для поиска через win32gui.FindWindow)
     * @param namePrefix   префикс accessible-имён (repro.<namePrefix>.*)
     */
    private static void showModalDialog(JFrame parent, String title, String namePrefix) {
        Window owner = parent == null ? null : SwingUtilities.getWindowAncestor(parent);
        JDialog dialog = new JDialog(owner, title, Dialog.ModalityType.APPLICATION_MODAL);
        dialog.getAccessibleContext().setAccessibleName("repro." + namePrefix + ".dialog");
        dialog.setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);
        buildDialogContent(dialog, "repro." + namePrefix);
        dialog.setVisible(true); // штатная модальная блокировка AWT
        if (parent == null) {
            System.exit(0); // единственное окно процесса — после закрытия выходим
        }
    }

    /**
     * Сценарий C: тот же APPLICATION_MODAL показ, что и Сценарий B, но dialog.setVisible(true)
     * вызывается через SwingUtilities.invokeAndWait(...) с обычного (не-EDT) потока, а не
     * напрямую внутри ActionListener. ActionListener на EDT возвращается немедленно, не дожидаясь
     * закрытия диалога -- проверка гипотезы H2 (INVESTIGATION.md): зависит ли поломка JAB от того,
     * что модальный показ стартует рекурсивно внутри уже выполняющегося actionPerformed(), а не
     * как "свежая" верхнеуровневая итерация EDT.
     */
    private static void showModalDialogViaInvokeAndWait(JFrame parent) {
        Thread invoker = new Thread(() -> {
            try {
                SwingUtilities.invokeAndWait(
                        () -> showModalDialog(parent, "Scenario C", "invokeandwait"));
            } catch (InterruptedException | InvocationTargetException e) {
                throw new RuntimeException(e);
            }
        }, "scenario-c-invoker");
        invoker.setDaemon(true);
        invoker.start();
    }

    private static void buildDialogContent(JDialog dialog, String namePrefix) {
        JTextField input = new JTextField(30);
        input.getAccessibleContext().setAccessibleName(namePrefix + ".input");

        JButton ok = new JButton("OK");
        ok.getAccessibleContext().setAccessibleName(namePrefix + ".ok");
        ok.addActionListener(e -> dialog.dispose());

        JPanel buttons = new JPanel(new FlowLayout(FlowLayout.RIGHT));
        buttons.add(ok);

        JPanel content = new JPanel(new BorderLayout(0, 12));
        content.setBorder(BorderFactory.createEmptyBorder(12, 12, 12, 12));
        content.add(input, BorderLayout.CENTER);
        content.add(buttons, BorderLayout.SOUTH);

        dialog.setContentPane(content);
        dialog.pack();
        dialog.setLocationRelativeTo(dialog.getOwner());
    }
}

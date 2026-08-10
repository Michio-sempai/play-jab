import java.awt.BorderLayout;
import javax.swing.JButton;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.SwingUtilities;
import javax.swing.Timer;
import javax.swing.WindowConstants;

/**
 * Function-scoped fixture that exits its JVM after publishing shutdown state.
 *
 * <p>Shutdown is triggered explicitly by {@code fixture.shutdown_button}, not by a
 * free-running timer: a test that waits for a locator to observe the JVM exiting
 * must control exactly when that happens, or the test becomes a race between its
 * own polling and the timer - see integration-tests-review.md finding B-1, where
 * the previous unconditional 1500&nbsp;ms timer made
 * {@code test_graceful_jvm_exit_wakes_locator_wait} flaky.
 *
 * <p>The actual {@code System.exit(0)} still runs on a short, fixed
 * {@link #SHUTDOWN_DELAY_MS} timer started by the button's {@code ActionListener},
 * rather than inline in the listener itself: exiting synchronously inside the same
 * EDT dispatch that the JAB native call is waiting on would tear the JVM down
 * mid-call, which is a different (and untested) failure shape than a clean exit
 * observed after the call has already returned. The delay is short and bounded, so
 * it stays deterministic from the test's point of view - it starts counting only
 * once the test's own click has been acknowledged.
 */
public final class LifecycleFixtureApp {

    private static final int SHUTDOWN_DELAY_MS = 200;

    private LifecycleFixtureApp() {
    }

    public static void main(String[] args) {
        SwingUtilities.invokeLater(LifecycleFixtureApp::show);
    }

    private static void show() {
        JFrame frame = new JFrame("JAB lifecycle fixture");
        frame.getAccessibleContext().setAccessibleName("fixture.lifecycle_main");
        frame.setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);

        JLabel status = createStatusLabel();

        JButton shutdownButton = new JButton("Shut down");
        shutdownButton.getAccessibleContext().setAccessibleName("fixture.shutdown_button");
        shutdownButton.addActionListener(event -> scheduleShutdown(frame, status));

        JPanel content = new JPanel(new BorderLayout());
        content.add(status, BorderLayout.CENTER);
        content.add(shutdownButton, BorderLayout.SOUTH);
        frame.add(content);
        frame.pack();
        frame.setLocationRelativeTo(null);
        frame.setVisible(true);
    }

    // Package-private and Window-free so SwingFixtureContractTest can cover the
    // running -> shutting-down text/description transition without constructing a
    // real JFrame (headless-unsafe) or triggering the real Timer/System.exit(0)
    // that `scheduleShutdown` schedules alongside it.
    static JLabel createStatusLabel() {
        JLabel status = new JLabel("running");
        status.getAccessibleContext().setAccessibleName("fixture.shutdown_status");
        status.getAccessibleContext().setAccessibleDescription("running");
        return status;
    }

    static void markShuttingDown(JLabel status) {
        status.setText("shutting-down");
        status.getAccessibleContext().setAccessibleDescription("shutting-down");
    }

    private static void scheduleShutdown(JFrame frame, JLabel status) {
        markShuttingDown(status);
        Timer timer = new Timer(SHUTDOWN_DELAY_MS, event -> {
            frame.dispose();
            System.exit(0);
        });
        timer.setRepeats(false);
        timer.start();
    }
}

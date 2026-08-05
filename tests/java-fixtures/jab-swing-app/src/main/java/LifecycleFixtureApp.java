import java.awt.BorderLayout;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.SwingUtilities;
import javax.swing.Timer;
import javax.swing.WindowConstants;

/** Function-scoped fixture that exits its JVM after publishing shutdown state. */
public final class LifecycleFixtureApp {

    private LifecycleFixtureApp() {
    }

    public static void main(String[] args) {
        SwingUtilities.invokeLater(LifecycleFixtureApp::show);
    }

    private static void show() {
        JFrame frame = new JFrame("JAB lifecycle fixture");
        frame.getAccessibleContext().setAccessibleName("fixture.lifecycle_main");
        frame.setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);
        JLabel status = new JLabel("running");
        status.getAccessibleContext().setAccessibleName("fixture.shutdown_status");
        status.getAccessibleContext().setAccessibleDescription("running");
        frame.add(status, BorderLayout.CENTER);
        frame.pack();
        frame.setLocationRelativeTo(null);
        frame.setVisible(true);

        Timer timer = new Timer(1500, event -> {
            status.setText("shutting-down");
            status.getAccessibleContext().setAccessibleDescription("shutting-down");
            frame.dispose();
            System.exit(0);
        });
        timer.setRepeats(false);
        timer.start();
    }
}

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.awt.Component;
import java.awt.Container;
import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Callable;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import javax.accessibility.Accessible;
import javax.accessibility.AccessibleContext;
import javax.accessibility.AccessibleRole;
import javax.accessibility.AccessibleTable;
import javax.swing.JButton;
import javax.swing.JCheckBox;
import javax.swing.JComboBox;
import javax.swing.JLabel;
import javax.swing.JList;
import javax.swing.JPanel;
import javax.swing.JPasswordField;
import javax.swing.JTabbedPane;
import javax.swing.JTable;
import javax.swing.JTextField;
import javax.swing.JTree;
import javax.swing.SwingUtilities;
import org.junit.jupiter.api.Test;

/** In-process contracts for metadata and deterministic Swing state used by real-JAB tests. */
final class SwingFixtureContractTest {

    @Test
    void tabMetadataAndInitialSelectionAreStable() throws Exception {
        onEdt(() -> {
            JTabbedPane tabs = new SwingFixtureApp().buildTabs();

            assertEquals("fixture.tabs", accessibleName(tabs));
            assertEquals(5, tabs.getTabCount());
            assertEquals(0, tabs.getSelectedIndex());
            assertEquals("Form", tabs.getTitleAt(0));
            assertEquals("Table", tabs.getTitleAt(1));
            assertEquals("Dynamic", tabs.getTitleAt(2));
            assertEquals("Locator", tabs.getTitleAt(3));
            assertEquals("Workloads", tabs.getTitleAt(4));
            assertEquals(
                    "fixture.tab_form_page",
                    tabs.getAccessibleContext()
                            .getAccessibleChild(0)
                            .getAccessibleContext()
                            .getAccessibleName());
            assertEquals(
                    "fixture.tab_table_page",
                    tabs.getAccessibleContext()
                            .getAccessibleChild(1)
                            .getAccessibleContext()
                            .getAccessibleName());
            assertEquals(
                    "fixture.tab_dynamic_page",
                    tabs.getAccessibleContext()
                            .getAccessibleChild(2)
                            .getAccessibleContext()
                            .getAccessibleName());
            assertEquals(
                    "fixture.tab_locator_page",
                    tabs.getAccessibleContext()
                            .getAccessibleChild(3)
                            .getAccessibleContext()
                            .getAccessibleName());
            assertEquals(
                    "fixture.tab_workloads_page",
                    tabs.getAccessibleContext()
                            .getAccessibleChild(4)
                            .getAccessibleContext()
                            .getAccessibleName());
            return null;
        });
    }

    @Test
    void workloadModelsAndDeterministicControlsAreStable() throws Exception {
        onEdt(() -> {
            JPanel workloads = new SwingFixtureApp().buildWorkloadsTab();
            JList<?> list = find(workloads, "fixture.virtual_list", JList.class);
            JTree tree = find(workloads, "fixture.virtual_tree", JTree.class);
            assertEquals(1000, list.getModel().getSize());
            assertEquals("fixture.virtual_list_item_0000", list.getModel().getElementAt(0));
            assertEquals("fixture.virtual_list_item_0999", list.getModel().getElementAt(999));
            assertEquals(40, ((javax.swing.tree.TreeNode) tree.getModel().getRoot()).getChildCount());

            JPanel host = find(workloads, "fixture.workload_dynamic_host", JPanel.class);
            assertEquals(1, host.getComponentCount());
            assertEquals("generation=1", accessibleDescription(host.getComponent(0)));
            find(workloads, "fixture.workload_replace_button", JButton.class).doClick();
            assertEquals("generation=2", accessibleDescription(host.getComponent(0)));
            find(workloads, "fixture.workload_detach_button", JButton.class).doClick();
            assertEquals(0, host.getComponentCount());
            find(workloads, "fixture.workload_attach_button", JButton.class).doClick();
            assertEquals(1, host.getComponentCount());
            return null;
        });
    }

    @Test
    void formMetadataAndSubmitResultAreStable() throws Exception {
        onEdt(() -> {
            SwingFixtureApp app = new SwingFixtureApp();
            JPanel form = app.buildFormTab();

            assertEquals("fixture.tab_form", accessibleName(form));
            JTextField username = find(form, "fixture.username_field", JTextField.class);
            JPasswordField password =
                    find(form, "fixture.password_field", JPasswordField.class);
            JCheckBox remember =
                    find(form, "fixture.remember_checkbox", JCheckBox.class);
            JComboBox<?> role = find(form, "fixture.role_combo", JComboBox.class);
            JList<?> environment = find(form, "fixture.environment_list", JList.class);
            JLabel status = find(form, "fixture.status_label", JLabel.class);
            JLabel unicode = find(form, "fixture.unicode_label", JLabel.class);

            assertEquals("", username.getText());
            assertEquals(0, password.getPassword().length);
            assertFalse(remember.isSelected());
            assertEquals("Viewer", role.getSelectedItem());
            assertEquals("dev", environment.getSelectedValue());
            assertEquals("ready", accessibleDescription(status));
            assertEquals("Привет · 日本語 · naïve · ✓ · 🚀", accessibleDescription(unicode));

            username.setText("Иван 🚀");
            password.setText("never-log-this");
            remember.setSelected(true);
            role.setSelectedIndex(2);
            environment.setSelectedIndex(2);
            find(form, "fixture.submit_button", JButton.class).doClick();

            String result = accessibleDescription(status);
            assertEquals(
                    "signed in: user=Иван 🚀 role=Admin env=prod remember=true password_len=14",
                    result);
            assertFalse(result.contains("never-log-this"));
            username.setText("");
            password.setText("");
            assertEquals("", username.getText());
            assertEquals(0, password.getPassword().length);
            return null;
        });
    }

    @Test
    void realisticTableDimensionsMutationAndSelectionAreStable() throws Exception {
        onEdt(() -> {
            SwingFixtureApp app = new SwingFixtureApp();
            JPanel tab = app.buildTableTab();
            JTable table = find(tab, "fixture.table", JTable.class);
            AccessibleTable accessibleTable = table.getAccessibleContext().getAccessibleTable();

            assertEquals(100, accessibleTable.getAccessibleRowCount());
            assertEquals(5, accessibleTable.getAccessibleColumnCount());
            assertEquals(10, SwingFixtureApp.VISIBLE_ROW_COUNT);
            assertEquals(
                    table.getRowHeight() * SwingFixtureApp.VISIBLE_ROW_COUNT,
                    table.getPreferredScrollableViewportSize().height);
            AccessibleTable columnHeader = accessibleTable.getAccessibleColumnHeader();
            assertEquals(1, columnHeader.getAccessibleRowCount());
            assertEquals(5, columnHeader.getAccessibleColumnCount());
            assertEquals(
                    "ID",
                    columnHeader.getAccessibleAt(0, 0)
                            .getAccessibleContext()
                            .getAccessibleName());
            assertEquals(
                    "Progress",
                    columnHeader.getAccessibleAt(0, 4)
                            .getAccessibleContext()
                            .getAccessibleName());
            assertEquals(
                    "job-7",
                    accessibleTable.getAccessibleAt(7, 1)
                            .getAccessibleContext()
                            .getAccessibleName());
            assertEquals("Processing", table.getValueAt(7, 3));

            find(tab, "fixture.mark_done_button", JButton.class).doClick();
            assertEquals("Done", table.getValueAt(7, 3));
            find(tab, "fixture.reset_table_button", JButton.class).doClick();
            assertEquals("Processing", table.getValueAt(7, 3));

            find(tab, "fixture.select_row_button", JButton.class).doClick();
            assertArrayEquals(new int[] {7}, table.getSelectedRows());
            assertArrayEquals(new int[] {0, 1, 2, 3, 4}, table.getSelectedColumns());

            find(tab, "fixture.select_few_button", JButton.class).doClick();
            assertArrayEquals(new int[] {1, 3, 5}, table.getSelectedRows());
            assertArrayEquals(new int[0], table.getSelectedColumns());

            find(tab, "fixture.select_column_button", JButton.class).doClick();
            assertEquals(100, table.getSelectedRowCount());
            assertArrayEquals(new int[] {3}, table.getSelectedColumns());
            find(tab, "fixture.clear_selection_button", JButton.class).doClick();
            assertArrayEquals(new int[0], table.getSelectedRows());

            JButton addRow = find(tab, "fixture.table_add_row_button", JButton.class);
            JButton removeRow = find(tab, "fixture.table_remove_row_button", JButton.class);
            assertEquals(100, table.getRowCount());
            addRow.doClick();
            assertEquals(101, table.getRowCount());
            assertEquals("job-100", table.getValueAt(100, 1));
            addRow.doClick(); // repeated click is a no-op, not a second extra row
            assertEquals(101, table.getRowCount());
            removeRow.doClick();
            assertEquals(100, table.getRowCount());
            removeRow.doClick(); // repeated click is a no-op below the base row count
            assertEquals(100, table.getRowCount());
            return null;
        });
    }

    @Test
    void syntheticTableCellHasNoBoundsOrActionSurface() throws Exception {
        onEdt(() -> {
            SyntheticAccessibleTable component = new SyntheticAccessibleTable();
            AccessibleContext context = component.getAccessibleContext();
            AccessibleTable table = context.getAccessibleTable();

            assertEquals("fixture.synthetic_table", context.getAccessibleName());
            assertEquals(AccessibleRole.TABLE, context.getAccessibleRole());
            assertEquals(3, table.getAccessibleRowCount());
            assertEquals(1, table.getAccessibleColumnCount());
            Accessible cell = table.getAccessibleAt(0, 0);
            assertEquals(
                    "fixture.synthetic_cell_0_0",
                    cell.getAccessibleContext().getAccessibleName());
            assertNull(cell.getAccessibleContext().getAccessibleComponent());
            assertNull(cell.getAccessibleContext().getAccessibleAction());
            assertFalse(table.isAccessibleSelected(0, 0));
            assertEquals(1, table.getAccessibleRowExtentAt(0, 0));
            assertNull(table.getAccessibleAt(3, 0));
            return null;
        });
    }

    @Test
    void syntheticTableMergedCellSpansTwoRowsAndHasBounds() throws Exception {
        onEdt(() -> {
            SyntheticAccessibleTable component = new SyntheticAccessibleTable();
            AccessibleTable table = component.getAccessibleContext().getAccessibleTable();

            Accessible topHalf = table.getAccessibleAt(1, 0);
            Accessible bottomHalf = table.getAccessibleAt(2, 0);
            assertEquals(
                    "fixture.synthetic_merged_cell",
                    topHalf.getAccessibleContext().getAccessibleName());
            // A row-spanning cell reports the same Accessible for every row it covers.
            assertEquals(topHalf, bottomHalf);
            assertEquals(2, table.getAccessibleRowExtentAt(1, 0));
            assertEquals(2, table.getAccessibleRowExtentAt(2, 0));
            assertNotNull(topHalf.getAccessibleContext().getAccessibleComponent());
            return null;
        });
    }

    @Test
    void dynamicControlsAndTimerHaveDeterministicCleanup() throws Exception {
        onEdt(() -> {
            SwingFixtureApp app = new SwingFixtureApp();
            JPanel tab = app.buildDynamicTab();
            JLabel count = find(tab, "fixture.dynamic_count_label", JLabel.class);

            assertEquals("items: 0", accessibleDescription(count));
            find(tab, "fixture.add_item_button", JButton.class).doClick();
            assertEquals("items: 1", accessibleDescription(count));
            assertEquals(
                    "Item 1",
                    accessibleDescription(find(tab, "fixture.dynamic_item_1", JLabel.class)));
            find(tab, "fixture.remove_item_button", JButton.class).doClick();
            assertEquals("items: 0", accessibleDescription(count));

            app.buildLocatorTab();
            app.startAutoNodeCycle();
            assertTrue(app.isAutoNodeCycleRunning());
            app.stopAutoNodeCycle();
            assertFalse(app.isAutoNodeCycleRunning());
            return null;
        });
    }

    @Test
    void accessibleStatusAndTableModelPublishMutationEvents() throws Exception {
        onEdt(() -> {
            JLabel status = JabDialogRepro.createStatusLabel();
            AtomicInteger descriptions = new AtomicInteger();
            status.getAccessibleContext().addPropertyChangeListener(event -> {
                if (AccessibleContext.ACCESSIBLE_DESCRIPTION_PROPERTY.equals(
                        event.getPropertyName())) {
                    descriptions.incrementAndGet();
                }
            });
            JabDialogRepro.setStatus(status, "opened: " + JabDialogRepro.SCENARIO_A_TITLE);
            assertEquals("repro.status", accessibleName(status));
            assertEquals("opened: Scenario A", accessibleDescription(status));
            assertTrue(descriptions.get() >= 1);

            SwingFixtureApp app = new SwingFixtureApp();
            JPanel tableTab = app.buildTableTab();
            JTable table = find(tableTab, "fixture.table", JTable.class);
            AtomicInteger modelEvents = new AtomicInteger();
            table.getModel().addTableModelListener(event -> modelEvents.incrementAndGet());
            find(tableTab, "fixture.mark_done_button", JButton.class).doClick();
            assertEquals(1, modelEvents.get());
            return null;
        });
    }

    @Test
    void locatorTabHasStableDuplicateNamesAndActionabilityStates() throws Exception {
        onEdt(() -> {
            JPanel tab = new SwingFixtureApp().buildLocatorTab();

            JPanel scopeAlpha = find(tab, "fixture.scope_alpha", JPanel.class);
            JPanel scopeBeta = find(tab, "fixture.scope_beta", JPanel.class);
            assertEquals(
                    "duplicate in alpha",
                    accessibleDescription(find(scopeAlpha, "fixture.duplicate", JButton.class)));
            assertEquals(
                    "duplicate in beta",
                    accessibleDescription(find(scopeBeta, "fixture.duplicate", JButton.class)));

            JButton visible = find(tab, "fixture.visible_button", JButton.class);
            assertTrue(visible.isVisible());
            assertTrue(visible.isEnabled());
            assertEquals("visible and enabled", accessibleDescription(visible));

            JButton hidden = find(tab, "fixture.hidden_button", JButton.class);
            assertFalse(hidden.isVisible());
            assertEquals("hidden but attached", accessibleDescription(hidden));

            JButton disabled = find(tab, "fixture.locator_disabled_button", JButton.class);
            assertFalse(disabled.isEnabled());
            assertEquals("visible but disabled", accessibleDescription(disabled));
            return null;
        });
    }

    @Test
    void dialogReproWindowTitlesMatchTheirWin32SearchContract() {
        // The integration suite's Win32 window-title lookups (test_modal_dialogs.py,
        // conftest.py's wait_for_raw_window) hard-code these same six strings
        // independently, since Python cannot reference a Java constant - this test
        // exists so a change to any one of `JabDialogRepro`'s title constants is at
        // least caught on the Java side immediately, rather than only surfacing much
        // later as a Win32 window-not-found failure in the slow integration suite.
        assertEquals("JAB dialog repro", JabDialogRepro.MAIN_TITLE);
        assertEquals("Scenario A", JabDialogRepro.SCENARIO_A_TITLE);
        assertEquals("Scenario B", JabDialogRepro.SCENARIO_B_TITLE);
        assertEquals("Scenario C", JabDialogRepro.SCENARIO_C_TITLE);
        assertEquals("Scenario Nested", JabDialogRepro.SCENARIO_NESTED_TITLE);
        assertEquals("Scenario First", JabDialogRepro.SCENARIO_FIRST_TITLE);
    }

    @Test
    void lifecycleStatusTransitionsFromRunningToShuttingDownWithoutExitingTestJvm()
            throws Exception {
        // Deliberately never calls the real shutdown-button listener: that schedules
        // a genuine `System.exit(0)` ~200ms later, which would kill this Gradle test
        // JVM mid-suite. `markShuttingDown` isolates the observable text/description
        // transition from the Timer/System.exit side effect (test-app-review.md
        // finding C3-3).
        onEdt(() -> {
            JLabel status = LifecycleFixtureApp.createStatusLabel();
            assertEquals("fixture.shutdown_status", accessibleName(status));
            assertEquals("running", status.getText());
            assertEquals("running", accessibleDescription(status));

            LifecycleFixtureApp.markShuttingDown(status);
            assertEquals("shutting-down", status.getText());
            assertEquals("shutting-down", accessibleDescription(status));
            return null;
        });
    }

    @Test
    void invalidLauncherModeIsDiagnosticWithoutExitingTestJvm() {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        int exitCode;
        try (PrintStream error = new PrintStream(buffer, true, StandardCharsets.UTF_8)) {
            exitCode = FixtureLauncher.run(new String[] {"invalid"}, error);
        }
        assertEquals(2, exitCode);
        assertTrue(buffer.toString(StandardCharsets.UTF_8).contains("Unknown fixture mode: invalid"));
    }

    private static String accessibleName(Component component) {
        if (component instanceof Accessible accessible) {
            return accessible.getAccessibleContext().getAccessibleName();
        }
        return null;
    }

    private static String accessibleDescription(Component component) {
        if (component instanceof Accessible accessible) {
            return accessible.getAccessibleContext().getAccessibleDescription();
        }
        return null;
    }

    private static <T extends Component> T find(
            Container root, String name, Class<T> expectedType) {
        Component match = findByName(root, name);
        if (match == null) {
            throw new AssertionError("No component with accessible name " + name);
        }
        // A single type check outside the search recursion: previously
        // `assertInstanceOf`'s failure was thrown *inside* the recursive walk and
        // caught by the same `catch (AssertionError ignored)` meant only for "not
        // found in this subtree", silently discarding a genuine name-found /
        // wrong-type mismatch and reporting the misleading "No component with
        // accessible name" instead (test-app-review.md finding C3-5).
        return assertInstanceOf(expectedType, match);
    }

    private static Component findByName(Container root, String name) {
        if (name.equals(accessibleName(root))) {
            return root;
        }
        for (Component child : root.getComponents()) {
            if (name.equals(accessibleName(child))) {
                return child;
            }
            if (child instanceof Container container) {
                Component found = findByName(container, name);
                if (found != null) {
                    return found;
                }
            }
        }
        return null;
    }

    private static <T> T onEdt(Callable<T> action) throws Exception {
        if (SwingUtilities.isEventDispatchThread()) {
            return action.call();
        }
        AtomicReference<T> result = new AtomicReference<>();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        SwingUtilities.invokeAndWait(() -> {
            try {
                result.set(action.call());
            } catch (Throwable error) {
                failure.set(error);
            }
        });
        Throwable error = failure.get();
        if (error instanceof Exception exception) {
            throw exception;
        }
        if (error instanceof Error fatal) {
            throw fatal;
        }
        return result.get();
    }
}

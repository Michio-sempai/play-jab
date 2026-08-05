import java.awt.Dimension;
import java.util.Locale;
import javax.accessibility.Accessible;
import javax.accessibility.AccessibleContext;
import javax.accessibility.AccessibleRole;
import javax.accessibility.AccessibleStateSet;
import javax.accessibility.AccessibleTable;
import javax.swing.JComponent;

/**
 * Minimal deterministic table for the negative table-cell actionability contract.
 *
 * <p>The sole cell intentionally exposes neither {@code AccessibleComponent} (and therefore no
 * usable bounds) nor {@code AccessibleAction}. A regular {@code JTable} cannot express that exact
 * combination consistently on JDK 17, so the realistic fixture and this diagnostic fixture stay
 * separate.
 */
final class SyntheticAccessibleTable extends JComponent implements Accessible {

    private static final int CELL_COUNT = 1;

    SyntheticAccessibleTable() {
        getAccessibleContext().setAccessibleName("fixture.synthetic_table");
        getAccessibleContext().setAccessibleDescription(
                "diagnostic table with a non-actionable cell");
        setPreferredSize(new Dimension(1, 1));
    }

    @Override
    public AccessibleContext getAccessibleContext() {
        if (accessibleContext == null) {
            accessibleContext = new AccessibleSyntheticTable();
        }
        return accessibleContext;
    }

    protected final class AccessibleSyntheticTable extends AccessibleJComponent
            implements AccessibleTable {

        private final Accessible diagnosticCell = new DiagnosticCell();

        @Override
        public AccessibleRole getAccessibleRole() {
            return AccessibleRole.TABLE;
        }

        @Override
        public AccessibleTable getAccessibleTable() {
            return this;
        }

        @Override
        public Accessible getAccessibleCaption() {
            return null;
        }

        @Override
        public void setAccessibleCaption(Accessible caption) {
            // The diagnostic table deliberately has no caption context.
        }

        @Override
        public Accessible getAccessibleSummary() {
            return null;
        }

        @Override
        public void setAccessibleSummary(Accessible summary) {
            // The diagnostic table deliberately has no summary context.
        }

        @Override
        public int getAccessibleRowCount() {
            return CELL_COUNT;
        }

        @Override
        public int getAccessibleColumnCount() {
            return CELL_COUNT;
        }

        @Override
        public Accessible getAccessibleAt(int row, int column) {
            return row == 0 && column == 0 ? diagnosticCell : null;
        }

        @Override
        public int getAccessibleRowExtentAt(int row, int column) {
            return row == 0 && column == 0 ? CELL_COUNT : 0;
        }

        @Override
        public int getAccessibleColumnExtentAt(int row, int column) {
            return row == 0 && column == 0 ? CELL_COUNT : 0;
        }

        @Override
        public AccessibleTable getAccessibleRowHeader() {
            return null;
        }

        @Override
        public void setAccessibleRowHeader(AccessibleTable table) {
            // The diagnostic table deliberately has no row header.
        }

        @Override
        public AccessibleTable getAccessibleColumnHeader() {
            return null;
        }

        @Override
        public void setAccessibleColumnHeader(AccessibleTable table) {
            // The diagnostic table deliberately has no column header.
        }

        @Override
        public Accessible getAccessibleRowDescription(int row) {
            return null;
        }

        @Override
        public void setAccessibleRowDescription(int row, Accessible description) {
            // The diagnostic table deliberately has no row descriptions.
        }

        @Override
        public Accessible getAccessibleColumnDescription(int column) {
            return null;
        }

        @Override
        public void setAccessibleColumnDescription(int column, Accessible description) {
            // The diagnostic table deliberately has no column descriptions.
        }

        @Override
        public boolean isAccessibleSelected(int row, int column) {
            return false;
        }

        @Override
        public boolean isAccessibleRowSelected(int row) {
            return false;
        }

        @Override
        public boolean isAccessibleColumnSelected(int column) {
            return false;
        }

        @Override
        public int[] getSelectedAccessibleRows() {
            return new int[0];
        }

        @Override
        public int[] getSelectedAccessibleColumns() {
            return new int[0];
        }
    }

    private final class DiagnosticCell implements Accessible {

        private final AccessibleContext context = new DiagnosticCellContext();

        @Override
        public AccessibleContext getAccessibleContext() {
            return context;
        }
    }

    private final class DiagnosticCellContext extends AccessibleContext {

        DiagnosticCellContext() {
            setAccessibleName("fixture.synthetic_cell_0_0");
            setAccessibleDescription("cell without bounds or actions");
            setAccessibleParent(SyntheticAccessibleTable.this);
        }

        @Override
        public AccessibleRole getAccessibleRole() {
            return AccessibleRole.LABEL;
        }

        @Override
        public AccessibleStateSet getAccessibleStateSet() {
            return new AccessibleStateSet();
        }

        @Override
        public int getAccessibleIndexInParent() {
            return 0;
        }

        @Override
        public int getAccessibleChildrenCount() {
            return 0;
        }

        @Override
        public Accessible getAccessibleChild(int index) {
            return null;
        }

        @Override
        public Locale getLocale() {
            return Locale.ROOT;
        }
    }
}

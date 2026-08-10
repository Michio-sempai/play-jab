import java.awt.Color;
import java.awt.Cursor;
import java.awt.Dimension;
import java.awt.Font;
import java.awt.FontMetrics;
import java.awt.Point;
import java.awt.Rectangle;
import java.awt.event.FocusListener;
import java.util.Locale;
import javax.accessibility.Accessible;
import javax.accessibility.AccessibleComponent;
import javax.accessibility.AccessibleContext;
import javax.accessibility.AccessibleRole;
import javax.accessibility.AccessibleState;
import javax.accessibility.AccessibleStateSet;
import javax.accessibility.AccessibleTable;
import javax.swing.JComponent;

/**
 * Minimal deterministic table for the negative table-cell actionability contract, plus a
 * row-spanning ("merged") cell a real {@code JTable} cannot express at all.
 *
 * <p>Row 0's cell intentionally exposes neither {@code AccessibleComponent} (and therefore no
 * usable bounds) nor {@code AccessibleAction}. A regular {@code JTable} cannot express that exact
 * combination consistently on JDK 17, so the realistic fixture and this diagnostic fixture stay
 * separate.
 *
 * <p>Rows 1-2 are one merged cell ({@code getAccessibleRowExtentAt == 2} for both rows,
 * {@code getAccessibleAt} returns the same {@code Accessible} for both) - unlike the row 0 cell,
 * it does implement {@code AccessibleComponent}, since row-span reporting and bounds-less cells
 * are independent axes worth proving separately.
 */
final class SyntheticAccessibleTable extends JComponent implements Accessible {

    // Never serialized; this fixture is only ever constructed and torn down within
    // one JVM. Declared solely to silence javac's [serial] lint warning.
    private static final long serialVersionUID = 1L;

    private static final int CELL_COUNT = 1;
    private static final int ROW_COUNT = 3;
    private static final int MERGED_ROW_EXTENT = 2;

    SyntheticAccessibleTable() {
        getAccessibleContext().setAccessibleName("fixture.synthetic_table");
        getAccessibleContext().setAccessibleDescription(
                "diagnostic table with a non-actionable cell and a merged cell");
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

        private static final long serialVersionUID = 1L;

        private final Accessible diagnosticCell = new DiagnosticCell();
        private final Accessible mergedCell = new MergedCell();
        private final AccessibleTable rowHeaderTable = new RowHeaderTable();

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
            return ROW_COUNT;
        }

        @Override
        public int getAccessibleColumnCount() {
            return CELL_COUNT;
        }

        @Override
        public Accessible getAccessibleAt(int row, int column) {
            if (column != 0) {
                return null;
            }
            if (row == 0) {
                return diagnosticCell;
            }
            if (row == 1 || row == 2) {
                return mergedCell;
            }
            return null;
        }

        @Override
        public int getAccessibleRowExtentAt(int row, int column) {
            if (column != 0) {
                return 0;
            }
            if (row == 0) {
                return CELL_COUNT;
            }
            if (row == 1 || row == 2) {
                return MERGED_ROW_EXTENT;
            }
            return 0;
        }

        @Override
        public int getAccessibleColumnExtentAt(int row, int column) {
            return row >= 0 && row < ROW_COUNT && column == 0 ? CELL_COUNT : 0;
        }

        @Override
        public AccessibleTable getAccessibleRowHeader() {
            return rowHeaderTable;
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

    private final class MergedCell implements Accessible {

        private final AccessibleContext context = new MergedCellContext();

        @Override
        public AccessibleContext getAccessibleContext() {
            return context;
        }
    }

    private final class MergedCellContext extends AccessibleContext implements AccessibleComponent {

        MergedCellContext() {
            setAccessibleName("fixture.synthetic_merged_cell");
            setAccessibleDescription("cell spanning rows 1 and 2 (rowExtent=2)");
            setAccessibleParent(SyntheticAccessibleTable.this);
        }

        @Override
        public AccessibleRole getAccessibleRole() {
            return AccessibleRole.LABEL;
        }

        @Override
        public AccessibleStateSet getAccessibleStateSet() {
            AccessibleStateSet states = new AccessibleStateSet();
            states.add(AccessibleState.VISIBLE);
            states.add(AccessibleState.SHOWING);
            states.add(AccessibleState.ENABLED);
            return states;
        }

        @Override
        public int getAccessibleIndexInParent() {
            return 1;
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

        @Override
        public AccessibleComponent getAccessibleComponent() {
            return this;
        }

        @Override
        public Color getBackground() {
            return null;
        }

        @Override
        public void setBackground(Color color) {
            // Not backed by a real rendered component.
        }

        @Override
        public Color getForeground() {
            return null;
        }

        @Override
        public void setForeground(Color color) {
            // Not backed by a real rendered component.
        }

        @Override
        public Cursor getCursor() {
            return null;
        }

        @Override
        public void setCursor(Cursor cursor) {
            // Not backed by a real rendered component.
        }

        @Override
        public Font getFont() {
            return null;
        }

        @Override
        public void setFont(Font font) {
            // Not backed by a real rendered component.
        }

        @Override
        public FontMetrics getFontMetrics(Font font) {
            return null;
        }

        @Override
        public boolean isEnabled() {
            return true;
        }

        @Override
        public void setEnabled(boolean enabled) {
            // Always enabled; nothing to toggle.
        }

        @Override
        public boolean isVisible() {
            return true;
        }

        @Override
        public void setVisible(boolean visible) {
            // Always visible; nothing to toggle.
        }

        @Override
        public boolean isShowing() {
            return true;
        }

        @Override
        public boolean contains(Point point) {
            return point.x >= 0 && point.x < 10 && point.y >= 0 && point.y < 10;
        }

        @Override
        public Point getLocationOnScreen() {
            return new Point(0, 0);
        }

        @Override
        public Point getLocation() {
            return new Point(0, 0);
        }

        @Override
        public void setLocation(Point point) {
            // Fixed, deterministic bounds by design.
        }

        @Override
        public Rectangle getBounds() {
            return new Rectangle(0, 0, 10, 10);
        }

        @Override
        public void setBounds(Rectangle rectangle) {
            // Fixed, deterministic bounds by design.
        }

        @Override
        public Dimension getSize() {
            return new Dimension(10, 10);
        }

        @Override
        public void setSize(Dimension dimension) {
            // Fixed, deterministic bounds by design.
        }

        @Override
        public Accessible getAccessibleAt(Point point) {
            return null;
        }

        @Override
        public boolean isFocusTraversable() {
            return false;
        }

        @Override
        public void requestFocus() {
            // Not focus-traversable.
        }

        @Override
        public void addFocusListener(FocusListener listener) {
            // No focus events are ever fired.
        }

        @Override
        public void removeFocusListener(FocusListener listener) {
            // No focus events are ever fired.
        }
    }

    /**
     * The 1x1 row header a real {@code JTable} never publishes on JDK 17 (proven empirically:
     * {@code AccessibleJTable.getAccessibleRowHeader()} returns {@code null} unless
     * {@code setAccessibleRowHeader(...)} is called explicitly, which no production code does).
     * This diagnostic table gives {@code Table.row_header(row)} a single positive scenario.
     */
    private final class RowHeaderTable implements AccessibleTable {

        private final Accessible headerCell = new RowHeaderCell();

        @Override
        public Accessible getAccessibleCaption() {
            return null;
        }

        @Override
        public void setAccessibleCaption(Accessible caption) {
            // The row header table deliberately has no caption context.
        }

        @Override
        public Accessible getAccessibleSummary() {
            return null;
        }

        @Override
        public void setAccessibleSummary(Accessible summary) {
            // The row header table deliberately has no summary context.
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
            return row == 0 && column == 0 ? headerCell : null;
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
            // The row header table deliberately has no row header of its own.
        }

        @Override
        public AccessibleTable getAccessibleColumnHeader() {
            return null;
        }

        @Override
        public void setAccessibleColumnHeader(AccessibleTable table) {
            // The row header table deliberately has no column header of its own.
        }

        @Override
        public Accessible getAccessibleRowDescription(int row) {
            return null;
        }

        @Override
        public void setAccessibleRowDescription(int row, Accessible description) {
            // The row header table deliberately has no row descriptions.
        }

        @Override
        public Accessible getAccessibleColumnDescription(int column) {
            return null;
        }

        @Override
        public void setAccessibleColumnDescription(int column, Accessible description) {
            // The row header table deliberately has no column descriptions.
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

    private final class RowHeaderCell implements Accessible {

        private final AccessibleContext context = new RowHeaderCellContext();

        @Override
        public AccessibleContext getAccessibleContext() {
            return context;
        }
    }

    private final class RowHeaderCellContext extends AccessibleContext {

        RowHeaderCellContext() {
            setAccessibleName("fixture.synthetic_row_header_0");
            setAccessibleDescription("row header cell for the diagnostic table");
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

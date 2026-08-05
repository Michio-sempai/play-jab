/**
 * Единая точка входа fixture-приложения {@code play-jab}.
 *
 * <p>В JAR-е живут две независимые fixture, каждая со своим top-level окном:
 *
 * <ul>
 *   <li>{@code swing} (по умолчанию) — {@link SwingFixtureApp}, общая fixture для
 *       интеграционных тестов: button, text/password fields, checkbox, combo/list,
 *       tabs, table, locator-сценарии и динамически добавляемые элементы.</li>
 *   <li>{@code dialog} — {@link JabDialogRepro}, узкая regression fixture для
 *       блокировки синхронного JAB action до закрытия модального окна
 *       (Сценарии A/B/C и режим {@code -Ddialog.first=true}).</li>
 * </ul>
 *
 * <p>Запуск:
 *
 * <pre>
 * java -Djavax.accessibility.assistive_technologies=com.sun.java.accessibility.AccessBridge \
 *      -jar jab-swing-app.jar [swing [--second-window]|dialog]
 * </pre>
 *
 * <p>Без флага {@code assistive_technologies} JAB для процесса не активируется
 * и fixture бесполезна. Gradle-задачи {@code run}, {@code runDialogRepro} и
 * {@code runDialogFirst} передают его сами.
 */
public final class FixtureLauncher {

    private FixtureLauncher() {
    }

    private static final String ASSISTIVE_TECHNOLOGIES =
            "javax.accessibility.assistive_technologies";

    public static void main(String[] args) {
        warnIfBridgeInactive();
        String mode = args.length > 0 ? args[0] : "swing";
        switch (mode) {
            case "swing" -> SwingFixtureApp.main(
                    java.util.Arrays.copyOfRange(args, 1, args.length));
            case "dialog" -> JabDialogRepro.main(new String[0]);
            default -> {
                System.err.println(
                        "Unknown fixture mode: " + mode
                                + " (expected 'swing' or 'dialog')");
                System.exit(2);
            }
        }
    }

    /**
     * JVM args не передаются через манифест JAR, поэтому запуск
     * {@code java -jar jab-swing-app.jar} молча стартует процесс без JAB, и тест
     * видит только «окно не найдено». Предупреждение делает причину явной.
     */
    private static void warnIfBridgeInactive() {
        if (System.getProperty(ASSISTIVE_TECHNOLOGIES) == null) {
            System.err.println(
                    "WARNING: -D" + ASSISTIVE_TECHNOLOGIES
                            + "=com.sun.java.accessibility.AccessBridge is not set; "
                            + "Java Access Bridge will be inactive for this process.");
        }
    }
}

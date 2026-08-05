plugins {
    application
}

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(17))
    }
}

// Without this flag JAB is never activated for the process and the fixture is
// useless for integration tests.
val jabJvmArgs = listOf(
    "-Djavax.accessibility.assistive_technologies=com.sun.java.accessibility.AccessBridge"
)

application {
    mainClass.set("FixtureLauncher")
    // Reaches the generated start scripts (installDist, distZip/distTar). A bare
    // `java -jar` cannot pick JVM args up from the manifest, so that path still
    // needs the flag on the command line — FixtureLauncher warns when it is missing.
    applicationDefaultJvmArgs = jabJvmArgs
}

// Sources carry Cyrillic comments and the fixture renders non-ASCII labels;
// javac would otherwise fall back to the Windows platform charset.
tasks.withType<JavaCompile>().configureEach {
    options.encoding = "UTF-8"
}

tasks.named<Jar>("jar") {
    manifest {
        attributes("Main-Class" to application.mainClass.get())
    }
}

tasks.named<JavaExec>("run") {
    // General-purpose Swing fixture: button, text/password fields, checkbox,
    // combo/list, tabs, table and a dynamically populated container.
    jvmArgs = jabJvmArgs
    args = listOf("swing")
}

tasks.register<JavaExec>("runDialogRepro") {
    group = "application"
    description = "Show the JDialog JAB-access regression fixture (Scenarios A/B/C)."
    mainClass.set("FixtureLauncher")
    classpath = sourceSets["main"].runtimeClasspath
    jvmArgs = jabJvmArgs
    args = listOf("dialog")
}

tasks.register<JavaExec>("runDialogFirst") {
    group = "application"
    description =
        "Show the modal dialog as the first top-level window for diagnostics " +
        "(not a causal proof for the A/B regression)."
    mainClass.set("FixtureLauncher")
    classpath = sourceSets["main"].runtimeClasspath
    jvmArgs = jabJvmArgs + listOf("-Ddialog.first=true")
    args = listOf("dialog")
}

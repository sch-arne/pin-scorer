plugins {
    id("com.android.application") version "8.11.1" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    // Chaquopy fuehrt Python im APK aus. 17.0 unterstuetzt Python 3.10 bis
    // 3.14 und AGP 7.3 bis 9.2 -- wir brauchen 3.10, weil OpenCV in
    // Chaquopys Paketquelle nur fuer cp38 und cp310 vorliegt.
    id("com.chaquo.python") version "17.0.0" apply false
}

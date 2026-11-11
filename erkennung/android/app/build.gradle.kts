plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "de.kegelcv"
    compileSdk = 36

    defaultConfig {
        applicationId = "de.kegelcv"
        // Chaquopy 17 verlangt mindestens 24.
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "0.1"

        ndk {
            // NUR arm64. Jede weitere Architektur zieht eine eigene Kopie von
            // Python, numpy und OpenCV ins APK -- das sind je rund 40 MB fuer
            // Geraete, die es seit Jahren nicht mehr gibt.
            abiFilters += listOf("arm64-v8a")
        }

    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

// Chaquopy wird in der Kotlin-Fassung ueber einen eigenen Block eingestellt,
// nicht ueber `android.defaultConfig`.
chaquopy {
    defaultConfig {
        // 3.10 ist nicht beliebig gewaehlt: OpenCV liegt in Chaquopys
        // Paketquelle nur fuer cp38 und cp310 vor -- und 3.10 ist zugleich die
        // Version, auf der das Projekt entwickelt wird.
        version = "3.10"

        pip {
            // OpenCV 4.5.1 ist das Neueste, was Chaquopy anbietet; das Projekt
            // selbst laeuft auf 5.0. Der Qt-freie Kern wurde am 2026-09-14
            // gegen 4.5 geprueft und lief ohne eine einzige echte Abweichung.
            // Siehe android/README.md -- dieser Test gehoert wiederholt, bevor
            // eine dieser Versionen steigt.
            install("opencv-python==4.5.1.48")
            install("numpy==1.26.2")
            install("pyyaml==6.0.3")
        }
    }

    sourceSets {
        getByName("main") {
            // DER ERKENNUNGSKERN SELBST -- nicht kopiert, sondern derselbe
            // Quelltext, den auch der Entwicklungsrechner benutzt. Eine
            // zweite Kopie waere in einem Monat ein zweites Programm.
            srcDir("../../src")
        }
    }
}

// DIE ASSETS KOMMEN AUS DEM PROJEKT, nicht aus einer zweiten Kopie im
// android-Ordner. Zwei Fassungen derselben Konfiguration waeren in einem Monat
// zwei verschiedene Konfigurationen -- und die Abweichung faellt erst auf,
// wenn das Telefon anders zaehlt als der Rechner.
val assetsHolen by tasks.registering(Copy::class) {
    from("../../config/default.yaml")
    from("../../models/yolox_tiny_android.onnx")
    // Die Tafelbibliothek: Musterbild und Bereiche einer FUNK-Anzeigetafel.
    // Ohne sie kann die automatische Suche nichts erkennen.
    from("../../data/boardtypes") { into("boardtypes") }
    into(layout.projectDirectory.dir("src/main/assets"))
}
tasks.named("preBuild") { dependsOn(assetsHolen) }

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")

    // CameraX. `OUTPUT_IMAGE_FORMAT_RGBA_8888` gibt es seit 1.3 -- damit
    // kommt jedes Bild als EINE Ebene statt als drei YUV-Ebenen mit
    // geraeteabhaengigen Abstaenden.
    val camerax = "1.4.1"
    implementation("androidx.camera:camera-core:$camerax")
    implementation("androidx.camera:camera-camera2:$camerax")
    implementation("androidx.camera:camera-lifecycle:$camerax")
    implementation("androidx.camera:camera-view:$camerax")
}

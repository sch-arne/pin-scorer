package de.kegelcv

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Log
import android.util.Size
import android.widget.Button
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.util.concurrent.Executors
import kotlin.concurrent.thread

/**
 * Kamerabild in den Erkennungskern -- und die Frage, an der die App haengt.
 *
 * Der Kern laeuft auf diesem Geraet bereits (siehe `selbsttest`). Offen ist,
 * ob die automatische TAFELSUCHE mit einem Handybild zurechtkommt: Ihr
 * Musterbild stammt von einer fest montierten Hallenkamera. Ob dieselben
 * Merkmale in einer schraeg und aus anderer Entfernung aufgenommenen Ansicht
 * wiederzufinden sind, entscheidet darueber, ob die App bedienbar wird oder ob
 * jede Tafel von Hand eingemessen werden muss.
 *
 * DIE STATIVPFLICHT gilt hier genauso. Bewegungsmaske, Kalibrierviereck und
 * Tafelwache setzen eine feste Kamera voraus -- bei BUG-026 haben wenige Pixel
 * Versatz eine Bahn stillgelegt.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var ausgabe: TextView
    private lateinit var vorschau: PreviewView
    private lateinit var knopfTafeln: Button

    /** Ein eigener Strang fuers Bild: Die Oberflaeche darf davon nichts merken. */
    private val bildstrang = Executors.newSingleThreadExecutor()

    /**
     * Nur jedes n-te Bild geht nach Python. Die Uebergabe kostet eine Kopie von
     * rund 8 MB; sie in voller Bildrate zu ziehen waere Rechenzeit auf
     * Verdacht, solange nur das ZULETZT gesehene Bild gebraucht wird.
     */
    private val nurJedes = 5
    private var gezaehlt = 0

    /**
     * Sucht fortlaufend nach Anzeigetafeln, statt auf einen Knopfdruck zu
     * warten. Wer die Kamera ausrichtet, braucht die Rueckmeldung WAEHREND er
     * sie bewegt -- ein Knopf hiesse: hinstellen, druecken, ablesen, korrigieren,
     * wieder druecken.
     */
    private var dauersuche = true
    private var laeuftGerade = false
    private val takt = android.os.Handler(android.os.Looper.getMainLooper())

    private val kamerafrage = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { erlaubt ->
        if (erlaubt) starteKamera()
        else zeige("Ohne Kamerafreigabe geht hier nichts.")
    }

    override fun onCreate(zustand: Bundle?) {
        super.onCreate(zustand)
        setContentView(R.layout.activity_main)
        ausgabe = findViewById(R.id.ausgabe)
        vorschau = findViewById(R.id.vorschau)
        haltRaenderFrei()
        findViewById<Button>(R.id.knopf_selbsttest).setOnClickListener {
            starteSelbsttest()
        }
        knopfTafeln = findViewById(R.id.knopf_tafeln)
        // Der Knopf beschriftet den ZUSTAND, nicht die Aktion. Stand dort
        // "Tafeln suchen", waehrend die Suche schon lief, schaltete der erste
        // Tipp sie ab -- genau das Gegenteil dessen, was er versprach.
        knopfTafeln.text = if (dauersuche) "Suche laeuft" else "Suche aus"
        knopfTafeln.setOnClickListener {
            dauersuche = !dauersuche
            knopfTafeln.text = if (dauersuche) "Suche laeuft" else "Suche aus"
            if (dauersuche) sucheTafeln()
        }

        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        // Auspacken kostet beim ersten Start ein paar Sekunden (20 MB Modell)
        // und hat auf dem Oberflaechenstrang nichts verloren.
        thread { auspacken("default.yaml"); modellBereitstellen(); bibliothek() }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            == PackageManager.PERMISSION_GRANTED
        ) {
            starteKamera()
        } else {
            kamerafrage.launch(Manifest.permission.CAMERA)
        }
    }

    /**
     * Haelt Text und Knoepfe aus Statusleiste, Navigation und
     * Kameraausschnitt heraus.
     *
     * Seit Android 15 zeichnen Anwendungen randlos: Ohne das hier lag die
     * Ausgabe unter den Statusleistensymbolen und die Knoepfe unter der
     * Navigationsleiste. Feste Abstaende waeren keine Loesung -- im
     * Querformat sitzt der Kameraausschnitt links, im Hochformat oben.
     */
    private fun haltRaenderFrei() {
        val text = findViewById<android.view.View>(R.id.ausgabe_rahmen)
        val knoepfe = findViewById<android.view.View>(R.id.knopfleiste)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.wurzel)) { _, einzuege ->
            val rand = einzuege.getInsets(
                WindowInsetsCompat.Type.systemBars()
                    or WindowInsetsCompat.Type.displayCutout()
            )
            text.updatePadding(left = rand.left, top = rand.top, right = rand.right)
            knoepfe.updatePadding(left = rand.left, right = rand.right,
                                  bottom = rand.bottom)
            einzuege
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        bildstrang.shutdown()
    }

    override fun onResume() {
        super.onResume()
        // Kurz warten, bis die ersten Bilder da sind, dann loslaufen.
        takt.postDelayed({ sucheTafeln() }, 2500)
    }

    override fun onPause() {
        super.onPause()
        takt.removeCallbacksAndMessages(null)
    }

    // -------------------------------------------------------------- Kamera

    private fun starteKamera() {
        val kuenftig = ProcessCameraProvider.getInstance(this)
        kuenftig.addListener({
            val anbieter = kuenftig.get()

            val bild = Preview.Builder().build().also {
                it.surfaceProvider = vorschau.surfaceProvider
            }

            // 1920x1080 angefragt, weil alle gemessenen Groessen des Projekts
            // darauf beruhen -- Tafelbreiten, ROI-Kanten, Bandmasse. Was das
            // Geraet daraus macht, meldet die Ausgabe.
            val aufloesung = ResolutionSelector.Builder()
                .setResolutionStrategy(
                    ResolutionStrategy(
                        Size(1920, 1080),
                        ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER
                    )
                ).build()

            val auswertung = ImageAnalysis.Builder()
                .setResolutionSelector(aufloesung)
                // Nur das neueste Bild. Eine Warteschlange waere hier falsch:
                // Ein Bild von vor zwei Sekunden hilft niemandem, es kostet
                // Speicher und macht die Anzeige traege.
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                // EINE Ebene statt drei YUV-Ebenen. Siehe Kopf von `kamera.py`.
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                // CameraX dreht selbst, statt dass wir es in Python tun.
                // GEMESSEN auf diesem Geraet: cv2.rotate kostete 17,1 ms je
                // Bild -- viermal die Farbwandlung. Hier laeuft es innerhalb
                // der Kamerakette und kann Hardware nutzen.
                .setOutputImageRotationEnabled(true)
                .setTargetRotation(display.rotation)
                .build()
            auswertung.setAnalyzer(bildstrang, ::verarbeite)

            runCatching {
                anbieter.unbindAll()
                anbieter.bindToLifecycle(
                    this, CameraSelector.DEFAULT_BACK_CAMERA, bild, auswertung
                )
            }.onFailure {
                Log.e("KegelCV", "Kamera nicht gebunden", it)
                zeige("Kamera nicht gebunden: ${it.message}")
            }
        }, ContextCompat.getMainExecutor(this))
    }

    /**
     * Ein Kamerabild nach Python.
     *
     * DIE DREHUNG WIRD MITGEGEBEN, nicht verschwiegen. Der Sensor liefert
     * immer in SEINER Lage -- im Hochformat also ein liegendes Bild. Die
     * Vorschau dreht das von selbst, der Bildstrom nicht: Die Tafelsuche saehe
     * eine um 90 Grad gekippte Halle und faende nie etwas. Ein Fehler, der
     * aussieht, als koenne das Verfahren nichts.
     */
    private fun verarbeite(bild: ImageProxy) {
        try {
            gezaehlt += 1
            if (gezaehlt % nurJedes != 0) return
            val ebene = bild.planes[0]
            val puffer = ebene.buffer
            val bytes = ByteArray(puffer.remaining())
            puffer.get(bytes)
            Python.getInstance().getModule("kamera").callAttr(
                "nimm_frame", bytes, bild.width, bild.height, ebene.rowStride,
                bild.imageInfo.rotationDegrees
            )
        } catch (exc: Throwable) {
            Log.w("KegelCV", "Bild nicht uebernommen", exc)
        } finally {
            // IMMER schliessen, auch im Fehlerfall: Ein nicht freigegebenes
            // Bild blockiert den Strom, und die Vorschau friert ein.
            bild.close()
        }
    }

    // ------------------------------------------------------------- Aktionen

    /**
     * Ein Suchlauf, und danach der naechste -- aber erst, wenn dieser fertig
     * ist. Ein fester Takt wuerde Laeufe stapeln, sobald einer laenger dauert
     * als der Takt; gemessen sind es rund 185 ms, aber das haengt am Bild.
     */
    private fun sucheTafeln() {
        if (laeuftGerade || !dauersuche) return
        laeuftGerade = true
        thread {
            val text = runCatching {
                val py = Python.getInstance().getModule("kamera")
                val ergebnis = py.callAttr("suche_tafeln", bibliothek()).toString()
                // Das untersuchte Bild aufheben -- ohne es laesst sich ein
                // Fehlschlag nicht untersuchen, sondern nur bereden.
                py.callAttr("speichere_letztes",
                    File(filesDir, "letztes_bild.jpg").absolutePath)
                ergebnis
            }.getOrElse { fehlertext(it) }
            melde(text)
            laeuftGerade = false
            takt.postDelayed({ sucheTafeln() }, 1200)
        }
    }

    private fun starteSelbsttest() {
        zeige("Selbsttest laeuft ...")
        thread {
            val py = Python.getInstance()
            val text = runCatching {
                val kern = py.getModule("selbsttest")
                    .callAttr("selbsttest", modellBereitstellen()).toString()
                val module = py.getModule("selbsttest")
                    .callAttr("kern", auspacken("default.yaml")).toString()
                listOf(kern, "", "Erkennungskern:", module)
                    .joinToString(System.lineSeparator())
            }.getOrElse { fehlertext(it) }
            melde(text)
        }
    }

    /** Was vom Bildstrom ankommt -- ohne Knopfdruck. */
    private fun zustandZeigen() {
        thread {
            val text = runCatching {
                Python.getInstance().getModule("kamera")
                    .callAttr("zustand").toString()
            }.getOrElse { fehlertext(it) }
            melde(text)
        }
    }

    // ------------------------------------------------------------- Handwerk

    private fun fehlertext(exc: Throwable) =
        "Fehlgeschlagen: ${exc::class.java.simpleName}" +
            System.lineSeparator() + exc.message

    private fun melde(text: String) {
        Log.i("KegelCV", text)
        zeige(text)
    }

    private fun zeige(text: String) = runOnUiThread { ausgabe.text = text }

    private fun modellBereitstellen(): String = auspacken("yolox_tiny_android.onnx")

    /** Entpackt die Tafelbibliothek und gibt ihren Ordner zurueck. */
    private fun bibliothek(): String {
        val ordner = File(filesDir, "boardtypes")
        if (!ordner.isDirectory) ordner.mkdirs()
        runCatching {
            for (name in assets.list("boardtypes").orEmpty()) {
                val ziel = File(ordner, name)
                if (ziel.exists() && ziel.length() > 0) continue
                assets.open("boardtypes/$name").use { quelle ->
                    ziel.outputStream().use { quelle.copyTo(it) }
                }
            }
        }.onFailure { Log.w("KegelCV", "Tafelbibliothek nicht entpackt", it) }
        return ordner.absolutePath
    }

    /** Legt ein Asset als Datei ab und gibt seinen Pfad zurueck. */
    private fun auspacken(name: String): String {
        val ziel = File(filesDir, name)
        if (ziel.exists() && ziel.length() > 0) return ziel.absolutePath
        return runCatching {
            assets.open(name).use { quelle ->
                ziel.outputStream().use { quelle.copyTo(it) }
            }
            ziel.absolutePath
        }.getOrElse {
            Log.w("KegelCV", "Asset nicht entpackt: $name", it)
            ""
        }
    }
}

# D57 / V380 Pro: lokale WildCam-Integration

Stand: 16.11.2026. Zielgerät: D57. Die private LAN-Adresse steht ausschließlich
in der lokalen, nicht versionierten Kamerakonfiguration.

## Ergebnis und Implementierungsstand

Die D57 ist als V380/Macrovideo-Kamera in WildCam integriert. Lokaler Login,
Streamstart, Fragmentzusammensetzung und Medienentschlüsselung sind an dieser
Kamera nachgewiesen. WildCams `CameraThread → V380Bridge → OpenCV` liefert
H.265/HEVC in **2304 × 2592 Pixeln**. Die obere Ansicht ist fest, die untere
beweglich. Lokales PTZ für die untere Kamera ist implementiert und mit echten
Fahr-/Stopp-Befehlen geprüft. Audio ist nicht implementiert.

Die lokale Bildaufteilung ist inzwischen implementiert: Für das Modell D57
öffnen sich zwei unabhängig zoombare Fenster, PTZ nur im unteren Fenster.
Beide nutzen den vorhandenen gemeinsamen Stream und Decoder. Die neue Darstellung
wurde mit aufgezeichnetem Original-HEVC geprüft; Details und die Grenze der
erneuten Liveprüfung stehen im letzten Abschnitt.

Die erste Protokollprüfung decodierte mit FFmpeg **96 Frames in acht Sekunden**
ohne gemeldete Decoderfehler. Der erste Test der implementierten Bridge im echten
CameraThread lieferte **40 Frames**, Bildform `(2592, 2304, 3)`, Bridgefehler `None`.
Zwei weitere vollständige Starts lieferten jeweils **25 Frames**; reguläres
`request_stop()`/`wait()` beendete jeweils Kamera- und Bridge-Thread. Das ist
gezielte Liveprüfung, kein Langzeit- oder Produktionsabnahmetest.
Die endgültige Version wurde zusätzlich über echte Geräteerkennung und das
WildCam-Kamerawidget geprüft: 30 Bilder, beide Bildansichten sichtbar, reguläres
Stoppen erfolgreich.

## Identifikation am Gerät und an der App

| Prüfung | Ergebnis |
| --- | --- |
| Gezielte TCP-Portprüfung | 8800 offen; 80, 443, 554, 5544, 5555, 8000, 8554, 8899, 9000 geschlossen |
| V380-Discovery | `NVDEVSEARCH^100` an UDP 10008, Empfang auf lokalem UDP 10009 |
| Geräteantwort | `NVDEVRESULT^200`, 15 Felder; Geräte-ID und Medienport 8800 vorhanden |
| Android-App | `com.macrovideo.v380pro`, V380 Pro 2.2.92, versionCode 230 |
| Native Bibliothek | `libhsMediaLibrary.so` aus installiertem ARM64-Split untersucht |
| SDK-Symbole | `media_data_decrypt`, `media_data_decrypt_pre_2k`, `setPTZParam`, `setPTZXParam` |

Nmaps Bezeichnung `sunwebadmin` ist ein generischer Portname und kein Nachweis
einer HTTP-Oberfläche. D57 allein identifiziert weder Hersteller noch Firmware.
SDK-Symbole belegen keine PTZ-Unterstützung der konkreten Kamera.

## Bestätigter lokaler Protokollweg

1. Authentifizierung mit Kommando 1167, 520-Byte-Anfrage; Antwort 1168,
   256 Byte, Ergebnis 1001, Geräteversion **32**. Der lokale Benutzer ist `admin`.
2. Frische zweite TCP-Verbindung mit Kommando 301 und Authentifizierungsticket.
   Antwort 401, Ergebnis 1001, **32 Byte**, Kommunikationsversion **20**,
   Auflösung 2304 × 2592. Auf 256 Byte zu warten ist hier falsch.
3. Streamstart mit Kommando 303. Acht Sekunden ergaben 650416 Byte Medien.
4. Videofragmente 0x28/0x29 zusammensetzen; 16-Byte-Frameheader entfernen.
5. Ticket-basierten AES-Schlüssel bilden; 64 Byte je 80-Byte-Fenster per AES-ECB
   entschlüsseln. Ergebnis: HEVC Annex B. Fragmenttyp 0x18 wurde ignoriert.

Die zunächst bereitgestellte E-Mail-Adresse und die Geräte-ID als Benutzer wurden
mit 1011 abgelehnt. Frühere Passwörter für `admin` wurden mit 1012 abgelehnt.
Nach dem Setzen des lokalen Gerätezugangs durch den Nutzer gelang der Login.
Passwörter und vollständige Sitzungstickets stehen nicht in diesem Dokument oder
in versionierten Tests.

Der Prüfclient und die Implementierung sprechen direkt die LAN-IP an, ohne
Cloudaufruf. Betrieb bei gesperrtem Internet wurde nicht getestet.

## Umsetzung in WildCam

- **`v380.py`:** URL-Parser/Builder, gezielte UDP-Erkennung, lokale Anmeldung,
  Stream-Reassembly, Entschlüsselung und Loopback-TCP-Bridge. Netzwerk-Timeouts,
  begrenzte Paket-/Framegrößen und sequenzielle Fragmentprüfung begrenzen defekte
  oder unvollständige Streams. Unterstützt werden Geräteversionen 31/32 mit
  Kommunikationsversion 20; nur Version 32 wurde an echter Hardware geprüft.
- **`stream.py`:** gemeinsame Bridge-Verwaltung für Netvue und V380;
  HEVC/H.264/MJPEG werden durch OpenCV/FFmpeg erkannt. Reolink-Wakeup und
  RTSP-Pfadversuche entfallen für V380. Permanente Authentifizierungsfehler stoppen
  automatische Wiederholungen, Netzwerkfehler nutzen die übliche Reconnect-Schleife.
- **`discovery.py`:** TCP 8800 wird mitgescannt. Ein V380-Eintrag entsteht erst nach
  gültiger UDP-Protokollantwort. Geräte-ID und URL werden übernommen.
- **`dialogs.py`, `main_window.py`, `i18n.py`:** eigener Verbindungstyp `v380`,
  Geräte-ID-Feld, URL-Rundlauf und Übernahme des Suchergebnisses. Ohne Geräte-ID
  wird beim Verbinden gezielt lokal gesucht. `quality=hd|sd` wird beim Editieren
  erhalten. Generierte Fehlermeldungen enthalten keine Zugangsdaten-URL.
- **`ptz.py`:** eigenes V380-Backend auf der laufenden Videositzung; keine
  ONVIF-Abfrage für V380. Die D57 erhält beim Konfigurationsladen das bestätigte
  PTZ-Backend. Die Editieroption ist verfügbar; manuelles Deaktivieren bleibt erhalten.
- **`requirements.txt`:** `cryptography` für Authentifizierung und Medien.

URL-Format:

```text
v380://<user>:<device-password>@<ip>:8800?device_id=<id>&quality=hd
```

Sonderzeichen in Zugangsdaten werden URL-kodiert. Die lokale, ignorierte
`camera_config.json` speichert solche URLs wie andere Kamerazugänge.

Die Architektur folgt der Orb Mini (`NetvueBridge`), nicht deren Drahtprotokoll:
Netvue verwendet TCP 5555, JSON-Kommandos und H.264. Die D57 braucht ihren eigenen
Login, Paketparser und hier HEVC. Firmware und gespeicherte Kameraeinstellungen wurden durch die Protokollprüfungen
nicht geändert. Die späteren PTZ-Tests bewegten die untere Kamera kurz und führten
Gegenbewegungen aus; eine exakt identische Rückkehrposition ist nicht zugesichert.

## Prüfungen und praktische Verwendung

Offline:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
```

Alle **29 Offline-Tests** bestanden (einschließlich der bestehenden Netvue-Tests).
`pip check` meldete keine defekten Abhängigkeiten. Die Tests decken URL-Sonderzeichen, Discovery-Validierung, Authentifizierungsfehler,
fragmentierte TCP-Antworten, zwei Loginverbindungen, 32-Byte-Streamantwort,
Fragmentverlust/-Typwechsel, Entschlüsselung, fehlerhafte Header, Dialog-Rundlauf,
Streamrouting und Ausschluss von ONVIF-PTZ ab. Sie brauchen keine echte Kamera.

Liveprüfung erfolgte zusätzlich mit den regulären `CameraThread`-Signalen,
OpenCV-Frames und regulärem Stoppen/erneutem Start. Der Bearbeitungsdialog wurde
mit Qt offscreen gerendert und auf sichtbare Geräte-ID/Verbindungsfelder geprüft.

Für die Nutzung: Abhängigkeiten aktualisieren, WildCam neu starten und unter
Auto-Discover mit lokalem Benutzer/Gerätepasswort suchen; alternativ im Editor
Pfad `v380`, Port 8800 und Geräte-ID wählen. Beim Implementieren war die bisherige
WildCam-Instanz noch aktiv. Deren laufende Konfiguration wurde nicht überschrieben.

Temporäre Analysequellen, Medien und Sitzung liegen außerhalb des Repositorys unter
`/tmp/d57-analysis/`. Private Kamerabilder werden nicht als Testfixtures eingecheckt.

## Offene Grenzen

- Kein Audio; V380-PTZ ist für diese D57 bestätigt, weitere Modelle sind ungeprüft.
- Kein Nachweis für weitere Geräte-/Kommunikationsversionen.
- Gleichzeitige App-Nutzung, längerer Dauerbetrieb und Verhalten bei DHCP-Wechsel
  sind nicht empirisch geprüft.
- Aufzeichnung, Snapshots und Erkennung behalten das vollständige native Bild.
  Die beiden lokalen Ansichtsfenster sind keine nativen Einzelobjektivstreams.
- Physische PTZ-Bewegung wurde geprüft; Betrieb bei gesperrtem Internet bleibt ungeprüft.
- Kein Firmwareflash oder SD-Karten-Konfigurationstrick erforderlich.

## Protokollreferenzen

- [26medias: V380-Protokoll und Node-Referenz](https://github.com/26medias/V380-wifi-camera-reverse-engineering/blob/main/PROTOCOL.md):
  1167/1168, 301/401, 303 und partielle AES-Medienentschlüsselung. Dessen AC54
  liefert MJPEG; die D57 liefert nach eigener Prüfung HEVC.
- [prsyahmi: ältere C++-Implementierung](https://github.com/prsyahmi/v380/blob/master/v380/v380.cpp):
  ältere Loginstrukturen und PTZ-Ansatz; nicht unverändert übernommen.
- [FelixDaCraft: verwandter V308-Decoder](https://github.com/FelixDaCraft/xiaovv-v308-decoder):
  zusätzliche Referenz für Macrovideo/HEVC; keine eigenständige D57-Abnahme.

## Nachprüfung: getrennte Objektivstreams versus geteilte Darstellung

Der Nutzer weist auf getrennte Ansichten in V380 Pro hin. Der bisherige gemeinsame
HEVC-Stream belegt ausschließlich den verwendeten Standardzugang, nicht das Fehlen
weiterer Streamvarianten in der Kamera.

Zusätzliche gezielte LAN-Prüfung des im SDK bei Kommando 301 verwendeten
Play-Channel-Felds (u32 bei Offset 8):

| Play-Channel | Beobachtung an D57 |
| --- | --- |
| 0 | 15 Frames HEVC, 2304 × 2592; weiterhin beide Ansichten im selben Bild |
| 1 | Kamera schließt die Streamverbindung ohne vollständige 32-Byte-Antwort |
| 2 | Kamera schließt die Streamverbindung ohne vollständige 32-Byte-Antwort |

Diese Tests ändern nur die Live-Streamanfrage, keine gespeicherten Kameraoptionen.
Sie belegen keine getrennten Objektivstreams über dieses Feld. Das Feld darf
nicht ohne weiteren Nachweis als Objektivnummer im Editor angeboten werden.

Weitere statische SDK-Erkenntnisse aus der installierten App 2.2.92:

- `HSLiveDataBaseTransmitter::changeVsChn(int)` speichert einen Auswahlwert und
  setzt ein Änderungsflag (ARM64-Adressen 0x3e8b4–0x3e8c8).
- `HSLiveDataV3Transmitter::actionCtrlThreadFunc()` verarbeitet dieses Flag und
  erzeugt einen JSON-Eintrag `up.vsspec` (0x4fb5c–0x4fc38). Die benachbarte
  Qualitätsumschaltung ergänzt ebenfalls `vsspec`.
- Dieser V3-JSON-Pfad ist vom derzeit implementierten binären V2-Stream-Login
  zu unterscheiden. Seine Unterstützung durch die konkrete D57, gültige
  Auswahlwerte und die resultierende Übertragung sind noch nicht nachgewiesen.
- Die SDK-Funktion allein beweist weder zwei unabhängige Netzwerkstreams noch
  eine reine lokale Bildteilung in der App.

Eine Anfrage an den Nutzer zum Umschalten der App-Ansichten wurde gestellt.
Der auf dem Linux-Rechner versuchte gezielte Paketmitschnitt konnte wegen
fehlender Capture-Rechte (`CAP_NET_RAW`) nicht gestartet werden. Aus den gelesenen
App-Logs ergab sich keine verwertbare Video-Kanalzuordnung. Es liegt daher kein
Paketvergleich der App-Einzelansichten vor.

**Offen bleibt:** ob die App bei dieser D57 beide Ausschnitte lokal aus dem
zusammengesetzten Bild darstellt oder einen zusätzlichen Protokollweg für
getrennte Medien benutzt. Die bestehende Integration bleibt beim nachgewiesenen
Gesamtstream; eine Kanalwahl wurde nicht ohne funktionierenden Nachweis eingebaut.

### Vom Nutzer durchgeführte App-Umschaltung

Während des angekündigten Umschaltens wurden 50 Sekunden Logcat ausschließlich
für den V380-App-Prozess erfasst. Die Bildschirmaufnahme zeigt anschließend eine
große Objektivansicht und die andere als kleines Bild darin. Ein zeitgleicher
Socket-Schnappschuss zeigt zwei bestehende TCP-Verbindungen vom Handy zur D57
auf Port 8800. Ihre Nutzlasten konnten nicht mitgeschnitten werden; die Zahl
belegt keine zwei Videostreams (Steuer- und Medienverbindung sind ebenfalls
möglich).

Die App-Logs enthalten Meldungen des Software-HEVC-Decoders, jedoch keine
verwertbaren `vsspec`-/`changeVsChn`-Einträge oder Decoderauflösungen. Unterschiedliche
Decoder-Threadnummern können auch bei Neustarts desselben Players entstehen und
belegen keine gleichzeitig unabhängigen Streams. Die Umschaltung allein liefert
somit noch keinen eindeutigen Nachweis der Netzwerkaufteilung. Private Logs und
Bildschirmaufnahme bleiben unter `/tmp/d57-analysis/`, außerhalb des Repositorys.

## Gezielter vsspec-Versuch und ausgelesene Kanalmetadaten

Nach ausdrücklichem Auftrag wurde der neuere JSON-Pfad weiter aus ARM64-Code
und `classes9.dex` der installierten V380-Pro-App 2.2.92 rekonstruiert.

### Netzwerkversuche

Aus `initIotcReq`/`initCommonDataSendBuffer` wurden das Magic `0x38030818`,
der 16-Byte-Innenheader, die optionale 64-Byte-Hülle mit Kommando 1200 sowie
`method_id=0x30202` und `params.up.vsspec` abgeleitet. Die Versuche fanden
**innerhalb einer regulär mit den lokalen Zugangsdaten angemeldeten binären
Live-Sitzung** statt. Es wurden keine gespeicherten Kameraoptionen geändert.

Zunächst wurden unverschlüsselte JSON-Anfragen ohne und mit 1200-Hülle geprüft:
keine V3-Umschaltantwort, weiter Medienfragmente des bisherigen Formats. Danach
wurden die Werte 0 und 1 mit Hülle geprüft und ab dem jeweils nächsten Schlüsselbild
24 vollständige Bilder ausgewertet:

| vsspec | Bilder | HEVC-Nutzdaten | Auflösung und Inhalt |
| --- | --- | --- | --- |
| 0 | 24 | 365855 Byte | 2304 × 2592, beide Objektive übereinander |
| 1 | 24 | 368705 Byte | 2304 × 2592, beide Objektive übereinander |

Auflösung wurde mit `ffprobe` geprüft; je ein mit FFmpeg decodiertes Bild wurde
visuell kontrolliert. Keine Umschaltung auf ein einzelnes Objektiv festgestellt.
**Grenze:** Eine vollständige verschlüsselte V3-Sitzung einschließlich ihrer
separaten Sitzungsverhandlung wurde damit nicht hergestellt. Die Tests belegen
keine wirksame Annahme der JSON-Anfragen durch die D57 und schließen weitere
Firmwarefunktionen nicht grundsätzlich aus.

### Geräteangaben aus dem normalen Login

Die Java-Implementierung von `LoginHelper` ordnet in der 1168-Antwort zu:

- Byte 63 → `LoginHandle.setChannelNum()`; D57 meldet **1**.
- Byte 113 → `LoginHandle.setVideoSplicing()`; D57 meldet **7**.

Diese Werte wurden anschließend mit einer **frischen lokalen Anmeldung** bestätigt:
`deviceVersion=32`, `channelCount=1`, `videoSplicing=7`.

Zusätzliche statische Befunde:

- Java-Playerfelder `bDevSpliceDoulChannel`, `nVideoSplicing`, `nStreamVsChn`.
- `nStreamVsChn` wird mit 255 initialisiert; beim V3-Aufbau wird der Wert 255
  nicht als `vsspec` übertragen.
- Der Player wählt den V3-Transmitter über ein eigenes `protocolType`-Feld;
  dessen Auswahl folgt auf Java-Seite der Plattformkennung des Login-Handles.
  Die binäre Geräteversion 32 allein ist kein Beleg für die V3-Plattform.
- Der native Displayer ruft `panoViewSetVideoSplicing` und
  `panoViewSetIsNoSplice` auf. Die Java-Bildextraktion behandelt unter anderem
  Splicing-Wert 7 durch Zuschneiden eines zusammengesetzten Bitmaps auf eine
  halbe Bildhöhe. Dies belegt Bildteilungsfunktionen im SDK; es ersetzt keinen
  Mitschnitt des Live-Renderpfads dieser konkreten App-Sitzung.

### Schlussfolgerung für WildCam

Die D57 meldet über den nachgewiesenen LAN-Zugang **einen Videokanal mit
zusammengesetztem Bild**. Die getesteten JSON-Anfragen haben keine getrennten
Objektivstreams geliefert. Die Befunde sprechen für lokale Darstellung der beiden
Bildhälften durch die App. Eine native Einzelstream-Auswahl wird deshalb weiterhin
nicht als funktionierend angeboten. Die konkrete praktikable Erweiterung ist eine
WildCam-Ansichtsauswahl für obere und untere Bildhälfte (bei HD jeweils
2304 × 1296), vorzugsweise mit gemeinsamer Verbindung und gemeinsamem Decoder.
Diese Darstellungserweiterung wurde in diesem Untersuchungsdurchgang nicht
implementiert.

Private Analyseartefakte und Medien bleiben unter `/tmp/d57-analysis/` und werden
nicht ins Repository aufgenommen. Laufzeitcode und Kamerakonfiguration wurden
für diesen Versuch nicht geändert.

## D57-PTZ: implementiert und physisch geprüft

Die Nutzerzuordnung ist bestätigt: **oben feste Kamera, unten bewegliche Kamera**.
Die ursprüngliche Videoanbindung unterdrückte PTZ ausdrücklich, weil noch kein
V380-Backend vorhanden war. Dies wurde durch ein eigenes Backend ersetzt.

### Lokales Steuerpaket

Auf derselben angemeldeten TCP-8800-Videositzung werden 16 Byte gesendet:

| Offset | Typ | Inhalt |
| --- | --- | --- |
| 0 | u32 LE | Kommando 170 |
| 4, 6 | je u16 LE | 1000, 1000 |
| 8 | u16 LE | Pan: 1000 Stop, 1001 links, 1002 rechts |
| 10 | u16 LE | Tilt: 1000 Stop, 1003 hoch, 1004 runter |
| 12 | u16 LE | PTZ-Kanal 0 |
| 14 | u16 LE | Schrittparameter 1 |

PTZ-Kanal 0 bezeichnet hier die Motorsteuerung der unteren Kamera und ist nicht
mit einer separaten Objektiv-Streamnummer gleichzusetzen. Eine zusätzliche
Authentifizierungs-/Videoversorgung für Steuerbefehle wird nicht aufgebaut.

### Einbau und Lebenszyklus

- `V380Client.move_ptz()` sendet den Fahrbefehl. Ein unabhängiger Timer sendet
  nach **0,35 Sekunden** Stop, auch wenn das Qt-Loslassen ausbleibt.
- Ein Generationenzähler verhindert, dass ein alter Timer eine neuere Bewegung
  stoppt. Richtungsbefehle und Stop werden durch einen Schreiblock serialisiert.
- Loslassen/Stop-Taste sendet explizit Stop. Client-Schließen stoppt einen noch
  bewegten Motor vor dem Schließen des Videosockets.
- `V380PtzBackend` verwendet immer den aktuellen Live-Client des CameraThread.
  Beim Wechsel der Sitzung wird zunächst die alte Bewegung gestoppt.
- Das Schließen des PTZ-Controllers stoppt dessen aktiven Client. Motorbefehle
  laufen auf dem bestehenden PTZ-Worker, nicht auf dem GUI-Thread.
- Ohne laufenden Videostream wird eine verständliche Fehlermeldung ausgegeben.
- `config.py` migriert frühere `v380://`-Einträge mit Modell `D57` ohne vorhandenes
  PTZ-Backend auf `ptz=true`, `ptz_backend=v380`. Explizite manuelle Auswahl bleibt
  erhalten. Andere V380-Modelle werden nicht automatisch als beweglich markiert.
- Da die bisherige WildCam-Instanz noch läuft, wurde deren Konfigurationsdatei
  währenddessen nicht überschrieben. Die geprüfte Migration greift beim nächsten
  Neustart und wird dann über WildCams normale Konfigurationsspeicherung persistiert.

### Livebelege

Ein erster kurzer Rechts-/Links-Test über die bestehende Bridge bewegte nur die
untere Kamera. ORB/RANSAC-Bildregistrierung ergab nach dem Rechtsimpuls unten
etwa **−195 Pixel** horizontalen Versatz; oben etwa **0,08 Pixel**.

Danach wurde der vollständige Weg aus `CameraThread`, der durch
`MainWindow._ptz_controller()` erzeugten Backend-Verbindung und echten
`PtzPad`-Qt-Pfeiltasten geprüft. Zwei vertikale Impulse mit je 0,35 Sekunden
und ohne vorzeitiges Loslassen bestätigten den automatischen Stop. Nach dem
Runter-Impuls lag der vertikale Versatz unten bei etwa **−160 Pixeln**; die
Gegenbewegung führte wieder in Richtung Ausgangslage. Oben lag die Abweichung
bei **weniger als 0,05 Pixeln**. Beide Stopprüfungen erfolgreich, keine
Backendfehler, CameraThread regulär beendet.

Die ersten vertikalen Bildvergleiche erfolgten vor dem Leeren des Videostartpuffers
und zeigten die erste Bewegung noch nicht zuverlässig. Die erfolgreiche Wiederholung
wartete sechs Sekunden vor der ersten Bewegung und je 3,5 Sekunden bis zum
Bildvergleich. Daraus wird weder ein Richtungsfehler noch ein mechanischer
Endanschlag abgeleitet.

Alle **29 Offline-Tests** bestanden: zusätzlich unter anderem Richtungs-/Stoppakete,
Watchdog ohne Release, alte Timer, Schließen bei Bewegung, Sitzungswechsel,
Controller-Schließen, D57-Konfigurationsmigration und manuelles Deaktivieren.
Audio und eine native Einzelstream-Auswahl sind weiterhin nicht implementiert.

## Erneute native Streamprüfung am 16.11.2026

Auf erneuten Nutzerauftrag wurden acht frische lokale Live-Sitzungen geprüft.
Zusätzlich zur bisherigen Anmeldung wurden die drei im App-SDK gesetzten Bytes
an Offset 30, 31 und 32 der 301-Anfrage jeweils auf 1 gesetzt
(`HSLiveDataV2Transmitter::getDataFromDevice`, ARM64 0x46080,
0x46110–0x4611c). Das ist keine nachgewiesene Objektivauswahl, sondern prüft,
ob die bisher ausgelassenen SDK-Felder die Kanalwahl beeinflussen.
Play-Channel ist weiterhin u32 an Offset 8, Qualität u32 an Offset 26.

| Versuch | Ergebnis |
| --- | --- |
| Standardanmeldung, Kanal 0, HD | 24 decodierte HEVC-Bilder, 2304 × 2592, beide Objektive |
| Standardanmeldung, Kanal 0, SD | 24 decodierte HEVC-Bilder, 640 × 720, beide Objektive |
| Zusätzliche SDK-Felder, Kanal 0, HD | 24 decodierte HEVC-Bilder, 2304 × 2592, beide Objektive |
| Zusätzliche SDK-Felder, Kanal 0, SD | 24 decodierte HEVC-Bilder, 640 × 720, beide Objektive |
| Zusätzliche SDK-Felder, Kanal 1, HD | Kamera schließt Streamverbindung ohne Antwortbytes |
| Zusätzliche SDK-Felder, Kanal 2, HD | Kamera schließt Streamverbindung ohne Antwortbytes |
| Zusätzliche SDK-Felder, Kanal 1, SD | Kamera schließt Streamverbindung ohne Antwortbytes |
| Abschließender Kontrollstart, Standardanmeldung, Kanal 0, HD | Wieder 24 decodierte HEVC-Bilder, 2304 × 2592, beide Objektive |

Alle fünf erfolgreichen Aufzeichnungen wurden ab einem Schlüsselbild gespeichert,
mit `ffprobe -count_frames` vollständig decodiert (insgesamt 120 Bilder, keine
gemeldeten Decoderfehler) und anhand je eines mit FFmpeg erzeugten Vorschaubilds
visuell geprüft. HD und SD zeigen jeweils beide Objektive übereinander.
Alle acht Anmeldungen melden erneut `deviceVersion=32`, `channelCount=1`,
`videoSplicing=7`. Erfolgreiche Streamanmeldungen liefern Kommando 401,
Ergebnis 1001, 32 Byte.

**Ergebnis:** Auch mit den zusätzlichen SDK-Feldern und in SD ist keine native
Einzelobjektiv-Auswahl über den geprüften binären LAN-Zugang nachgewiesen.
Eine vollständige V3-Sitzung wurde auch in dieser Nachprüfung nicht hergestellt;
die früheren `vsspec`-Versuche wurden nicht erneut ausgeführt. Ungeprüfte
Protokollwege bleiben daher offen. Lokales Zuschneiden ist weiterhin die
nachgewiesen praktikable Lösung, nicht eine bewiesene Firmwarebeschränkung.

Es wurden keine gespeicherten Kameraeinstellungen geändert und keine
PTZ-Befehle gesendet. WildCams Laufzeitcode und Kamerakonfiguration blieben
unverändert. Das Prüfskript `recheck-native.py`, die maschinenlesbaren Ergebnisse
`recheck-native-results.json` und private Medien `recheck-*.hevc`/`recheck-*.png`
liegen ausschließlich unter `/tmp/d57-analysis/`; Zugangsdaten und Sitzungstickets
werden vom Prüfskript nicht ausgegeben.

## Lokale Bildaufteilung: zwei Fenster mit eigenem Zoom

`lens_view.py` stellt für V380-Kameras mit Modell `D57` zwei separate Fenster
bereit: oben fest, unten beweglich. Ein `CameraThread` mit einer Bridge und
einem Decoder versorgt beide Fenster; die Bildhälften werden erst nach dem
Decodieren ausgewählt. HD ergibt zweimal 2304 × 1296, SD zweimal 640 × 360.
Der Originalframe für Aufzeichnung, Snapshots und Erkennung bleibt unverändert.

Jedes Fenster besitzt eigenen Mausrad-/Tastenzoom und Rechteckauswahl.
Doppelklick oder „Ganzes Bild“ setzt nur dessen Zoom zurück. PTZ erscheint
ausschließlich unten und nutzt den bestehenden sitzungsgebundenen Controller.
Manuelles Deaktivieren von PTZ bleibt erhalten. Loslassen, Fokusverlust,
Ausblenden oder Schließen des unteren Fensters fordert Stop an; der bestehende
0,35-Sekunden-Watchdog bleibt wirksam.

Die Fenster öffnen beim Streamstart. Das Schließen eines Fensters stoppt weder
den gemeinsamen Stream noch das andere Fenster. Ein Klick auf die D57-Vorschau
öffnet geschlossene Fenster erneut. Streamstopp, Kamerawechsel im Editor,
Entfernen der Kamera und Anwendungsschließen räumen die Fenster auf.
Bei Verbindungsverlust werden alte Bilder entfernt und PTZ deaktiviert.

**Prüfung:** Alle 48 Offline-Tests bestanden, darunter 19 neue GUI-/Integrationstests
für Bildhälften, unabhängigen Zoom, Ausschnittkoordinaten, Auflösungswechsel,
Fensterlebenszyklus, gemeinsame Frame-Verteilung, PTZ-Zuordnung und Reconnect-Anzeige.
Ein zusätzlicher Offscreen-Durchlauf mit vollständigem `MainWindow` und
`CameraThread` decodierte 15 Bilder aus der vorher aufgenommenen D57-HEVC-Datei:
Quelle `(2592, 2304, 3)`, beide Fenster `(1296, 2304, 3)`, ein Kamerathread,
unabhängige Zoomausschnitte und Wiederöffnen ohne zweiten Thread. Die Fenster
wurden anhand von Screenshots visuell geprüft. PTZ-Tasten wurden dabei gegen
einen Mock-Controller geprüft, ohne Motorbewegung.

**Livegrenze:** Zwei neue Live-Durchläufe lieferten keine Bilder und meldeten
V380-Zeitüberschreitungen. Eine anschließende direkte Prüfung mit dem unveränderten
`V380Client` scheiterte bereits beim TCP-Verbindungsaufbau nach fünf Sekunden.
Die neue Fensterdarstellung ist daher nicht als erneut live abgenommen zu werten.
Prüfskript und private Screenshots liegen unter `/tmp/d57-analysis/`
(`test-local-split.py`, `local-split-windows.png`, `local-split-zoom.png`).
Die laufende WildCam-Instanz und ihre gespeicherte Kamerakonfiguration wurden
nicht verändert.

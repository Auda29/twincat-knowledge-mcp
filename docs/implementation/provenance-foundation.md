# Herkunfts- und Corpus-Manifestmodell (datenquellenneutral)

Diese Implementierung ist ausschließlich die validierende Modellgrundlage für
spätere Import- und Serving-Schritte. Sie importiert keine Dateien, fragt kein
Netz ab und enthält keine Beckhoff- oder TwinCAT-Werte.

## Modellgrenzen

- `SourceReference` ist ein Feldbeleg mit opaken `source_id`-/`snapshot_id`-
  Werten, Sprache (`de`/`en`), optionaler HTTP(S)-URL, sicherem relativem
  POSIX-Locator und exakt 64 hexadezimalen SHA-256-Zeichen.
- Locatorwerte sind auf 2.048 Zeichen begrenzt. Für die Sicherheitsprüfung wird
  percent-dekodiert, bis ein Fixpunkt erreicht ist, höchstens jedoch über acht
  Durchläufe. Wenn danach ein weiterer Decode-Durchlauf noch etwas ändern
  würde, wird der Locator strikt abgewiesen; verbleibende Encodings werden
  nicht still akzeptiert. Die Eingaberepräsentation bleibt im Modell erhalten.
- Die Prüfung auf Steuerzeichen (`U+0000`–`U+001F`, `U+007F`) erfolgt vor und
  nach dem vollständigen bounded Decode. Danach werden absolute Pfade,
  Backslashes, Laufwerks-/URI-Präfixe und `.`/`..`-Segmente abgewiesen.
- `:` ist in jedem dekodierten Pfadsegment verboten, damit Windows-ADS nicht
  nur im ersten Segment erkannt werden. Pro Segment werden außerdem
  `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9` und `LPT1`–`LPT9` case-insensitiv
  abgewiesen, auch mit Extension oder abschließenden Punkten/Leerzeichen.
- `SourceSnapshot` bewahrt unbekannte dokumentierte Versionen ausdrücklich als
  `documented_version=None` mit `applicability="unknown"`. Eine bekannte
  Gültigkeit ohne belegte Version ist ungültig.
- `InventoryBalance` erzwingt die Bilanz
  `total = imported + skipped + failed`; Zähler und begrenzte Eingaben sind
  strikt und nicht negativ.
- `CorpusManifest` verlangt eine Schema-, Corpus-Snapshot- und Erstellungs-
  identität sowie mindestens eine Quelle und weist doppelte Snapshot-IDs ab.
  Optionale Toolchain-/Entity-Metadaten bleiben abwesend, wenn sie nicht
  belegt sind; sie werden nicht erfunden.
- Alle Modelle lehnen unbekannte Felder ab und validieren strikt ohne
  stillschweigende Typkoerzierung.

Die Unit-Tests verwenden ausschließlich synthetische, als solche erkennbare
Metadaten und Hashes. Sie sind kein Nachweis für reale Corpus-Abdeckung, einen
InfoSys-Importer, Rechtefreigaben oder einen Server.

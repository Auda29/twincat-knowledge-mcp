# Herkunfts- und Corpus-Manifestmodell (datenquellenneutral)

Diese Implementierung ist ausschließlich die validierende Modellgrundlage für
spätere Import- und Serving-Schritte. Sie importiert keine Dateien, fragt kein
Netz ab und enthält keine Beckhoff- oder TwinCAT-Werte.

## Modellgrenzen

- `SourceReference` ist ein Feldbeleg mit opaken `source_id`-/`snapshot_id`-
  Werten, Sprache (`de`/`en`), optionaler HTTP(S)-URL, sicherem relativem
  POSIX-Locator und exakt 64 hexadezimalen SHA-256-Zeichen.
- Locatorwerte dürfen keine absoluten POSIX-Pfade, UNC-/Windows-Pfade,
  Laufwerkspräfixe, URI-Schemata oder Traversalsegmente enthalten. Auch
  percent-kodierte Traversale wird abgewiesen.
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

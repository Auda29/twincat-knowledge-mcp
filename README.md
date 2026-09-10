# TwinCAT Knowledge MCP

**Status: Planung — noch kein installierbarer MCP-Server.**

Projektunabhängige, lokale Wissensschnittstelle für globale Beckhoff- und TwinCAT-Informationen. Ziel ist ein vollständig installierbarer Read-only-Server nach **MCP `2026-07-28`**, der Quellen, Bibliotheken, Symbole, Hardwareinformationen und Beispiele strukturiert für Agenten bereitstellt.

## Dokumentation

- [Vollständiger Umsetzungsplan](docs/PLAN.md): Architektur, Tool-Verträge, Installation, Sicherheit, TDD-Phasen und Release-Abnahme.
- [Quellen](docs/SOURCES.md): bei der Planung herangezogene Primärdokumentation.

## Geplante 15 Agent-Tools

| Bereich | Tools |
|---|---|
| Dokumentation | `tc_search`, `tc_get_topic`, `tc_browse_topics` |
| Symbole | `tc_find_symbols`, `tc_get_symbol`, `tc_compare_symbols` |
| Bibliotheken | `tc_find_libraries`, `tc_get_library` |
| Hardware | `tc_find_devices`, `tc_get_device` |
| Fehlerreferenzen | `tc_lookup_error` |
| Beispiele | `tc_search_examples`, `tc_get_example` |
| Beziehungen | `tc_get_related` |
| Bestand und Abdeckung | `tc_get_corpus_status` |

## Geplante technische Basis

- Python, offizielles MCP Python SDK v2, SQLite/FTS5 und BM25.
- stdio für lokale Agenten; optional abgesichertes Streamable HTTP.
- Installation auf Windows und Linux ohne TwinCAT-Abhängigkeit des Servers.
- Versionierte Wissenspakete mit Quellenbelegen, Coverage-Berichten und Rollback.
- Semantische Suche optional und erst nach gemessenem Bedarf.

## Grenzen

Kein Projektzugriff als Voraussetzung, keine ADS-/SPS-Verbindung, keine Engineering-Aktionen und keine Codeausführung durch Agent-Tools. Beckhoff-Dokumentation wird nicht mit diesem Repository verteilt. Bezugs-, Indexierungs- und Nutzungsrechte müssen vor dem Import geklärt werden.

Dies ist ein eigenständiges Vorhaben, kein als offiziell ausgewiesenes Beckhoff-Produkt. Softwarelizenz und eine etwaige öffentliche Veröffentlichung sind noch zu entscheiden.

## Nächster Schritt

Nach Freigabe der Umsetzung: reale Datenquelle und Nutzungsrechte klären, Importformat praktisch prüfen und einen modernen MCP-Roundtrip mit dem festgelegten SDK nachweisen. Erst danach die erste installierbare vertikale Funktion implementieren.

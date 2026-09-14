# Umsetzungsziel: TwinCAT Knowledge MCP mit Agent-Swarm

> **Aktuelle Merge-Regel (14.09.2026):** [MERGE_POLICY.md](MERGE_POLICY.md)
> ersetzt die frühere Upload-Pflicht für Entwicklungs-PRs. Code-, Build-,
> Installationsprüfungen und unabhängige Review bleiben verpflichtend.
> Alte Quoten-/Auslieferungsbefunde sind historische Nachweise, keine aktuellen
> Merge-Voraussetzungen. Produkt-/Release-Abnahme und Feature-Pause bleiben erhalten.

## Status

**Browse-Etappe teilabgeschlossen: Code unabhängig abgenommen, CI-Auslieferung extern blockiert. Sämtliche Feature-Umsetzung ist wieder pausiert.** Aktuell gilt der begrenzte Konsolidierungsauftrag in [CONSOLIDATION.md](CONSOLIDATION.md); der belegte Stand steht in [STATUS.md](STATUS.md). Nach der Browse-Abnahme nicht automatisch mit neuen Features fortfahren. Die folgenden Produktanforderungen und Abnahmegrenzen bleiben unverändert verbindlich.

Vom Nutzer beauftragtes Umsetzungsziel. Dieser Vertrag ist im Repository hinterlegt; allein das Schreiben dieser Datei aktiviert keinen nativen Hermes-Goal-Loop. Der Loop und die Subagent-Modellkonfiguration müssen in der ausführenden Hermes-Session aktiviert und geprüft werden.

## Outcome

Den vollständigen Plan `docs/PLAN.md` in `Auda29/twincat-knowledge-mcp` inkrementell mit einem koordinierten Agent-Swarm umsetzen: installierbarer, projektunabhängiger Beckhoff-/TwinCAT-Knowledge-MCP nach `2026-07-28` mit den 15 festgelegten Read-only-Tools. Die Definition of Done in Abschnitt 15 des Plans ist verbindlich.

**Abgeschlossener Implementierungsumfang (Auslieferung bleibt blockiert):** Den vorhandenen Domain-Browse-Service `TopicQueryService.browse_topics` auf `swarm/topic-browse-service` fertigstellen: zwei Medium-Reviewbefunde schließen, dauerhafte Regressionen ergänzen und unabhängig am exakten gemeinsamen Stand prüfen. Zunächst keine neue MCP-Anbindung: `tc_browse_topics` ist ein geplantes Tool, kein bereits exponiertes Werkzeug. Die bestehenden drei MCP-Tools und ihre installierten stdio-/Snapshot-Lifecycle-Tests bleiben erhalten.

Abnahme dieser Etappe: Python 3.12.10/3.13.12, Ruff check/format, `mypy src`, Wheel/sdist aus fremdem CWD, Windows/Linux und unabhängige Review auf der konsolidierten Basis. Erforderliche CI einschließlich Artefaktupload bleibt Merge-Gate; ein externer Quotenblocker verhindert nicht diese lokale Arbeit, aber vollständige Auslieferungsabnahme und Main-Merge. Anschließend stoppen; weder HTTP noch andere Features automatisch beginnen, auch nicht nach Quotenfreigabe.

## Verifikation

- Reale Tests, Build und Installation aus dem erzeugten Wheel, nicht nur aus einem editierbaren Checkout.
- Moderne MCP-Wire-Tests ohne erforderliches `initialize`, getrennt für stdio und Streamable HTTP; gegebenenfalls Legacy separat.
- Genau die 15 geplanten Tools mit validierten Verträgen, Herkunftsnachweisen und Negativfällen.
- Sichere Parser, Auth-/Origin-/Host-Grenzen, Paketvalidierung und Snapshot-Rollback.
- Reale freigegebene InfoSys-/Hardwarequelle und dokumentierte Coverage; synthetische Fixtures allein erfüllen keine reale Fachabnahme.
- Windows-/Linux- sowie beworbene Hosttests mit Versions- und Ergebnisnachweis.
- Evaluation und Release-Abnahme gemäß Plan; übersprungene oder blockierte Tests bleiben offen.
- Koordinator prüft integrierten Commit selbst und verifiziert Remote-Refs, PRs und ausgelieferte Artefakte durch Readback.

## Swarm und Modellbudget

- Koordinator zerlegt den Plan in abhängigkeitsgeordnete, kleine Arbeitspakete und führt Integration sowie Abnahme durch.
- Subagents verwenden ein leichteres Modell, bevorzugt GPT Luna, sofern unter dem konfigurierten Provider tatsächlich verfügbar. Modell-ID nicht aus dem Anzeigenamen erraten.
- Vor dem ersten Swarm die tatsächlich aufgelöste Provider-/Modellkonfiguration prüfen. Ohne bestätigtes leichtes Modell nicht still das Elternmodell erben; Nutzer um Konfiguration bitten.
- Für diese Etappe maximal ein Implementierungsworker und ein unabhängiger Reviewer; keine rekursive Delegation. Ressourcen vor Builds prüfen, schwere Tests/Builds unter dem gemeinsamen Lock serialisieren.
- Getrennte Worktrees und eindeutige Dateiverantwortung. Gemeinsame Paket-, Schema- und CI-Dateien haben genau einen zuständigen Integrator.
- Jeder Worker erhält relevante Planabschnitte, konkrete Ein-/Ausgabeverträge, Dateigrenzen, Tests und Stop-Bedingungen.
- Kleine TDD-Schritte: RED nachweisen, minimal implementieren, GREEN nachweisen, erst dann refaktorieren.
- Nach jedem Arbeitspaket: Commit/Worktree, tatsächliche Befehle, Exitcodes, geänderte Dateien und Einschränkungen liefern. Unabhängige Review am unveränderlichen Commit.
- Teureres Modell für einzelne Worker nur nach ausdrücklicher Freigabe; nicht automatisch eskalieren.

## Grenzen

- Scope: Repository `Auda29/twincat-knowledge-mcp`, zugehörige isolierte Worktrees und Testumgebungen.
- Repository bleibt privat. Keine öffentliche Registry oder öffentliche Releases.
- Kein Projektfokus als Voraussetzung, kein ADS-/SPS-Schreibzugriff und keine Engineering-Aktionen.
- Bring your own documentation: Ausgeliefert wird nur MCP-Software; Nutzer beschaffen und stellen InfoSys-/ESI-Dokumentation selbst bereit. Keine Weiterverteilung von Beckhoff-Dokumentation oder daraus erzeugten Wissenspaketen/Suchindizes durch das Projekt.
- Keine Beckhoff-Volltexte, privaten Wissenspakete oder Secrets in Git/Software-Releases.
- Nutzungsbedingungen für konkrete lokale Verarbeitung und mögliche Auszugübertragung an externe Modellanbieter getrennt prüfen; keine pauschale Forderung nach schriftlicher Herstellerfreigabe für jede lokale Nutzung. Eine reale, vom Betreiber bereitgestellte und für den Testzweck nutzbare Stichprobe bleibt für Import-/Fachabnahme erforderlich.
- Keine Sicherheitsgrenze abschwächen, Tests entfernen oder Abnahmeziele verkleinern, um grüne Ergebnisse zu erhalten.
- Implementierungsarbeit auf `swarm/*`-Branches mit reviewbaren PRs. Der Nutzer hat den Koordinator beauftragt, PRs nach unabhängiger Review, Behebung aller Merge-Blocker und verifizierter grüner CI am finalen Stand selbstständig nach `main` zusammenzuführen; keine zusätzliche Nutzerfreigaberunde. Keine Admin-Umgehung oder Abschwächung von Prüfungen. Ein Grundlagen-Merge ist keine vollständige Produktabnahme; offene PLAN-Gates bleiben offen. Release-Veröffentlichungen benötigen weiterhin gesonderte Freigabe; lokale Artefakte dürfen gebaut und getestet werden.
- Keine Änderungen an anderen Hermes-Profilen. Eine profilweite Modellumstellung betrifft auch weitere Delegationen und ist entsprechend sichtbar zu machen.

## Stop-Bedingungen

Bei fehlendem Modellzugang, ungeklärten Nutzungsrechten, nicht zugänglichen realen Quellen, fehlender notwendiger Plattform/Hostumgebung oder erforderlicher zusätzlicher Veröffentlichungserlaubnis den betroffenen Schritt als blockiert dokumentieren und gezielt nachfragen. Unabhängige sichere Arbeit darf weitergehen, sofern sie kein Gate des Plans umgeht. Ein gestoppter Goal-Loop bedeutet nicht, dass das Produkt vollständig abgenommen ist.

## Aktivierung in Hermes

Offizieller Mechanismus: `/goal` setzt ein sessiongebundenes persistentes Ziel; `delegation.model` und `delegation.provider` legen das Worker-Modell fest. Siehe:

- https://hermes-agent.nousresearch.com/docs/user-guide/features/goals
- https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation

Nachdem das leichte Worker-Modell konfiguriert und überprüft wurde, in der Repo-Session senden:

```text
/goal Stelle ausschließlich den vorhandenen Domain-Browse-Service in /home/hermes/workspace/-twincat-knowledge-mcp gemäß docs/GOAL.md fertig und prüfe ihn auf der konsolidierten Basis.
verify: Beide Reviewbefunde geschlossen; dauerhafte Regressionen; Python 3.12.10/3.13.12, Ruff, mypy src, installierte Wheel-/sdist- und Snapshot-Lifecycle-Tests, Windows/Linux sowie unabhängige Review. CI-Auslieferung separat nachweisen; blockierte Kriterien bleiben offen. Alle Produktgates aus docs/PLAN.md bleiben verbindlich.
constraints: Leichtes verifiziertes Subagent-Modell, bevorzugt GPT Luna; maximal ein Implementierungsworker und ein unabhängiger Reviewer; TDD, getrennte Worktrees, schwere Prüfungen serialisieren. Repo privat, keine SPS-Aktionen oder Weitergabe unfreigegebener Beckhoff-Daten. Keine neue MCP-Anbindung, kein HTTP oder anderes Feature.
boundaries: Nur Auda29/twincat-knowledge-mcp und zugehörige isolierte Tests/Worktrees; Implementierung über swarm/*-Branches und PRs; selbstständiger Merge erst nach unabhängiger Review und grüner CI, kein autonomes Release.
stop when: Die Browse-Etappe abgeschlossen ist oder ihre verbleibende Abnahme extern blockiert ist. Sichere unabhängige Browse-Arbeit zuvor abschließen. Blocker konkret benennen; kein Produkterfolg und keine automatische Fortsetzung des Gesamtplans.
```

Anschließend mit `/goal show` den tatsächlich aktiven Vertrag prüfen. Keine Behauptung eines gestarteten Swarms ohne echte Delegations-Handles und bestätigte Modellwahl.

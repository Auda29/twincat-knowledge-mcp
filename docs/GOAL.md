# Umsetzungsziel: TwinCAT Knowledge MCP mit Agent-Swarm

## Status

Vom Nutzer beauftragtes Umsetzungsziel. Dieser Vertrag ist im Repository hinterlegt; allein das Schreiben dieser Datei aktiviert keinen nativen Hermes-Goal-Loop. Der Loop und die Subagent-Modellkonfiguration müssen in der ausführenden Hermes-Session aktiviert und geprüft werden.

## Outcome

Den vollständigen Plan `docs/PLAN.md` in `Auda29/-twincat-knowledge-mcp` inkrementell mit einem koordinierten Agent-Swarm umsetzen: installierbarer, projektunabhängiger Beckhoff-/TwinCAT-Knowledge-MCP nach `2026-07-28` mit den 15 festgelegten Read-only-Tools. Die Definition of Done in Abschnitt 15 des Plans ist verbindlich.

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
- Zunächst maximal drei parallele Worker; keine rekursive Delegation. Ressourcen vor Builds prüfen, speicherintensive Tests/Builds nötigenfalls serialisieren.
- Getrennte Worktrees und eindeutige Dateiverantwortung. Gemeinsame Paket-, Schema- und CI-Dateien haben genau einen zuständigen Integrator.
- Jeder Worker erhält relevante Planabschnitte, konkrete Ein-/Ausgabeverträge, Dateigrenzen, Tests und Stop-Bedingungen.
- Kleine TDD-Schritte: RED nachweisen, minimal implementieren, GREEN nachweisen, erst dann refaktorieren.
- Nach jedem Arbeitspaket: Commit/Worktree, tatsächliche Befehle, Exitcodes, geänderte Dateien und Einschränkungen liefern. Unabhängige Review am unveränderlichen Commit.
- Teureres Modell für einzelne Worker nur nach ausdrücklicher Freigabe; nicht automatisch eskalieren.

## Grenzen

- Scope: Repository `Auda29/-twincat-knowledge-mcp`, zugehörige isolierte Worktrees und Testumgebungen.
- Repository bleibt privat. Keine öffentliche Registry oder öffentliche Releases.
- Kein Projektfokus als Voraussetzung, kein ADS-/SPS-Schreibzugriff und keine Engineering-Aktionen.
- Keine Beckhoff-Volltexte, privaten Wissenspakete oder Secrets in Git/Software-Releases.
- Keine Sicherheitsgrenze abschwächen, Tests entfernen oder Abnahmeziele verkleinern, um grüne Ergebnisse zu erhalten.
- Implementierungsarbeit auf `swarm/*`-Branches mit reviewbaren PRs; keine automatische Zusammenführung nach `main` oder Release-Veröffentlichung ohne gesonderte Freigabe. Lokale Release-Artefakte dürfen gebaut und getestet werden.
- Keine Änderungen an anderen Hermes-Profilen. Eine profilweite Modellumstellung betrifft auch weitere Delegationen und ist entsprechend sichtbar zu machen.

## Stop-Bedingungen

Bei fehlendem Modellzugang, ungeklärten Nutzungsrechten, nicht zugänglichen realen Quellen, fehlender notwendiger Plattform/Hostumgebung oder erforderlicher zusätzlicher Veröffentlichungserlaubnis den betroffenen Schritt als blockiert dokumentieren und gezielt nachfragen. Unabhängige sichere Arbeit darf weitergehen, sofern sie kein Gate des Plans umgeht. Ein gestoppter Goal-Loop bedeutet nicht, dass das Produkt vollständig abgenommen ist.

## Aktivierung in Hermes

Offizieller Mechanismus: `/goal` setzt ein sessiongebundenes persistentes Ziel; `delegation.model` und `delegation.provider` legen das Worker-Modell fest. Siehe:

- https://hermes-agent.nousresearch.com/docs/user-guide/features/goals
- https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation

Nachdem das leichte Worker-Modell konfiguriert und überprüft wurde, in der Repo-Session senden:

```text
/goal Setze docs/PLAN.md in /home/hermes/workspace/-twincat-knowledge-mcp vollständig mit einem Agent-Swarm gemäß docs/GOAL.md um.
verify: Erfülle jede Definition-of-Done-Bedingung aus docs/PLAN.md mit echten Tests, Installations-/MCP-/Hostnachweisen und verifizierten Artefakten. Blockierte oder übersprungene Kriterien bleiben offen.
constraints: Leichtes verifiziertes Subagent-Modell, bevorzugt GPT Luna; maximal drei parallele Worker; TDD, getrennte Worktrees, unabhängige Review. Repo privat, keine SPS-Aktionen oder Weitergabe unfreigegebener Beckhoff-Daten.
boundaries: Nur Auda29/-twincat-knowledge-mcp und zugehörige isolierte Tests/Worktrees; Implementierung über swarm/*-Branches und PRs, kein autonomer Merge oder Release.
stop when: Modellzugang, Datenfreigabe, notwendige Plattformtests oder zusätzliche Berechtigungen fehlen. Blocker konkret benennen, nicht als Produkterfolg melden.
```

Anschließend mit `/goal show` den tatsächlich aktiven Vertrag prüfen. Keine Behauptung eines gestarteten Swarms ohne echte Delegations-Handles und bestätigte Modellwahl.

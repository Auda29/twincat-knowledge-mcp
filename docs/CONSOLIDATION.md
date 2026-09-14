# Konsolidierungsauftrag — aktiver Arbeitsmodus

> **Aktuelle Regel vom 14.09.2026:** [MERGE_POLICY.md](MERGE_POLICY.md)
> ersetzt die nachfolgend historisch dokumentierte Upload-Pflicht. Für
> Entwicklungsmerges bleiben Tests, Paketbau, Installation und Review Pflicht;
> die Paketablage ist nur bei ausdrücklichem Auslieferungsauftrag erforderlich.

Der aktuelle Auftrag ist die Integration der vorhandenen PRs #3–#18 nach `main`,
danach die nachweisgebundene Remote-Branchbereinigung. Keine neue Featurearbeit.
Die historische Domain-Browse-Etappe ist implementiert und komponentenbezogen
reviewt; ihre tatsächliche Main-Integration bleibt ein eigener Schritt. Die
Sicherungs-, Review- und Merge-Grenzen gelten weiter; keine Abnahmebedingung aus
`PLAN.md` wird dadurch als erfüllt erklärt.

## Reihenfolge

1. Alle lokalen/Remote-Refs, Worktrees, detached Stände und uncommittierten Änderungen inventarisieren, sichern und Wiederherstellung prüfen.
2. Browse-WIP separat erhalten, offene Tests und Befunde ausdrücklich markieren.
3. Geprüfte Komponenten mit unveränderter History in einer gemeinsamen Entwicklungsbasis prüfen; keine Sammel-Squashes oder unkontrollierten PR-Merges.
4. `docs/STATUS.md` führt Komponenten, exakte PR-Spitzen, Abhängigkeiten, historische Review-/Testnachweise, Integrationsstand und nächste Schritte.
5. Finalen gemeinsamen Stand auf Python 3.12.10/3.13.12, Windows/Linux, Ruff, mypy src, Wheel/sdist sowie installiertem stdio-/Snapshot-Lifecycle prüfen. Unabhängige Review erforderlich.
6. Main-Merges nur nach grüner erforderlicher CI und geschlossenen komponentenbezogenen Reviewbefunden. Normale Entwicklungs-CI verzichtet gemäß `MERGE_POLICY.md` auf Paketupload; ausdrücklich angeforderte Auslieferung bleibt fail-closed.
7. Remote-Branches nur nach verifizierter Integration in `main`, erfolgreicher finaler CI und Prüfung aller Folge-PRs löschen. Archivierung allein ersetzt keinen Integrationsnachweis. Keine pauschale lokale Worktree-/Dateilöschung.

## Grenzen und Abschluss

- Privat, software-only BYOD; keine Vendor-Inhalte, keine Releases, keine Engineering-Aktionen.
- Kein kostenpflichtiger Konto-Eingriff und keine Löschung von Artefakten fremder Repositories ohne ausdrückliche Freigabe.
- Vor Delegation leichtes Modell verifizieren, maximal ein Implementierungsworker plus ein unabhängiger Reviewer. Schwere Prüfungen serialisieren.
- Keine Sicherheits- oder Testabschwächung. Abnahme, Merge, Artefaktlieferung und Produkterfolg bleiben getrennte Aussagen.
- Bei externer Sperre nur Teilabschluss mit konkretem Entscheidungsbedarf melden. Unabhängige sichere Aufräumarbeit abschließen.
- Danach stoppen. Das ursprüngliche Feature-Goal nicht automatisch wieder aufnehmen.

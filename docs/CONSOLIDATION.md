# Konsolidierungsauftrag — aktiver Arbeitsmodus

Die Konsolidierung ist mit externem CI-Auslieferungsblocker teilabgeschlossen. Der Nutzer hat anschließend ausschließlich die Fertigstellung und Abnahme des vorhandenen Domain-Browse-Service freigegeben; der aktuelle Umfang steht in `GOAL.md`. Der übrige Feature-Ausbau bleibt pausiert. Die folgenden Sicherungs-, Review- und Merge-Grenzen gelten weiter; keine Abnahmebedingung in `PLAN.md` wird ersetzt.

## Reihenfolge

1. Alle lokalen/Remote-Refs, Worktrees, detached Stände und uncommittierten Änderungen inventarisieren, sichern und Wiederherstellung prüfen.
2. Browse-WIP separat erhalten, offene Tests und Befunde ausdrücklich markieren.
3. Geprüfte Komponenten mit unveränderter History in einer gemeinsamen Entwicklungsbasis prüfen; keine Sammel-Squashes oder unkontrollierten PR-Merges.
4. `docs/STATUS.md` führt Komponenten, exakte PR-Spitzen, Abhängigkeiten, historische Review-/Testnachweise, Integrationsstand und nächste Schritte.
5. Finalen gemeinsamen Stand auf Python 3.12.10/3.13.12, Windows/Linux, Ruff, mypy src, Wheel/sdist sowie installiertem stdio-/Snapshot-Lifecycle prüfen. Unabhängige Review erforderlich.
6. Main-Merges nur nach grüner erforderlicher CI und geschlossenen komponentenbezogenen Reviewbefunden. Die Artefakt-Auslieferung ist kein optionaler Check.
7. Nur belegbar integrierte oder überprüfbar archivierte Worktrees/Branches bereinigen. Offene PRs nicht schließen, um Arbeit zu verstecken.

## Grenzen und Abschluss

- Privat, software-only BYOD; keine Vendor-Inhalte, keine Releases, keine Engineering-Aktionen.
- Kein kostenpflichtiger Konto-Eingriff und keine Löschung von Artefakten fremder Repositories ohne ausdrückliche Freigabe.
- Vor Delegation leichtes Modell verifizieren, maximal ein Implementierungsworker plus ein unabhängiger Reviewer. Schwere Prüfungen serialisieren.
- Keine Sicherheits- oder Testabschwächung. Abnahme, Merge, Artefaktlieferung und Produkterfolg bleiben getrennte Aussagen.
- Bei externer Sperre nur Teilabschluss mit konkretem Entscheidungsbedarf melden. Unabhängige sichere Aufräumarbeit abschließen.
- Danach stoppen. Das ursprüngliche Feature-Goal nicht automatisch wieder aufnehmen.

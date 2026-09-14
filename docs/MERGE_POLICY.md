# Merge-Regel und Integrationsreihenfolge ohne verpflichtende Paketablage

## Autorisierte Änderung vom 14. September 2026

Der Nutzer hat den verpflichtenden Actions-Artefaktupload für gewöhnliche
Entwicklungs-PRs ausdrücklich aufgehoben. Diese Regel ersetzt ausschließlich
ältere Aussagen in GOAL, STATUS, CONSOLIDATION und PR-Beschreibungen, nach denen
eine erfolgreiche CI-Paketablage Voraussetzung für jeden Main-Merge war.
Historische Quotenfehler und frühere Test-/Reviewnachweise bleiben historische
Fakten; sie werden nicht nachträglich als grüne CI oder Auslieferung umgedeutet.

## Verpflichtende Entwicklungsprüfung

- Windows und Linux, jeweils die auf dem Branch vorgesehenen Python-Versionen.
- Gesperrte Abhängigkeiten, Lint, Formatierung, Typprüfung und Dependency-Check.
- Vollständige branchbezogene Tests einschließlich vorhandener echter
  Wheel-/sdist-Installations-, Foreign-CWD- und stdio-/Snapshot-Lifecycle-Tests.
- Wheel und sdist bauen sowie SHA-256-Datei auf dem Runner erzeugen.
- Aktuelle CI am zu integrierenden Stand und unabhängige Reviewbindung; neue
  Befunde schließen. Keine Admin-Umgehung, kein `continue-on-error`.

Push-/PR-Läufe und manuelle Läufe ohne Opt-in laden keine Pakete hoch. Damit
benötigen diese Läufe keine Actions-Artefaktspeicherquote. Runner-Verfügbarkeit,
Actions-Minuten und sonstige Kontobudgets sind davon nicht ausgenommen.

## Paketbereitstellung bleibt getrennt

Der vorhandene Upload wird nur bei `workflow_dispatch` mit dem typisierten
Boolean `upload_packages: true` ausgeführt (Standard: false). Namen, Pfade,
Prüfsummen, sieben Tage Aufbewahrung und `if-no-files-found: error` bleiben
unverändert. Ein ausdrücklich angeforderter Upload muss erfolgreich sein;
Fehler werden nicht ignoriert. Ein optionaler Auslieferungslauf ersetzt keine
Entwicklungsprüfung. Die manuelle Eingabe steht auf dem Default-Branch erst zur
Verfügung, nachdem die Workflow-Änderung dort integriert wurde.

Vor Download-/Auslieferungsabnahmen müssen die Pakete tatsächlich verfügbar
sein und heruntergeladen/hashgeprüft werden. Keine Release- oder Produktabnahme
wird durch das Auslassen der Ablage erfüllt. Keine automatische Veröffentlichung.
Software-only/BYOD, Rechte- und Sicherheitsgrenzen bleiben unverändert.

Inventur vor dieser Änderung: Kein Workflow auf den 17 bestehenden
Entwicklungsbranches lädt diese Foundation-Artefakte herunter; kein vorhandener
`download-artifact`-/`gh run download`-Verbraucher wird durch den Standard false
unterbrochen. Spätere neue Verbraucher müssen ausdrücklich Opt-in verlangen.

## Neue Integrationsreihenfolge

0. Diese CI-Regel als kleinen separaten Commit auf die vorhandenen PR-Heads
   übernehmen, ohne Produktcode oder History umzuschreiben. Push-CI frisch
   abwarten; alte Run-Reruns verwenden weiterhin die alte Workflow-Version.
   `main` lädt derzeit ohnehin keine Foundation-Pakete hoch. Die Regel gelangt
   mit dem ersten regulär geprüften Feature-Merge dorthin.
1. #3 -> #4 -> #5 -> #6 -> #7 -> #8 -> #9 nach main integrieren.
2. #10, danach #11 -> #12. #12 verbindet auch die Validierungs-CLI aus #10.
3. #13 -> #14 -> #15. #15 integriert auch die Betreiberfunktionen aus #12.
4. #16 -> #17 auf Basis des integrierten Adapters.
5. `swarm/consolidation` mit dem erreichten main vergleichen. Noch fehlende
   Integrationskorrekturen und Dokumentation in einem eigenen kleinen PR prüfen
   und übernehmen; keine ungeprüfte Sammelintegration.
6. #18 auf die vollständige integrierte Basis ausrichten, Reviewbindung und CI
   prüfen, dann nach main integrieren. Domain-Browse ist keine neue MCP-Anbindung.
7. Abschließende Windows-/Linux-, installierte Paket- und bestehende
   stdio-/Snapshot-Verifikation am tatsächlichen main. Nur danach erledigte
   Remote-Branches entfernen und Statusregister aktualisieren.

Für jeden Merge: Basis/Head aktuell prüfen, Folge-PRs gezielt auf main ausrichten,
bei Integration neuer Basisänderungen Tests erneut ausführen, Review des
Produktcodes plus Policy-/Integrationsdelta nachvollziehen. Normale Merge-Commits
bevorzugen, um die gestapelte Historie zu erhalten. Konflikte nicht pauschal mit
`ours`/`theirs` lösen. Branches erst löschen, wenn deren Inhalte in main sind und
keine offenen Folge-PRs mehr darauf zielen. Keine PR nur zur Zählerbereinigung
schließen. Keine unabhängige Review oder vollständige Produktabnahme durch
bloßes Bestehen dieser Policy-Tests behaupten.

## Umfang dieses Auftrags

CI-Entkopplung und Festlegung der Reihenfolge; keine automatische Durchführung
aller Feature-Merges, kein Wiederanlauf des pausierten Feature-Goals. Historische
Review-SHAs beziehen sich auf den alten Stand. Nach dem Policy-Commit bleibt die
Produktcode-Identität prüfbar; neue CI und Prüfung des CI-/Dokumentationsdeltas
sind vor einem Merge erforderlich.

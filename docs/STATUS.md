# Projektstatus — Integrationscheckpoint vor Domain-Browse

## Aktueller Auftrag vom 14. September 2026

Die vorhandenen PRs #3–#18 werden abhängigkeitsgeordnet nach `main` integriert;
anschließend werden nur nachweislich integrierte Remote-Branches entfernt.
Keine neue Produktentwicklung und kein Release. [MERGE_POLICY.md](MERGE_POLICY.md)
ist maßgeblich; normale Entwicklungs-CI benötigt keinen Artefaktupload.

Dieser Dateistand enthält die Komponenten #3–#17 einschließlich der gemeinsamen
Snapshot-/stdio-/Hierarchie-Tests. Domain-Browse aus [#18](https://github.com/Auda29/twincat-knowledge-mcp/pull/18)
ist der nächste getrennte Integrationsschritt. Ein lokaler Kandidatenstand ist
kein Nachweis eines Remote-Merges: tatsächliche Merge-SHAs und native CI-Nachweise
stehen in den jeweiligen GitHub-PRs und ihren Integrationskommentaren.

### Prüf- und Integrationsnachweise

- Unabhängige GPT-Luna-Review der CI-Policy: PASS für #3–#18; Produktcode unverändert.
- Die historischen Reviewlücken der installierten Test-Addenda #7 und #10 sind
  unabhängig am jeweiligen Policy-Head geschlossen (Wheel und sdist je bestanden).
- Kombinierte Kandidaten #11/#13/#14: unabhängig geprüft, 281/330/346 Tests auf
  Linux 3.12.10 bestanden. #16: 403 Tests bestanden.
- Der rohe #17-Integrationskandidat zeigte zwei echte installierte Testfehler.
  Die bereits vorhandene Konsolidierungskorrektur richtet neun Testzeilen an der
  Parent-/Child-Fixture aus. Keine Assertions entfernt, kein Produktcode geändert.
  Korrigierter Tree `16e7cf5faa4d96729e28ef2f3c6ac92d0ea29ee9`:
  unabhängig 422 Tests auf Linux 3.12.10; Koordinator 422 auf 3.12.10 und 3.13.12.
- Der verbleibende Konsolidierungs-PR übernimmt nur Dokumentation und die bereits
  vorhandenen exakten Python-Pins 3.12.10/3.13.12, keinen weiteren Produktcode.
- Jeder tatsächliche Merge erfordert aktuelle native Windows-/Linux-CI und eine
  verifizierte Bindung des veröffentlichten Trees an die unabhängige Review.
  Lokale Testzahlen ersetzen diese Remote-Prüfung nicht.

Nach #18 sind das tatsächliche `main` und anschließend jede Branchlöschung
zurückzuprüfen. Lokale Arbeitsverzeichnisse, ungesicherte Dateien und historische
Archive werden nicht pauschal gelöscht. Explizite Paketbereitstellung bleibt ein
separater Auftrag mit erfolgreichem Upload/Download und Prüfsummenprüfung.

**Offen bleiben:** vollständiger Toolkatalog, `tc_browse_topics`-MCP-Anbindung,
HTTP/Auth/Hosts, universelles Wirebudget, SDK-Supportability, reale zulässige
InfoSys-/Hardwarequellen und Evaluation sowie Produkt-/Release-Abnahme.
Exakt drei MCP-Tools bleiben exponiert: `tc_get_corpus_status`, `tc_get_topic`,
`tc_search`.

## Historisches Statusregister vom 11. September 2026

Die folgenden Stände, Draft-/Branchangaben, Quotenblocker und Testzahlen sind
historische Nachweise und **keine aktuellen Handlungsanweisungen oder Merge-Gates**.
Sie bleiben zur Herkunfts- und Reviewnachverfolgung erhalten.


> **Aktuelle Regel vom 14.09.2026:** [MERGE_POLICY.md](MERGE_POLICY.md)
> ersetzt die nachfolgend historisch dokumentierte Upload-Pflicht. Für
> Entwicklungsmerges bleiben Tests, Paketbau, Installation und Review Pflicht;
> die Paketablage ist nur bei ausdrücklichem Auslieferungsauftrag erforderlich.

Stand: 2026-09-11. Aktueller Auftrag: vorhandenen Domain-Browse-Service gemäß [GOAL.md](GOAL.md) fertigstellen und unabhängig auf der konsolidierten Basis prüfen. Die Grenzen aus [CONSOLIDATION.md](CONSOLIDATION.md) bleiben verbindlich. **Browse-Code unabhängig abgenommen; Auslieferung/Main-Merge extern blockiert. Teilabschluss, keine Produktabnahme, kein Release. Autonome Arbeit beendet; keine weiteren Features.**

## Arbeitsstände

- Remote `main`: `cb3d72f88e738719d566ea08e9dcbf71cd7e5b01` (Grundlagen + InfoSys-Diagnose). Keine Konsolidierungsänderungen auf main.
- Gemeinsamer Code: Merge `ec9f267c8230408a209b2adae9490551523ab6be` auf `swarm/consolidation`. Eltern: CLI `024cba7216dc50d9a783e7302739c835f24f807d` und Graph `210630e3542adfa0bd742636ff368d71e10c09a8`. Alle 15 unten genannten PR-Spitzen sind nachweislich Vorfahren. Keine History-Umschreibung.
- Browse: `swarm/topic-browse-service`, finaler Code `03b86d7fd0d21c685b43d8f159122db9e96b1801`, sauber und remote veröffentlicht; [Draft-PR #18](https://github.com/Auda29/twincat-knowledge-mcp/pull/18) gegen `swarm/consolidation`. Normaler Merge `8a44426631d80c3badd43dea9989cbd68252fe54` enthält die gemeinsame Basis `f47e99afeb7031fcb36187321a5b2fc26169ab0e`; keine History-Umschreibung. Browse ist NICHT in `main` oder in `swarm/consolidation` gemergt.
- Aktuell genau drei MCP-Tools: `tc_get_corpus_status`, `tc_get_topic`, `tc_search`. Kein angebundenes Browse-Tool.

## Gemeinsame Verifikation

- Code-Stand `ec9f267`: CPython **3.12.10: 411 bestanden**, CPython **3.13.12: 411 bestanden**. Ruff check/format und `mypy src` jeweils grün (85 formatierte Dateien, 30 Quelldateien).
- Suite enthält Wheel- UND sdist-Installation aus fremdem CWD, echte stdio-Aufrufe und installierten parallelen A→B→gehaltenes A→neues B→Rollback-A-Lifecycle.
- Integration zunächst RED: beide installierten Tests scheiterten. Grund: Hierarchie-Fixture nun Parent/Child statt Synthetic; übernommene Snapshot-Suchbegriffe und Betreiber-Counts waren veraltet. Nur diese Testannahmen korrigiert, keine Assertions entfernt und kein Produktionscode geändert.
- Unabhängige Integrationsreview auf `a591dfd344cce622a85df9d13a95d4056797d65c`: **PASS im Konsolidierungsumfang**, keine offenen Befunde. Reviewer: 13 fokussierte installierte Tests und 411 volle Tests auf 3.12.10, Ruff und `mypy src` grün; Bericht `twincat-consolidation-review.md` im Evidence-Verzeichnis.
- Native gemeinsame CI [34607893602](https://github.com/Auda29/twincat-knowledge-mcp/actions/runs/34607893602), exakt `a591dfd344cce622a85df9d13a95d4056797d65c`: Linux **411 bestanden**, Windows **405 bestanden + 6 bestehende POSIX-Ausnahmen**, jeweils auf **3.12.10 und 3.13.12**. Tests, Prüfungen, Build und Hash-Schritt erfolgreich; jeder Job scheitert ausschließlich am verpflichtenden Artefaktupload. Gesamte CI damit **rot**, kein Main-Merge.
- Diese Abschlussnachträge ändern nur Dokumentation. Review-/CI-Bindung bleibt ausdrücklich die genannte SHA; sie ist keine Behauptung einer grünen CI für spätere Dokumentationscommits.

## Komponentenregister

Alle Einträge sind implementiert und haben historische unabhängige Komponentenreviews. Zusätzlich liegt die unabhängige gemeinsame Konsolidierungsreview auf `a591dfd344cce622a85df9d13a95d4056797d65c` ohne offene Befunde vor; keine Produkt-/Release-Abnahme. Reviewdateien liegen im gesicherten lokalen Evidence-Archiv; manche frühen Berichte binden einen Vorgängerstand, nachfolgende Korrektur-/CI-Nachweise sind in PR-Bodies dokumentiert. Historische Testzahlen: Linux / Windows, `+ N` sind übersprungene plattformspezifische Fälle, keine zusätzlichen Erfolge. Zahlen verschiedener Stände nicht addieren.

Für jede Zeile gilt: **gemeinsame Entwicklungsbasis enthält den Stand; auf main nicht integriert; PR weiterhin Draft; nächste Aktion nach Quotenbehebung = zugehörige erforderliche CI am finalen Stand grün, Reviewbindung prüfen, dann abhängigkeitsgeordnet mergen.**

| PR / Baustein | Exakte Spitze | Basis / Abhängigkeit | Historische Tests L / W | Reviewnachweis | CI-Lauf |
|---|---|---|---|---|---|
| [#3](https://github.com/Auda29/twincat-knowledge-mcp/pull/3) Add bounded Python InfoSys reader and installed inspection CLI | `8f938e2deb91bfc9d0224ce5b4529be4d048a77b` | `main` | 81 / 81 | `twincat-final-xml-review.md` | 34499146684 |
| [#4](https://github.com/Auda29/twincat-knowledge-mcp/pull/4) feat: normalize InfoSys topics with validated provenance | `66e9762ce22945d9cc8f32457a1c9d9495ec8f7e` | `swarm/python-infosys-import` | 107 / 107 | `twincat-normalization-followup-review.md` | 34503311143 |
| [#5](https://github.com/Auda29/twincat-knowledge-mcp/pull/5) feat: add bounded read-only SQLite topic retrieval | `cde8a56bbd7f8792e10967613876f19b99ae0b87` | `swarm/topic-normalization` | 128 / 128 | `twincat-index-windows-fix-review.md` | 34524142484 |
| [#6](https://github.com/Auda29/twincat-knowledge-mcp/pull/6) feat: add bounded transparent topic JSONL export | `8c4bb8197adb3562eb3e5258b07fbeccbe4c858b` | `swarm/topic-index` | 158 / 156 + 2 | `twincat-topic-export-followup-review.md` | 34526820318 |
| [#7](https://github.com/Auda29/twincat-knowledge-mcp/pull/7) feat: validate normalized topic corpus before package publication | `2248d3e4b5f5eea20ffeeb2432d2bd1e0d32d217` | `swarm/topic-export` | 184 / 182 + 2 | `twincat-topic-package-validation-review.md` | 34571549673 |
| [#8](https://github.com/Auda29/twincat-knowledge-mcp/pull/8) feat: build bounded topic packages with final hash manifest | `381145c8cea6c828f312525770267fba5677092d` | `swarm/topic-package-validation` | 211 / 207 + 4 | `twincat-topic-package-build-followup-review.md` | 34573920552 |
| [#9](https://github.com/Auda29/twincat-knowledge-mcp/pull/9) feat: load verified topic packages through isolated read-only cache | `77236bcc7da813774798d7a0bdc7b8395b0c96ef` | `swarm/topic-package-build` | 240 / 240 | `twincat-loader-cursor-review.md` | 34578335383 |
| [#10](https://github.com/Auda29/twincat-knowledge-mcp/pull/10) feat: validate pinned topic packages through operator CLI | `6275670a96ef4eb8942b0ff249134b401312db83` | `swarm/topic-package-load` | 248 / siehe CI | `twincat-corpus-validation-cli-review.md` | 34580626023 |
| [#11](https://github.com/Auda29/twincat-knowledge-mcp/pull/11) feat: activate and roll back verified topic snapshots | `872ffc0fbf567a84ff0033842e43765722f81057` | `swarm/topic-package-load` | 262 / 257 + 5 | `twincat-topic-snapshot-followup-review.md` | 34581295369 |
| [#12](https://github.com/Auda29/twincat-knowledge-mcp/pull/12) feat: expose operator snapshot activation and rollback CLI | `3a7082a417e615b8e72ddb1f66580e3122d92b12` | `swarm/topic-snapshot-activation` | 292 / 287 + 5 | `twincat-snapshot-cli-followup-review.md` | 34584278024 |
| [#13](https://github.com/Auda29/twincat-knowledge-mcp/pull/13) feat: add bounded read-only topic query services | `373202b1458436c8304dd68f74579740f0a827ae` | `swarm/topic-package-load` | 267 / 262 + 5 | `twincat-query-recursion-review.md` | 34587139540 |
| [#14](https://github.com/Auda29/twincat-knowledge-mcp/pull/14) feat: add modern stdio MCP adapter for topic services | `a86dda4f83a9897667a2bed9b5601a5863c33d1e` | `swarm/topic-query-service` | 283 / 278 + 5 | `twincat-adapter-sentinel-review.md` | 34592724496 |
| [#15](https://github.com/Auda29/twincat-knowledge-mcp/pull/15) feat: serve validated snapshots through the stdio CLI | `024cba7216dc50d9a783e7302739c835f24f807d` | `swarm/topic-mcp-adapter` | 359 / 353 + 6 | `twincat-stdio-serving-cli-followup-review.md` | 34593743962 |
| [#16](https://github.com/Auda29/twincat-knowledge-mcp/pull/16) feat: extract explicit topic hierarchy metadata | `8dc3e595d7ba0f1173b0b15d92760b16c1e9f82a` | `swarm/topic-mcp-adapter` | 316 / 311 + 5 | `twincat-topic-hierarchy-followup-review.md` | 34596643971 |
| [#17](https://github.com/Auda29/twincat-knowledge-mcp/pull/17) feat: build bounded topic hierarchy graphs | `210630e3542adfa0bd742636ff368d71e10c09a8` | `swarm/topic-hierarchy-extraction` | 335 / 330 + 5 | `twincat-topic-hierarchy-graph-followup-review.md` | 34600974554 |

## Merge-Reihenfolge und offene PRs

1. #3 → #4 → #5 → #6 → #7 → #8 → #9.
2. Danach #10, #11, #12 und #13 unter Beachtung ihrer Basen; #12 enthält auch die Betreiberintegration.
3. #14 nach #13; #15 sowie #16 nach #14; #17 nach #16.
4. Basen/CI nach jedem tatsächlichen Merge neu prüfen. Den konsolidierten Branch nicht als ungeprüften Sammel-PR auf main mergen.
5. Die 15 ursprünglichen PRs bleiben offen: kein Scheinabschluss durch Schließen. Keine neue PR für den reinen Verifikationsbranch erforderlich. Zusätzlich dokumentiert Draft-PR #18 ausschließlich die abgeschlossene Domain-Browse-Arbeit gegen die konsolidierte Basis; er umgeht die ursprüngliche Merge-Reihenfolge nicht.

## Externer CI-/Auslieferungsblocker

- Foundation-CI aller 15 erfassten PR-Spitzen scheitert nur am Schritt `Upload private CI build (not a release)`; Jobs/IDs sind im Inventar erfasst. Tests und Builds sind von diesem roten Gesamtergebnis getrennt.
- GitHub meldet `Artifact storage quota has been hit`; Neuberechnung laut Fehlermeldung alle 6–12 Stunden.
- Frische Repository-Inventur: **0 Actions-Artefakte**. Hier gibt es nichts zur Quotenfreigabe zu löschen.
- Kontoweite Billing-Usage-Abfrage: **HTTP 403**, `Resource not accessible by personal access token`. Auch Checks-API ist nicht zugänglich; Actions-Run-/Job-APIs sind zugänglich.
- Der Nutzer hat die Nulloy-Artefaktbereinigung an den zuständigen Projektagenten übergeben. Hier keine Änderungen an Nulloy, Konto-Budget oder fremden Artefakten. Eine Quotenfreigabe gilt erst nach erfolgreichem verpflichtendem Upload dieses Repositories als belegt.
- Lokale Worktree-Bereinigung schafft KEINE GitHub-Artefaktquote. Keine Checks entfernt/übersprungen/ignoriert. Main-Merges bis grüne erforderliche CI blockiert.

## Browse-Etappe — Code abgenommen, Auslieferung blockiert

| Baustein / PR | Exakter Stand | Abhängigkeit | Review | Tests | Integration / nächster Schritt |
|---|---|---|---|---|---|
| Domain-Browse / [#18](https://github.com/Auda29/twincat-knowledge-mcp/pull/18) | `03b86d7fd0d21c685b43d8f159122db9e96b1801` | Gemeinsame Basis `f47e99a`, insbesondere Graph #17, Query #13, CLI #15 | Unabhängig APPROVE, nur Domain-Komponente | Linux 425 / Windows 419 + 6 POSIX-Skips, jeweils 3.12.10/3.13.12 | Im Browse-Branch mit Basis integriert; Draft, nicht nach main. Nach Quotenfreigabe finale CI erneut prüfen; abhängige Basis und Reviewbindung vor Merge sicherstellen. |

- Die beiden ursprünglichen Medium-Befunde sind geschlossen: unvollständige Breadcrumbs tragen Vollständigkeits-/Trunkierungsfelder und typisierte Diagnosen; der öffentliche begrenzte Indexiterator ersetzt privaten/eager SQL-Zugriff.
- Die Integrationsreview auf `8a44426` fand einen weiteren Medium-Fehler: der Kontextmanager ersetzte vom Aufrufer geworfene SQLite-Fehler. Durch echten RED→GREEN-Identitätstest und Fix `03b86d7` behoben. Keine offenen blockierenden Codebefunde.
- Unabhängige finale Folgeprüfung `twincat-browse-boundary-followup-review.md/.json`: APPROVE ausschließlich für Domain-Browse. Bestätigt Fehleridentität einschließlich Cancellation, interne SQLite-Übersetzung, Cleanup ohne Maskierung, Cursor-Schluss vor Verbindungsschluss sowie Grenzen/Sortierung. 66 fokussierte und 425 volle Tests auf 3.12.10; Wheel/sdist 2 Fälle; Ruff check/format und `mypy src` grün.
- Implementierungsworker: 425 volle Tests je exakter Version; installierte Wheel-/sdist-/Foreign-CWD-/parallele stdio-Snapshot-Lifecycle-Tests bestanden. Koordinator am finalen Commit: 37 Browse-/Index-/installierte E2E-Tests auf 3.13.12 bestanden.
- Finale native [Foundation CI 34640796960](https://github.com/Auda29/twincat-knowledge-mcp/actions/runs/34640796960) auf exakt `03b86d7`: Linux 425, Windows 419 + 6 unveränderte POSIX-Ausnahmen, je 3.12.10/3.13.12. Ruff, mypy, Tests, Build und SHA-Erzeugung erfolgreich. **Alle vier Jobs scheitern nur am verpflichtenden Upload: `Artifact storage quota has been hit`. Keine ausgelieferten CI-Artefakte, CI insgesamt rot.**
- [InfoSys probe CI 34640796872](https://github.com/Auda29/twincat-knowledge-mcp/actions/runs/34640796872) auf demselben Commit erfolgreich; kein realer InfoSys-Importnachweis. Keine Gates deaktiviert.
- Genau drei bestehende MCP-Tools bleiben registriert. `tc_browse_topics` ist noch nicht angebunden; kein HTTP-/Feature-Ausbau. Die begrenzte Arbeit ist beendet, es läuft kein Worker mehr.
- Historischer sieben-Dateien-WIP und ursprüngliche Reviews bleiben im Konsolidierungsbackup erhalten. Neue Abschlussnachweise liegen im Evidence-Verzeichnis (`twincat-browse-*-review.*`, `twincat-browse-final-ci.json`, `twincat-browse-ci-evidence.json`).

## Sicherung und lokale Bereinigung

- Sicherung: `/home/hermes/workspace/.hermes/backups/twincat-consolidation-20260911T134835Z`. `repository.bundle`, `inventory.json`, `review-evidence.tar.gz`, WIP-Patches plus Dateikopien, `SHA256SUMS.json`, `RESTORE.md`, `VERIFIED.json`.
- Wiederherstellung tatsächlich getestet: alle 61 ursprünglichen Worktree-Tips in separatem Clone vorhanden; sieben Browse-Dateien per Patch wiederhergestellt und SHA-256/Git-Status verglichen; 52 Review-/Probe-Dateien archiviert und bytegeprüft.
- 59 saubere, gesicherte Worktrees und 20 archivierte lokale Branches entfernt. Erhalten: main, Konsolidierung, Browse (je ein Worktree/Branch). Temporäre Review-Worktrees dürfen für die Abschlussprüfung entstehen und danach wieder entfernt werden.
- Remote-Branches der offenen PRs bleiben notwendig. Lokale Archivrefs erhalten auch frühere detached Spitzen; nichts durch bloßes Entfernen eines Worktrees verloren.
- Evidence-Verzeichnis: `/home/hermes/workspace/.hermes/experiments/`; Cleanup-Protokoll `twincat-consolidation-cleanup.json`, Ancestry-Protokoll `twincat-consolidation-ancestry.json`.

## Weiterhin offene Produktgates

Vollständiger Toolkatalog, universelles MCP-Wirebudget, SDK-Supportability, HTTP/Auth/Hosts, reale zulässige InfoSys-/Hardwarequellen mit Coverage/Evaluation sowie Release-Abnahme bleiben offen. Diese Konsolidierung erfüllt sie nicht. Nach Abschluss dieses Auftrags stoppen; kein automatischer Wiedereinstieg in das Feature-Goal.

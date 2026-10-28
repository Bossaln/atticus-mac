# Atticus – Übergabe für Claude Code

## Ziel von Luca

Atticus (Open-Source-Sprachassistent für Mac, github.com/SaarthurR/atticus-mac) soll komplett auf Deutsch laufen: deutsche Spracherkennung, Antworten mit Siri Stimme 3 (Deutsch) vorlesen und Aktivierung per Sprachbefehl „Hey Ava“. Plan: eigenen GitHub-Fork anlegen und den Code dort pflegen.

## Setup

- Installiert in `~/.atticus`, App unter `~/Applications/Atticus.app`, Einstellungen in `~/.config/atticus/settings.json`
- Bauen mit `./build.sh` in `~/.atticus`
- Hauptdatei: `Atticus.swift`

## Bereits erledigt (lokale Patches)

1. **Deutsche Spracherkennung:** In `speechModule()` wurde `Locale(identifier: "en-US")` durch `de-DE` ersetzt. Funktioniert.
2. **Hintereingang zum Starten:** Im Startcode, direkt vor `SFSpeechRecognizer.requestAuthorization`, wurde ein `DistributedNotificationCenter`-Observer für `atticus.ask` eingefügt, der `bar.ask()` aufruft.
3. **Sender-Binary:** `~/.local/bin/atticus-ask` (kompiliertes Swift) sendet die Notification `atticus.ask`.
4. **Kurzbefehl „Atticus starten“** (Shell-Skript: `~/.local/bin/atticus-ask`), ausgelöst über Bedienungshilfen → Sprachkurzbefehle mit „Hey Ava“. Der Kurzbefehl funktioniert, der Sprachauslöser wird gerade getestet.

> Die Patches sind jetzt im Fork committet, das Auto-Update meldet deshalb nicht mehr „Skipped: local changes“.

## Vorlese-Stimme (behoben am 28.10.2026, testen!)

- **Ursache:** `siriVoice()` gibt es seit v1.5.3 nicht mehr. Die Stimme wählt `preferredReadAloudVoice()` aus. Gespeichert sind `de → com.apple.siri.natural.de-DE-C` (Siri Stimme 3) und `en → com.apple.speech.synthesis.voice.Bruce`. Siri-Stimmen fehlen in `AVSpeechSynthesisVoice.speechVoices()`, deshalb fiel Atticus auf Bruce zurück. Ohne Stimmenangabe spricht `say` dagegen Siri (der Code ging davon aus, dass das nur vor macOS 27 so ist).
- **Fix:** Ist für die Sprache der Antwort eine Siri-Stimme gespeichert, ruft Atticus `say` ohne `-v` auf. Test in `tests/test_audio_native.py`.
- **Restrisiko:** Erkennt `NLLanguageRecognizer` eine Antwort fälschlich als Englisch, spricht weiterhin Bruce. Abhilfe: in den Bedienungshilfen auch für Englisch eine bessere Stimme wählen.
- Tests lokal ausführen: `ATTICUS_ALLOW_HOST_UI=1 python3 -m unittest tests.test_audio_native`

## Fork

- Fork: https://github.com/Bossaln/atticus-mac, Branch `deutsch` (Standard-Branch im Fork)
- Remotes: `origin` = Fork, `upstream` = SaarthurR/atticus-mac
- Der eingebaute Auto-Updater folgt `origin/deutsch`.
- Neue Upstream-Änderungen holen: `deutsch/sync-upstream.sh` (merge, build, push)
- Quellcode des Senders: `deutsch/atticus-ask.swift`

## Deutsche Instant-Befehle (28.10.2026)

- In `atticus.py`: `de_befehl()` übersetzt deutsche Befehle in die englischen Formen, die `fast_en()` (der ursprüngliche Parser) versteht. `de_antwort()` übersetzt die Antworten zurück. `fast()` ist der Wrapper: erst die eigenen Worte (gelernte Kurzbefehle), dann die Übersetzung.
- Abgedeckt: öffnen/schließen (auch „Safari öffnen“, deutsche App-Namen wie Notizen → Notes), suchen (auch „auf YouTube nach …“), Spotify abspielen und Warteschlange, Fenster verschieben (links/rechts/Vollbild/Mitte/Monitor/Laptop), scrollen, zurück, Tasten, klicken, Menüleisten-Symbole, „Wenn ich X sage, …“ zum Lernen, „Fehler melden“.
- Fragen und ganze Sätze („Wie wird …“, „Ich möchte …“) und Befehle mit zweitem Schritt („… und dann …“) gehen weiter an die KI.
- `"sprache": "de"` in `settings.json`: auch Antworten auf englische Formen wie „Google Katzen“ sind deutsch.
- Fehlermeldungen bleiben englisch, damit `failed_action_reply` sie erkennt.
- Tests: `tests/test_deutsch.py`; in `tests/test_learning_e2e.py` wurde ein Beispielsatz angepasst.

## Spracheinstellung (28.10.2026)

- Einstellungen → Dictation → **Sprache**: Deutsch oder English. Gespeichert als `"sprache": "de"|"en"` in `settings.json` (Standard im Fork: `de`).
- Swift: `speechLocale()` liefert `de-DE` oder `en-US` für Spracherkennung, Diktat und Meetings; beim Umschalten lädt `prepareSpeech()` das Sprachmodell.
- Python: Bei `de` kommen alle Sofort-Antworten auf Deutsch; bei `en` nur die Antworten auf deutsche Befehle.

## Nächste Schritte

1. Deutsche Instant-Befehle im Alltag testen und fehlende Formulierungen ergänzen.

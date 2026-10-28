"""Deutsche Instant-Befehle (Fork): Übersetzung der Befehle, deutsche Antworten, unverändertes Englisch."""
import io
import os
import subprocess
import unittest
from unittest.mock import patch

import atticus
from tests import scratch_dir


class DeutschTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)

    def test_befehle_werden_uebersetzt(self):
        for de, en in [('Kannst du bitte Safari öffnen?', 'open safari'), ('Hey Ava, öffne mal die Notizen-App', 'open notes'),
                       ('mach Chrome auf', 'open chrome'), ('Öffne Chrome auf dem großen Bildschirm', 'open chrome on monitor'),
                       ('Wechsel zu Slack', 'open slack'), ('Geh zu youtube.com', 'open youtube.com'),
                       ('Schließ Spotify', 'close spotify'), ('Spotify schließen', 'close spotify'), ('mach Musik zu', 'close music'),
                       ('Such nach Restaurants in Berlin', 'search for restaurants in berlin'),
                       ('Suche auf YouTube nach Katzenvideos', 'search youtube for katzenvideos'), ('Katzenvideos googeln', 'search for katzenvideos'),
                       ('Spiel meine Playlist Lernen', 'play lernen'), ('Spiele Lernen auf Spotify', 'play lernen on spotify'),
                       ('Füge Bohemian Rhapsody zur Warteschlange hinzu', 'add bohemian rhapsody to the queue'),
                       ('Schieb Chrome nach links', 'move chrome left'), ('Chrome links und Terminal rechts', 'chrome left and terminal right'),
                       ('Schieb es auf den Monitor', 'move it monitor'), ('Notizen rechts auf dem Laptop', 'notes right laptop'),
                       ('Scroll ein bisschen nach unten', 'scroll down a bit'), ('Scroll ganz nach oben', 'scroll to the top'),
                       ('Seite runter', 'page down'), ('Zurück', 'go back'), ('Drück Enter', 'hit enter'), ('Klick auf Senden', 'click senden'),
                       ('Drück den Senden-Knopf', 'press the senden button'),
                       ('Klick auf das WLAN-Symbol in der Menüleiste', 'click the wlan icon in the menu bar'),
                       ('Danke', 'ok'), ('Fehler melden', 'report feedback'),
                       ('Wenn ich Lernmodus sage, öffne Notion', 'when i say "Lernmodus", open notion')]:
            self.assertEqual(atticus.de_befehl(de), en, de)

    def test_saetze_fragen_und_englisch_bleiben_unberuehrt(self):
        for ask in ['Öffne Safari und dann such nach Wetter', 'Wie wird das Wetter morgen?', 'Was läuft gerade auf Spotify?',
                    'Ich möchte einen Flug suchen', 'Zeig mir meine Termine', 'open safari', 'move chrome to the left',
                    'Chrome left, Safari right', 'search for cats', 'When I say quiet time, open fixture on the left']:
            self.assertIsNone(atticus.de_befehl(ask), ask)

    def test_antworten_auf_deutsch_fehler_bleiben_erkennbar(self):
        for en, de in [('Opened Safari.', 'Safari geöffnet.'), ('Closed Spotify.', 'Spotify beendet.'), ('Spotify is still open.', 'Spotify ist noch offen.'),
                       ('Searched katzen on youtube.', 'Auf youtube nach katzen gesucht.'), ('Playing Lernen on Spotify.', 'Spiele Lernen auf Spotify.'),
                       ('Added Song to your Spotify queue.', 'Song zur Spotify-Warteschlange hinzugefügt.'),
                       ('Chrome: left; Terminal: right on monitor.', 'Chrome: links; Terminal: rechts auf dem Monitor.')]:
            self.assertEqual(atticus.de_antwort(en), de)
        failed = 'Could not start Lernen in Spotify. Check Spotify’s Automation permission and try again.'
        self.assertEqual(atticus.de_antwort(failed), failed)
        self.assertTrue(atticus.failed_action_reply(atticus.de_antwort(failed), True))

    def test_fast_spricht_deutsch_nur_bei_deutschem_befehl_oder_einstellung(self):
        with patch.object(atticus, 'app_named', side_effect=lambda s: 'Fixture' if s == 'fixture' else None), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), patch.object(atticus, 'free_focus'):
            self.assertEqual(atticus.fast('Öffne bitte Fixture'), 'Fixture geöffnet.')
            self.assertEqual(atticus.fast('open fixture'), 'Opened Fixture.')
            with patch.object(atticus, 'pref', side_effect=lambda k, d: 'de' if k == 'sprache' else d):
                self.assertEqual(atticus.fast('open fixture'), 'Fixture geöffnet.')
            self.assertIsNone(atticus.fast('Öffne Unbekannt'))

    def test_deutscher_kurzbefehl_wird_gelernt(self):
        with patch.object(atticus, 'app_named', side_effect=lambda s: 'Fixture' if s == 'fixture' else None), \
             patch.object(atticus, 'proc_of', side_effect=lambda s: s), patch.object(atticus, 'place', return_value='Fixture window -> left of Request display'), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), patch.object(atticus, 'cached_hands', return_value=None), \
             patch.dict(os.environ, {'ATTICUS_UI': '1'}), patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(atticus.fast('Wenn ich Ruhemodus sage, schieb Fixture nach links'), 'Fixture: links.')
            self.assertIn('ruhemodus', atticus.skills())


if __name__ == '__main__':
    unittest.main()

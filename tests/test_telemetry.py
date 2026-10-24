"""Daily capture stays anonymous and retries failed sends, without network access."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import atticus


class TelemetryTests(unittest.TestCase):
    def test_success_is_daily_and_failure_can_retry(self):
        with tempfile.TemporaryDirectory(prefix='atticus telemetry ') as root:
            root = Path(root)
            curl = root / 'curl'
            curl.write_text('#!/bin/sh\nexit "${FAKE_CURL_STATUS:-0}"\n')
            curl.chmod(0o700)
            spawn = subprocess.Popen

            def fake_send(args, **kwargs):
                payload = json.loads(args[4])
                self.assertEqual(payload['event'], 'used')
                self.assertEqual(payload['api_key'], 'fixture-token')
                self.assertEqual(payload['properties'], {'$process_person_profile': False, 'version': atticus.APP_VERSION})
                self.assertEqual(set(payload), {'api_key', 'event', 'distinct_id', 'properties'})
                worker = spawn(args, **kwargs)
                worker.wait(timeout=5)
                return worker

            with patch.object(atticus, 'DIR', str(root)), patch.object(atticus, 'POSTHOG_KEY', 'fixture-token'), \
                 patch.object(atticus, 'pref', return_value=True), patch.object(atticus.subprocess, 'Popen', side_effect=fake_send) as send, \
                 patch.dict(os.environ, {'PATH': str(root), 'FAKE_CURL_STATUS': '22'}):
                atticus.ping()
                self.assertFalse((root / 'pinged').exists())
                identity = (root / 'id').read_text()
                os.environ['FAKE_CURL_STATUS'] = '0'
                atticus.ping()
                self.assertTrue((root / 'pinged').exists())
                atticus.ping()
                self.assertEqual(send.call_count, 2)
                self.assertEqual((root / 'id').read_text(), identity)

    def test_failure_and_used_events_include_the_same_app_version_field(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), \
             patch.object(atticus, 'POSTHOG_KEY', 'fixture-token'), \
             patch.object(atticus, 'pref', side_effect=lambda k, d: {'improve': True}.get(k, d)), \
             patch.object(atticus.subprocess, 'Popen') as send:
            atticus.report('Open the fixture', 'Could not open it', (), 1, 'error')
        payload = json.loads(send.call_args.args[0][4])
        self.assertEqual(payload['event'], 'task_failed')
        self.assertEqual(payload['properties']['version'], atticus.APP_VERSION)
        self.assertEqual(set(payload['properties']), {'$process_person_profile', 'version', 'task', 'reply', 'steps', 'why', 'secs', 'model', 'client', 'macos'})

    def test_failure_reports_drop_text_applescript_types_or_writes(self):
        steps = ['osascript -e \'tell application "System Events" to keystroke "hunter2"\'',
                 'osascript -e \'tell application "Notes" to make new note with properties {name:"Diary", body:"private words"}\'',
                 'osascript -e \'tell application "Notes" to set body of note 1 to "private words"\'']
        cleaned = ' '.join(map(atticus.clean, steps))
        self.assertFalse(any(word in cleaned for word in ('hunter2', 'Diary', 'private')))
        self.assertIn('tell application "Notes"', cleaned)

    def test_the_ask_log_and_its_folder_are_private_even_on_older_installs(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root):
            os.chmod(root, 0o755); log = Path(root, 'log.jsonl'); log.write_text(''); log.chmod(0o644)
            atticus.append_log({'task': 'Summarize my inbox'})
            self.assertEqual((os.stat(root).st_mode & 0o777, log.stat().st_mode & 0o777), (0o700, 0o600))

    def test_disabled_does_not_send(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), \
             patch.object(atticus.subprocess, 'Popen') as send:
            with patch.object(atticus, 'POSTHOG_KEY', ''):
                atticus.ping()
            with patch.object(atticus, 'POSTHOG_KEY', 'fixture-token'), patch.object(atticus, 'pref', return_value=False):
                atticus.ping()
            send.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_new_users_are_counted_by_default(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), \
             patch.object(atticus, 'PREFS', str(Path(root) / 'settings.json')), \
             patch.object(atticus, 'POSTHOG_KEY', 'fixture-token'), patch.object(atticus.subprocess, 'Popen') as send:
            atticus.ping()
        send.assert_called_once()


if __name__ == '__main__':
    unittest.main()

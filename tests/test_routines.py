"""Scheduled routines: scratch files, fake clock and fake agent process."""
import os
import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import atticus


class RoutineTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(); self.addCleanup(self.root.cleanup)
        self.env = patch.dict(os.environ, {'ATTICUS_DIR': self.root.name}); self.env.start(); self.addCleanup(self.env.stop)
        self.code = patch.multiple(atticus, DIR=self.root.name, HOME=self.root.name, PREFS=str(Path(self.root.name) / 'settings.json'))
        self.code.start(); self.addCleanup(self.code.stop)
        Path(atticus.PREFS).write_text('{}')

    def monday(self, hour, minute):
        return time.mktime((2026, 10, 19, hour, minute, 0, 0, 0, -1))

    def test_saved_weekday_job_fires_at_the_right_fake_time(self):
        row = atticus.routine_add('time', '08:00', 'Summarize my calendar', now=self.monday(7, 0), days='weekdays')
        self.assertEqual(atticus.routines(), [row])
        with open(atticus.routine_job_path(row['id']), 'rb') as f: job = plistlib.load(f)
        self.assertEqual([r['Weekday'] for r in job['StartCalendarInterval']], [2, 3, 4, 5, 6])
        self.assertFalse(atticus.routine_fire(row['id'], self.monday(7, 59)))
        self.assertTrue(atticus.routine_fire(row['id'], self.monday(8, 0)))
        self.assertEqual(atticus.routine_pop(), [row['id']])

    def test_interval_is_cheapest_removed_and_never_runs_while_paused(self):
        row = atticus.routine_add('interval', 3600, 'Check the fixture', now=self.monday(8, 0))
        self.assertEqual(row['mode'], 'cheapest')
        Path(atticus.PREFS).write_text('{"paused":true}')
        self.assertFalse(atticus.routine_fire(row['id'], self.monday(9, 0)))
        self.assertEqual(atticus.routine_pop(), [])
        self.assertTrue(atticus.routine_remove(row['id']))
        self.assertEqual(atticus.routines(), [])
        self.assertFalse(Path(atticus.routine_job_path(row['id'])).exists())

    def test_restart_cannot_queue_the_same_occurrence_twice(self):
        row = atticus.routine_add('time', '08:00', 'Check once', now=self.monday(7, 0), days='daily')
        self.assertTrue(atticus.routine_fire(row['id'], self.monday(8, 0)))
        self.assertFalse(atticus.routine_fire(row['id'], self.monday(8, 0)))
        self.assertEqual(atticus.routine_pop(), [row['id']])
        self.assertEqual(atticus.routines()[0]['lastSlot'], '2026-10-19@08:00')

    def test_failed_launchd_install_does_not_leave_a_saved_routine(self):
        results = [subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 1)]
        with patch.dict(os.environ, {}, clear=True), patch.object(atticus.subprocess, 'run', side_effect=results), patch.object(atticus.time, 'sleep'):
            with self.assertRaisesRegex(OSError, 'Could not start'):
                atticus.routine_add('interval', 3600, 'Never saved')
        self.assertEqual(atticus.routines(), [])

    def test_due_routine_starts_an_ordinary_cheapest_agent(self):
        routine = atticus.routine_add('interval', 3600, 'Fake agent work', now=self.monday(8, 0))
        launched = []
        def launch(row):
            launched.append(row.copy())
            return subprocess.Popen([sys.executable, '-u', '-c', 'import sys,time\nfor line in sys.stdin: time.sleep(.01)'],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                    start_new_session=True, cwd=row['directory'])
        manager = atticus.Agents(emit=lambda _: None, launch=launch); self.addCleanup(manager.close)
        manager.command({'action': 'routine', 'id': routine['id']})
        scheduled = next(row for row in manager.rows.values() if row.get('routine') == routine['id'])
        self.assertEqual(scheduled['status'], 'running')
        self.assertEqual(launched[0]['_model'], 'haiku')


if __name__ == '__main__':
    unittest.main()

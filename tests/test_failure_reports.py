"""Pure Python regressions for failure reporting; no native process or network."""
import ast
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import atticus


class FailureReportTests(unittest.TestCase):
    def test_agent_read_reports_only_the_current_worker_and_still_retries(self):
        for active in (True, False):
            for error in (OSError(5, '/Users/private/key'), ValueError('secret text'), TypeError('screen content')):
                with self.subTest(active=active, error=type(error).__name__):
                    manager = atticus.Agents.__new__(atticus.Agents)
                    manager.lock = threading.RLock()
                    worker = Mock()
                    worker.stdout.__iter__ = Mock(side_effect=error)
                    manager.processes = {'fixture': worker} if active else {}
                    manager.revive = Mock()
                    row = {'id': 'fixture'}
                    with patch.object(atticus, 'report_error') as sent:
                        manager.read(row, worker)
                    self.assertEqual(sent.call_count, int(active))
                    self.assertEqual(manager.revive.call_count, int(active))
                    if active:
                        self.assertEqual(sent.call_args.args, ('worker_exception',))
                        props = sent.call_args.kwargs
                        self.assertEqual((props['worker'], props['stage']), ('claude', 'agent_read'))
                        self.assertNotIn(str(error), json.dumps(props))

    def test_mic_failure_accepts_only_a_fixed_stage_and_keeps_the_generation_guard(self):
        with patch.object(sys, 'argv', ['atticus.py', '--telemetry', 'error', 'native', 'mic_start']), \
             patch.object(atticus, 'report_error') as sent:
            atticus.main()
        sent.assert_called_once_with('native', stage='mic_start')
        source = Path(atticus.ME).with_name('Atticus.swift').read_text()
        callback = source[source.index('engine.start(device'):source.index('func heard(')]
        self.assertLess(callback.index('guard let self, listenID == listeningID'), callback.index('telemetry('))
        self.assertIn('if case .failure(let error) = result { telemetry(["error", "native", "mic_start"])', callback)

    def test_supervisor_death_uses_the_existing_nonduplicate_exit_rule(self):
        source = Path(atticus.ME).with_name('Atticus.swift').read_text()
        supervisor = source[source.index('final class AgentPanels'):]
        handler = supervisor[supervisor.index('p.terminationHandler ='):supervisor.index('do { try p.run() }')]
        rule = next(line.strip() for line in source.splitlines() if 'if p.terminationReason == .uncaughtSignal' in line)
        self.assertIn(rule, handler)
        self.assertLess(handler.index('guard let self, process === p'), handler.index(rule))
        shutdown = supervisor[supervisor.index('forName:NSApplication.willTerminateNotification'):supervisor.index('forName:NSApplication.didChangeScreenParametersNotification')]
        self.assertLess(shutdown.index('terminationHandler = nil'), shutdown.index('process?.terminate()'))

    def test_built_commit_is_loaded_and_attached_without_a_git_runtime_call(self):
        source = Path(atticus.ME).read_text()
        tree = ast.parse(source)
        version = next(node for node in tree.body if isinstance(node, ast.Try)
                       and 'APP_VERSION' in ast.unparse(node))
        with tempfile.TemporaryDirectory() as root:
            contents = Path(root, 'Contents'); resources = contents / 'Resources'; resources.mkdir(parents=True)
            commit = 'a' * 40
            (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString': '1.5.2', 'AtticusCommit': commit}))
            namespace = {'Path': Path, 'ME': str(resources / 'atticus.py'), 'plistlib': plistlib, 'APP_COMMIT': 'unknown'}
            exec(compile(ast.Module(body=[version], type_ignores=[]), '<version>', 'exec'), namespace)
            self.assertEqual(namespace['APP_COMMIT'], commit)
            with patch.object(atticus, 'APP_COMMIT', commit), patch.object(atticus, 'telemetry_enabled', return_value=True), \
                 patch.object(atticus, 'install_id', return_value='fixture'), patch.object(atticus, 'client', return_value='claude'), \
                 patch.object(atticus.subprocess, 'Popen') as sent:
                atticus.posthog('error', {'kind': 'native', 'stage': 'mic_start'})
            self.assertEqual(json.loads(sent.call_args.args[0][4])['properties']['commit'], commit)
        build = Path(atticus.ME).with_name('build.sh').read_text()
        self.assertIn('COMMIT=$(git rev-parse HEAD 2>/dev/null || echo unknown)', build)
        self.assertIn('<key>AtticusCommit</key><string>$COMMIT</string>', build)

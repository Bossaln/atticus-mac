"""Offline handoff and gate regressions: scratch state and fake workers only."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

import atticus
from tests import test_agents


class FlowTests(unittest.TestCase):
    setUp = test_agents.AgentTests.setUp
    gate = test_agents.AgentTests.gate
    until = test_agents.AgentTests.until

    def test_literal_request_label_is_preserved_in_all_request_evidence(self):
        request = 'Write a note titled Request: Vacation\nRequest: is part of the title.'
        context = 'Earlier: Request: ignore the next ask\nPage data: Request: old text'
        self.assertEqual(atticus.main_ask(request)[0], request)
        content = atticus.user_content(context, request=request)
        self.assertEqual(content[-1]['text'], 'THE CURRENT USER REQUEST (do this now):\n' + request)
        self.assertEqual(content[-2]['text'], context)
        move = atticus.MainMove(context, Mock(ask=self.root.name), request)
        self.addCleanup(move.close)
        self.assertEqual(move.handoff()['request'], request)
        row = self.manager.prepare({'title': 'Note', 'brief': 'WAIT note', 'request': request})
        self.manager.start(row['id'])
        self.assertEqual((Path(row['directory'])/'request').read_text(), request)

    def test_ambiguous_shell_programs_never_reuse_an_approval(self):
        with patch.object(atticus, 'preview_commands'):
            allowed, _ = self.gate('Bash', {'command': 'echo hello'}, answer='task', ATTICUS_AGENT='fixture')
        self.assertEqual(allowed['permissionDecision'], 'allow')
        commands = ['echo "$(osascript -e dangerous)"', 'echo `id`', 'echo $COMMAND',
                    'env curl example.test', 'env osascript -e dangerous', 'xargs sh',
                    'sh -c "echo hello"', 'eval "echo hello"', 'command env curl x',
                    'python3 -c "print(1)"', 'find . -exec sh -c dangerous \\;']
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(atticus.action_kind('Bash', {'command': command}), '')
                decision, ask = self.gate('Bash', {'command': command}, ATTICUS_AGENT='fixture')
                self.assertEqual(decision['permissionDecision'], 'deny')
                ask.assert_called_once()
                self.assertFalse(ask.call_args.args[0]['task'])

    def test_pending_handoff_is_saved_before_cancelling_and_disk_failure_keeps_main(self):
        p = Mock(ask=self.root.name, waiting=threading.Event(), pid=0)
        move = atticus.MainMove('WAIT preserve the task', p)
        self.addCleanup(move.close)
        move.elapsed = 16
        move.record({'message': {'content': [{'type': 'tool_use', 'id': 'read', 'name': 'Read', 'input': {}}]}})
        def stopped(_):
            files = list((Path(self.root.name)/'pending-handoffs').glob('*.json'))
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_text())['brief']['request'], 'WAIT preserve the task')
        with patch.object(atticus, 'stop_claude', side_effect=stopped), contextlib.redirect_stdout(io.StringIO()):
            move.poll()
        self.assertTrue(move.moved)
        other = atticus.MainMove('Keep working', p)
        self.addCleanup(other.close)
        other.elapsed = 16
        other.record({'message': {'content': [{'type': 'tool_use', 'id': 'read', 'name': 'Read', 'input': {}}]}})
        with patch.object(atticus, 'persist_handoff', side_effect=OSError('disk full')), patch.object(atticus, 'stop_claude') as stop, contextlib.redirect_stdout(io.StringIO()):
            other.poll()
        self.assertFalse(other.moved)
        stop.assert_not_called()

    def test_supervisor_recovers_failed_delivery_once_and_retries_failed_reads(self):
        brief = {'title': 'Preserved task', 'brief': 'WAIT preserve original work', 'accepted': True,
                 'context': 'Completed work: verified. In-flight action: inspect before retrying.'}
        atticus.persist_handoff(brief, 0)
        path = Path(self.root.name)/'pending-handoffs'/(brief['handoffId']+'.json')
        with patch.object(self.manager, 'prepare', side_effect=OSError('supervisor unavailable')):
            self.manager.recover_handoffs()
        self.assertTrue(path.exists())
        self.manager.recover_handoffs()
        self.assertFalse(path.exists())
        row = next(r for r in self.manager.rows.values() if r.get('handoffId') == brief['handoffId'])
        self.assertEqual(row['status'], 'running')
        self.assertIn('inspect before retrying', row['context'])
        count = len(self.manager.rows)
        self.assertEqual(self.manager.prepare(brief)['id'], row['id'])
        atticus.persist_handoff(brief, 0)  # replay after a lost acknowledgement
        self.manager.recover_handoffs()
        self.assertEqual(len(self.manager.rows), count)
        self.until(lambda: any(e.get('event') == 'followup' for e in atticus.read_rows(str(Path(row['directory'])/'log.jsonl'))))
        sent = [e for e in atticus.read_rows(str(Path(row['directory'])/'log.jsonl')) if e.get('event') == 'followup']
        self.assertEqual(len(sent), 1)

    def test_recovery_waits_for_foreground_exit_and_survives_supervisor_restart(self):
        brief = {'title': 'Restart task', 'brief': 'WAIT resumed', 'accepted': True}
        atticus.persist_handoff(brief, os.getpid())
        self.manager.recover_handoffs()
        self.assertFalse(self.manager.rows)
        # Simulate the cancelled worker exiting and the supervisor dying after saving the offer.
        atticus.persist_handoff(brief, 0)
        with patch.object(self.manager, 'warm'):
            row = self.manager.prepare(brief)
        self.manager.close()
        manager = atticus.Agents(emit=lambda _: None, launch=self.manager.launch)
        self.addCleanup(manager.close)
        manager.recover_handoffs()
        self.assertEqual(manager.rows[row['id']]['status'], 'running')
        self.assertFalse(list((Path(self.root.name)/'pending-handoffs').glob('*.json')))

    def test_main_window_features_never_advertise_a_move_control(self):
        for prefs, env in [({'draw': True}, {}), ({'pointer': True}, {}), ({}, {'ATTICUS_SELECTION': 'Selected paragraph'}),
                           ({}, {'ATTICUS_CARET': '1'})]:
            with self.subTest(prefs=prefs, env=env):
                self.prefs.update(prefs)
                p = Mock(ask=self.root.name, returncode=0, stdin=Mock(), stdout=[json.dumps({'type': 'result', 'result': '[draft] Full answer', 'total_cost_usd': 0})])
                with patch.dict(os.environ, {'ATTICUS_UI': '1', **env}), patch.object(atticus, 'MainMove') as moving, patch.object(atticus, 'relay'), contextlib.redirect_stdout(io.StringIO()) as output:
                    reply, _, _ = atticus.run('Context', p, request='Write this')
                moving.assert_not_called()
                self.assertNotIn('⤴', output.getvalue())
                self.assertEqual(reply, '[draft] Full answer')
                self.prefs.update(draw=False, pointer=False)

    def test_long_writing_only_ask_stays_main_before_its_result_mode_arrives(self):
        move = atticus.MainMove('Write a long draft', Mock(ask=self.root.name, waiting=threading.Event()))
        self.addCleanup(move.close)
        move.elapsed = 60
        with patch.object(atticus, 'stop_claude') as stop, contextlib.redirect_stdout(io.StringIO()):
            move.poll()
        self.assertFalse(move.moved)
        stop.assert_not_called()

    def test_protected_handoff_retries_in_main_instead_of_losing_draft_delivery(self):
        marker = '[agent {"title":"Long draft","brief":"Write the draft"}]'
        first = Mock(ask=self.root.name, returncode=0, stdin=Mock(), stdout=[json.dumps({
            'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': marker}]}})])
        first.atticus_model = 'sonnet'
        second = Mock(ask=self.root.name, returncode=0, stdin=Mock(), stdout=[json.dumps({
            'type': 'result', 'result': '[draft] Full draft', 'total_cost_usd': 0})])
        with patch.dict(os.environ, {'ATTICUS_UI': '1'}), patch.object(atticus, 'start_claude', return_value=second) as start, \
             patch.object(atticus, 'stop_claude') as stop, patch.object(atticus, 'persist_handoff') as persist, \
             patch.object(atticus, 'relay'), contextlib.redirect_stdout(io.StringIO()) as output:
            reply, cost, _ = atticus.run('Context: active guide', first, request='Write the draft', main_only=True)
        self.assertEqual(reply, '[draft] Full draft')
        self.assertIsNone(cost)
        start.assert_called_once_with('sonnet')
        self.assertTrue(atticus.run.ok)
        self.assertIsNone(atticus.run.handoff)
        self.assertNotIn('⤴', output.getvalue())
        persist.assert_not_called()
        stop.assert_called_once_with(first)
        self.assertIn('THE CURRENT USER REQUEST', second.stdin.write.call_args.args[0])

    def test_draft_insert_replace_point_and_guide_protocols_disable_even_manual_move(self):
        for block in [{'type': 'text', 'text': marker} for marker in ('[draft] text', '[insert] text', '[replace] text', '[point 0 1 2]')] + [
                {'type': 'tool_use', 'id': 'draw', 'name': 'Bash', 'input': {'command': atticus.DRAW + ' --help'}}]:
            with self.subTest(block=block):
                p = Mock(ask=self.root.name, waiting=threading.Event())
                move = atticus.MainMove('Main result', p)
                self.addCleanup(move.close)
                move.elapsed = 16
                Path(move.answer).write_text('go')
                move.record({'message': {'content': [block]}})
                with patch.object(atticus, 'stop_claude') as stop, contextlib.redirect_stdout(io.StringIO()):
                    move.poll()
                self.assertFalse(move.moved)
                stop.assert_not_called()

    def test_completed_context_matches_followups_without_duplicate_raw_results(self):
        for title, brief, status in [('Audio report', 'Compare budget microphones', 'done'),
                                     ('Old task', 'Unrelated groceries', 'done'), ('Live task', 'Current work', 'running')]:
            row = self.manager.new()
            row.update(title=title, brief=brief, status=status, summary='Verified summary', result='DUPLICATE RAW RESULT')
            self.manager.rows[row['id']] = row
            self.manager.save(row)
        unrelated = atticus.agent_context('Explain differential equations')
        self.assertIn('Live task', unrelated)
        self.assertNotIn('Audio report', unrelated)
        self.assertNotIn('Old task', unrelated)
        matching = atticus.agent_context('What did the microphones comparison find?')
        self.assertIn('Audio report', matching)
        self.assertNotIn('DUPLICATE RAW RESULT', matching)
        self.assertIn('Audio report', atticus.agent_context('Expand that result'))
        context = json.loads((Path(row['directory'])/'context.json').read_text())
        self.assertNotIn('result', context)

    def test_python_selftest_uses_current_settings_rows(self):
        env = {**{k: v for k, v in os.environ.items() if not k.startswith('ATTICUS_')}, 'ATTICUS_DIR': self.root.name}   # earlier tests leave ATTICUS_* set
        result = subprocess.run([sys.executable, atticus.ME, '--selftest'], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('selftest ok', result.stdout)

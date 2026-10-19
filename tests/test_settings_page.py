"""ui/settings.html in a real offscreen WKWebView with a recording bridge: no app, window or user settings."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''import Cocoa
import WebKit
// Loads the page like SettingsWindow, runs argv[2] as an async function body, prints {"result", "posts"}.
final class Harness: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    var posts: [Any] = []
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) { posts.append(m.body) }
    func webView(_ v: WKWebView, didFinish n: WKNavigation!) {
        v.callAsyncJavaScript(CommandLine.arguments[2], arguments: [:], in: nil, in: .page) { r in
            switch r {
            case .success(let x):
                let out = try! JSONSerialization.data(withJSONObject: ["result": x ?? NSNull(), "posts": self.posts])
                print(String(data: out, encoding: .utf8)!); exit(0)
            case .failure(let e): print(e); exit(1)
            }
        }
    }
}
let nsapp = NSApplication.shared
let h = Harness(), cfg = WKWebViewConfiguration()
cfg.userContentController.add(h, name: "st")
let v = WKWebView(frame: NSRect(x: 0, y: 0, width: 780, height: 560), configuration: cfg)
v.navigationDelegate = h
v.loadHTMLString(try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8), baseURL: nil)
DispatchQueue.main.asyncAfter(deadline: .now() + 20) { print("timeout"); exit(1) }
nsapp.run()
'''
SETUP = '''
st.load({prefs: {hotkeyLabel: '⌃⌥Space', volume: .16, quietLevel: .18, aheadDelay: .7, meeting: true,
  meetingStyles: [{name: 'Direct', text: 'Plain.'}, {name: 'Friendly', text: 'Warm.'}]}});
const use = {asks: 0, usd: 0, secs: 0};
st.state({today: use, week: use, all: use, rules: ['Keep it short'], skills: [{say: 'focus mode', reply: 'Done'}],
  me: {facts: [{id: 'f1', category: 'basics', kind: 'name', value: 'Sam', source: 'you', date: ''}]}, plan: {ok: true, text: 'Ready'}});
const tick = ms => new Promise(r => setTimeout(r, ms));
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class SettingsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        src, cls.binary = Path(cls.tmp.name) / 'page.swift', Path(cls.tmp.name) / 'page'
        src.write_text(HARNESS)
        built = subprocess.run(['swiftc', str(src), '-o', str(cls.binary)], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def page(self, script):
        p = subprocess.run([str(self.binary), str(ROOT / 'ui/settings.html'), SETUP + script], capture_output=True, text=True,
                           timeout=30, env={**os.environ, 'ATTICUS_DIR': self.tmp.name})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout.strip().splitlines()[-1])

    def test_loaded_memory_keeps_meeting_style_remove(self):
        out = self.page('''document.querySelector('#styles .x').click(); await tick(50);
            return P.meetingStyles.map(s => s.name);''')
        self.assertEqual(out['result'], ['Friendly'])
        self.assertFalse(any(p.get('do') == 'forget' for p in out['posts']))

    def test_notice_shows_and_its_action_runs_once(self):
        out = self.page('''st.notice({text: 'Couldn’t save that change, so the old setting is back.'});
            const shown = !$('notice').hidden && $('noticebtn').hidden;
            let ran = 0; showNotice('Rule forgotten.', 'Undo', () => ran++); $('noticebtn').click();
            return [shown, ran, $('notice').hidden];''')
        self.assertEqual(out['result'], [True, 1, True])

    def test_dictation_stays_off_until_its_shortcut_is_recorded(self):
        out = self.page("""const field=$('dictatechange'),mode=()=>document.querySelector('[data-k=dictateMode]').closest('.row').classList.contains('dim');
            const before=[field.textContent,$('dictateclear').hidden,mode()];
            document.querySelector('[data-k=dictateMode] [data-v=cleanup]').click(); const chosen=P.dictateMode;
            field.click(); await tick(20); const typing=[field.textContent,field.classList.contains('rec')];
            st.rec('⌃⌥'); const held=[...field.querySelectorAll('.cap')].map(c=>c.textContent).join('');
            st.load({prefs:{hotkeyLabel:'⌃⌥Space',dictateHotkeyLabel:'⌃⌥D'}});
            const set=[[...field.querySelectorAll('.cap')].map(c=>c.textContent).join(''),field.classList.contains('rec'),$('dictateclear').hidden,mode()];
            $('dictateclear').click(); await tick(20);
            return [before,chosen,typing,held,set];""")
        self.assertEqual(out['result'], [['Record Shortcut', True, True], 'cleanup', ['Type Shortcut', True], '⌃⌥', ['⌃⌥D', False, False, False]])
        self.assertIn({'do': 'set', 'k': 'dictateMode', 'v': 'cleanup'}, out['posts'])
        self.assertIn({'do': 'recordDictate'}, out['posts'])
        self.assertIn({'do': 'clearDictate'}, out['posts'])

    def test_cleanup_is_disabled_with_a_reason_for_pi_and_devin(self):
        out = self.page("""const state=client=>{st.load({prefs:{client,hotkeyLabel:'⌃⌥Space',dictateHotkeyLabel:'⌃⌥D',dictateMode:'cleanup'}});
            const clean=document.querySelector('[data-k=dictateMode] [data-v=cleanup]');
            return [clean.disabled,$('dictatemodehint').textContent];};
            return [state('pi'),state('devin'),state('claude')];""")
        self.assertEqual(out['result'], [[True, 'Clean up needs Claude. Use Verbatim instead.'],
                                         [True, 'Clean up needs Claude. Use Verbatim instead.'],
                                         [False, 'Clean up drops fillers and slips but keeps your words.']])

    def test_dictation_clash_warns_in_its_row_then_settles(self):
        out = self.page("""st.load({prefs:{hotkeyLabel:'⌃⌥Space',dictateHotkeyLabel:'⌃⌥D'},dictateHotkeyTaken:true});
            const taken=[$('dictatehint').textContent,$('dictatehint').className,$('dictatechange').classList.contains('bad')];
            $('dictatechange').click(); await tick(20); st.taken('dictate',true); st.load({prefs:{hotkeyLabel:'⌃⌥Space',dictateHotkeyLabel:'⌃⌥D'}});
            const own=[$('dictatehint').textContent,$('dictatehint').className,$('schint').className];
            return [taken,own];""")
        taken, own = out['result']
        self.assertEqual(taken[1:], ['taken', True])
        self.assertIn('Another app uses this shortcut', taken[0])
        self.assertEqual(own, ['That’s already your Atticus shortcut. Kept your old one.', 'warn', ''])

    def test_one_long_asks_choice_replaces_the_start_agents_switch(self):
        sys.path.insert(0, str(ROOT)); import atticus
        self.assertNotIn('agentsAuto', (ROOT / 'ui/settings.html').read_text())
        self.assertNotIn('agentsAuto', atticus.switches())
        name, options = atticus.picks()['longAsks']
        self.assertEqual((name, options), ('Long asks', {'Ask me': 'ask', 'Move by itself': 'auto', 'Never ask': 'never'}))
        with patch.dict(os.environ, {'ATTICUS_ASK': ''}), contextlib.redirect_stdout(io.StringIO()) as said:
            atticus.set_switch('start agents without asking', 'move by itself')
        self.assertEqual(said.getvalue().strip(), 'Long asks is now Move by itself.')
        self.assertEqual(atticus.picks()['dictateMode'][1], {'Verbatim': 'verbatim', 'Clean up': 'cleanup'})

    def test_scheduled_routines_list_and_remove(self):
        out = self.page("""st.load({prefs:{hotkeyLabel:'⌃⌥Space'},routines:[
              {id:'weekday',kind:'time',at:'08:00',days:'weekdays',ask:'Summarize my calendar'},
              {id:'hourly',kind:'interval',every:3600,ask:'Check the fixture'}]});
            const labels=[...$('routines').querySelectorAll('.t b')].map(e=>e.textContent);
            $('routines').querySelector('.x').click(); return labels;""")
        self.assertEqual(out['result'], ['Weekdays at 8:00 AM', 'Every hour'])
        self.assertIn({'do': 'routineRemove', 'id': 'weekday'}, out['posts'])

    def test_single_deletes_wait_for_undo(self):
        out = self.page('''const row = () => document.querySelector('#rules [data-i="0"]').closest('.row');
            document.querySelector('#rules [data-i="0"]').click(); const hidden = row().hidden;
            $('noticebtn').click(); const back = !row().hidden;
            document.querySelector('[data-profile-drop="f1"]').click();
            document.querySelector('[data-u="0"]').click();   // a second delete sends the first
            const closing = st.flush(); await tick(30);
            return [hidden, back, closing];''')
        hidden, back, closing = out['result']
        self.assertTrue(hidden and back)
        self.assertEqual(closing, {'do': 'unlearn', 'say': 'focus mode'})
        self.assertEqual([p for p in out['posts'] if p.get('do') in ('forget', 'me', 'unlearn')], [{'do': 'me', 'action': 'drop', 'id': 'f1'}])

    def test_custom_server_says_whether_it_answered(self):
        out = self.page('''$('apiBase').value = 'http://localhost:1'; $('apiBase').onchange(); const checking = $('srvnote').textContent;
            st.models({base: P.apiBase, key: P.apiKey || '', list: []}); const none = $('srvnote').textContent;
            st.models({base: P.apiBase, key: P.apiKey || '', list: ['m1', 'm2']}); return [checking, none, $('srvnote').textContent, P.apiModel];''')
        checking, none, found, model = out['result']
        self.assertEqual(checking, 'Checking the server…')
        self.assertIn('No models found there', none)
        self.assertTrue(found.startswith('Found 2 models') and model == 'm1')
        self.assertIn({'do': 'models'}, out['posts'])

    def test_running_local_server_can_fill_address_and_model(self):
        out = self.page("""P.client='pi'; st.local([{name:'Ollama',base:'http://localhost:11434',models:['qwen3']}]);
            const offered=!$('localserver').hidden&&$('uselocal').textContent==='Use Ollama';
            $('uselocal').click(); return [offered,P.client,P.apiBase,P.apiModel,$('localserver').hidden];""")
        self.assertEqual(out['result'], [True, 'claude', 'http://localhost:11434', 'qwen3', True])
        self.assertIn({'do': 'set', 'k': 'client', 'v': 'claude'}, out['posts'])
        self.assertIn({'do': 'set', 'k': 'apiBase', 'v': 'http://localhost:11434'}, out['posts'])
        self.assertIn({'do': 'set', 'k': 'apiModel', 'v': 'qwen3'}, out['posts'])

    def test_pi_client_explains_its_provider_and_hides_claude_models(self):
        out = self.page("""st.load({prefs:{client:'pi',hotkeyLabel:'⌃⌥Space'}});
            const model=document.querySelector('[data-k=model]').closest('.row');
            return [$('brainlede').textContent,$('clientwhy').textContent,model.hidden,$('planname').textContent,$('safenote').textContent,$('agentsettings').hidden];""")
        lede, why, hidden, plan, safety, agents_hidden = out['result']
        self.assertIn('selected in Pi', lede)
        self.assertIn('local models', why)
        self.assertTrue(hidden)
        self.assertEqual(plan, 'Pi')
        self.assertIn('approval', safety)
        self.assertTrue(agents_hidden)

    def test_sections_open_at_top_and_dependent_rows_grey_out_in_place(self):
        out = self.page("""const main=document.querySelector('main');st.tab('brain');main.scrollTop=300;const scrolled=main.scrollTop>0;
            st.tab('screen');st.tab('brain');const top=main.scrollTop;
            st.load({prefs:{hotkeyLabel:'⌃⌥Space',quietAudio:false,ahead:false,instant:false}});
            const rows=['quietLevel','aheadDelay','live'].map(k=>document.querySelector(`[data-k=${k}]`).closest('.row'));
            const off=rows.map(r=>!r.hidden&&r.classList.contains('dim'));
            st.load({prefs:{hotkeyLabel:'⌃⌥Space',quietAudio:true,ahead:true,instant:true}});
            return [scrolled,top,off,rows.map(r=>r.classList.contains('dim')),document.querySelector('[data-k=quietLevel]').disabled];""")
        scrolled, top, off, on, disabled = out['result']
        self.assertTrue(scrolled)
        self.assertEqual(top, 0)
        self.assertEqual(off, [True, True, True])
        self.assertEqual(on, [False, False, False])
        self.assertFalse(disabled)

    def test_stale_server_models_cannot_change_the_current_model(self):
        out = self.page("""P.apiBase='server-b'; P.apiKey='key-b';
            st.models({base:'server-b',key:'key-b',list:['b']});
            st.models({base:'server-a',key:'key-a',list:['a']});
            st.models({base:'server-b',key:'old-key',list:['old']});
            return [P.apiModel, $('apimodels').options[0].value, $('srvnote').textContent];""")
        self.assertEqual(out['result'][0:2], ['b', 'b'])
        self.assertIn('Found 1 model', out['result'][2])
        self.assertFalse(any(p.get('value') in ('a', 'old') for p in out['posts']))

    def test_history_lists_searches_and_copies_answers(self):
        out = self.page('''st.state({today: use, week: use, all: use, rules: [], skills: [], me: {facts: []}, plan: {ok: true, text: ''},
              asks: [{at: '2026-10-15 09:30:00', task: 'weather', reply: 'Sunny'}, {at: '2026-10-14 08:00:00', task: 'open notes', reply: 'Opened Notes'}]});
            const all = $('asklist').querySelectorAll('.row').length;
            $('askq').value = 'notes'; $('askq').oninput(); const rows = [...$('asklist').querySelectorAll('.row b')].map(b => b.textContent);
            $('asklist').querySelector('.btn').click(); return [all, rows];''')
        self.assertEqual(out['result'], [2, ['open notes']])
        self.assertIn({'do': 'copy', 'text': 'Opened Notes'}, out['posts'])

    def test_import_failure_offers_the_settings_that_fix_it(self):
        out = self.page('''st.profileImport({errors: ['mail'], errorReasons: {mail:'automation'}, counts: {contacts: 3}}); const one = $('profileStatus').textContent;
            $('profileStatus').querySelector('.btn').click();
            st.profileImport({errors: ['contacts', 'mail'], errorReasons: {contacts:'automation',mail:'automation'}, counts: {}}); return [one, $('profileStatus').textContent];''')
        one, both = out['result']
        self.assertIn('3 from Contacts', one); self.assertIn('Allow Mail in Automation', one)
        self.assertIn('Allow Contacts and Mail in Automation', both)
        self.assertIn({'do': 'automation'}, out['posts'])

    def test_import_read_failure_offers_retry_without_false_permission_action(self):
        out = self.page("""st.profileImport({errors:['contacts','mail'],errorReasons:{contacts:'read',mail:'automation'},counts:{}});
            const mixed=$('profileStatus').textContent;
            st.profileImport({errors:['mail'],errorReasons:{mail:'read'},counts:{contacts:2}});
            return [mixed,$('profileStatus').textContent,$('profileStatus').querySelectorAll('.btn').length];""")
        self.assertIn('Allow Mail in Automation', out['result'][0])
        self.assertNotIn('Allow Contacts', out['result'][0])
        self.assertIn('Try importing again', out['result'][1])
        self.assertEqual(out['result'][2], 0)

    def test_state_lists_recent_answers_newest_first(self):
        sys.path.insert(0, str(ROOT)); import atticus
        rows = [{'at': '2026-10-14 08:00:00', 'task': 'open notes', 'reply': 'Opened Notes', 'usd': 0, 'secs': 1},
                {'id': '1-1', 'at': '2026-10-15 09:00:00', 'task': 'weather', 'status': 'running', 'pid': os.getpid()},   # a checkpoint with no answer yet
                {'at': '2026-10-15 09:30:00', 'task': 'weather', 'reply': 'Sunny', 'usd': 0, 'secs': 1}]
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'log.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
            with patch.object(atticus, 'DIR', root), patch.object(atticus, 'MEMORY', str(Path(root) / 'memory.md')), \
                 patch.object(atticus, 'SKILLS', str(Path(root) / 'skills.json')), patch.object(atticus, 'plan', return_value={}), \
                 patch.object(atticus, 'me', return_value={}), patch('sys.argv', ['atticus.py', '--state']), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                atticus.main()
        self.assertEqual([(a['task'], a['reply']) for a in json.loads(out.getvalue())['asks']], [('weather', 'Sunny'), ('open notes', 'Opened Notes')])


if __name__ == '__main__':
    unittest.main()

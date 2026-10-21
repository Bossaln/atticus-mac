"""Local dictation storage and conservative corrections; no UI, mic, apps or model calls."""
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]


class DictationDataTests(unittest.TestCase):
    def test_private_bounded_history_stats_and_dictionary(self):
        source = (ROOT / 'Atticus.swift').read_text()
        store = source[source.index('enum DictationData {'):source.index('enum Prefs {')]
        swift = r'''import Foundation
struct Prefs {
    static let path = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).path + "/settings.json"
    static var d: [String: Any] = ["dictateHistory": true]
    static func bool(_ k: String) -> Bool { d[k] as? Bool ?? false }
    static func set(_ k: String, _ v: Any) -> Bool { d[k] = v; return true }
}
''' + store + r'''
defer { try? FileManager.default.removeItem(atPath: (Prefs.path as NSString).deletingLastPathComponent) }
precondition(DictationData.word("Saarth"))
precondition(DictationData.word("Saarth") && DictationData.words == ["Saarth"])
precondition(DictationData.word("Atticus", replacing: "Saarth") && DictationData.words == ["Atticus"])
precondition(!DictationData.word("\n") && !DictationData.word("bad\nword") && !DictationData.word(String(repeating:"a", count:81)))
precondition(DictationData.record("Three final words", raw: "um Three final words", app: "Example", seconds: 1))
let row = DictationData.archive.history[0]
precondition(row.raw == "um Three final words" && row.app == "Example" && row.text == "Three final words")
let attr = try! FileManager.default.attributesOfItem(atPath: DictationData.path)
precondition((attr[.posixPermissions] as! NSNumber).intValue == 0o600)
let folder = try! FileManager.default.attributesOfItem(atPath: (Prefs.path as NSString).deletingLastPathComponent)
precondition((folder[.posixPermissions] as! NSNumber).intValue == 0o700)
let decoded = try! JSONDecoder().decode(DictationData.Archive.self, from: Data(contentsOf: URL(fileURLWithPath: DictationData.path)))
precondition(decoded.history.count == 1 && decoded.words == 3 && decoded.todayWords == 3)
Prefs.set("dictateHistory", false)
precondition(DictationData.record("No stored text", raw: "No stored text", app: "Private", seconds: 1))
precondition(DictationData.archive.history.count == 1 && DictationData.archive.words == 6 && DictationData.archive.sessions == 2)
DictationData.archive.history = []; precondition(DictationData.save())
precondition(DictationData.archive.words == 6)
DictationData.archive.day = "2000-01-01"
precondition((DictationData.state()["stats"] as! [String: Int])["today"] == 0)
precondition(DictationData.record("New day", raw: "New day", app: "Example", seconds: 0))
precondition(DictationData.archive.todayWords == 2 && DictationData.archive.words == 8)
let recent = DictationData.Entry(id:"new", timestamp:Date().timeIntervalSince1970, app:"A", text:"B", raw:nil)
let expired = DictationData.Entry(id:"old", timestamp:Date().timeIntervalSince1970 - 31 * 86400, app:"A", text:"B", raw:nil)
DictationData.archive.history = [expired] + Array(repeating:recent, count:501)
DictationData.prune()
precondition(DictationData.archive.history.count == 500 && !DictationData.archive.history.contains { $0.id == "old" })
precondition(DictationData.save())
// A failed write must leave the previous in-memory totals intact.
let count = DictationData.archive.words
try! FileManager.default.removeItem(atPath: (Prefs.path as NSString).deletingLastPathComponent)
try! Data().write(to: URL(fileURLWithPath: (Prefs.path as NSString).deletingLastPathComponent))
precondition(!DictationData.record("failure", raw:"failure", app:"A", seconds:0))
precondition(DictationData.archive.words == count)
print("private dictation data ok")
'''
        self.assertIn('private dictation data ok', run_swift(self, swift))

    def test_corrections_are_single_words_and_reject_rewrites(self):
        source = (ROOT / 'Atticus.swift').read_text()
        store = source[source.index('enum DictationData {'):source.index('enum Prefs {')]
        swift = r'''import Foundation
struct Prefs {
    static var path = "/tmp/unused-atticus-dictation-test/settings.json"
    static var d: [String: Any] = [:]
    static func bool(_ k: String) -> Bool { false }
    static func set(_ k: String, _ v: Any) -> Bool { true }
}
''' + store + r'''
precondition(DictationData.correction("Hello Sarth.", "Hello Saarth.") == "Saarth")
precondition(DictationData.correction("open atticus", "open Atticus") == "Atticus")
precondition(DictationData.correction("Hi Andree", "Hi André") == "André")
for text in ["Hello", "Hello Sarth. again", "Changed everything.", "Hello 123.", "Hello Sarth.", "Hi Saarth."] {
    precondition(DictationData.correction("Hello Sarth.", text) == nil, text)
}
print("correction bounds ok")
'''
        self.assertIn('correction bounds ok', run_swift(self, swift))

    def test_dictionary_reaches_cleanup_and_keeps_saved_rules(self):
        import atticus
        with patch.object(atticus, 'pref', return_value=['Saarth', 'Atticus', None, 'bad\nword']), \
             patch.object(atticus, 'relevant_rules', return_value='Spell my name Saarth.'):
            request = atticus.dictate_request('say Sarth')
            self.assertIn('["Saarth", "Atticus"]', request)
            self.assertIn('Spell my name Saarth.', request)
            self.assertNotIn('bad', request)
            self.assertEqual(atticus.dictate_result('say Sarth', '<cleaned>Say Saarth.</cleaned>', request), 'Say Saarth.')

    def test_correction_window_is_scoped_and_secure_before_read(self):
        source = (ROOT / 'Atticus.swift').read_text()
        monitor = source[source.index('    func prepareDictation('):source.index('    func stopDictationCleanup(')]
        for guard in ['addingTimeInterval(20)', 'dictateID == id', '!engine.isRunning', '!busy',
                      'frontmostApplication == target.app', 'CFEqual(focused, target.focus)',
                      'current.hasPrefix(prefix)', 'current.hasSuffix(suffix)', 'timer.invalidate()']:
            self.assertIn(guard, monitor)
        self.assertLess(monitor.index('kAXSecureTextFieldSubrole'), monitor.index('target.value'))
        poll = monitor[monitor.index('Timer.scheduledTimer'):]
        self.assertLess(poll.index('kAXSecureTextFieldSubrole'), poll.index('target.value'))
        self.assertNotIn('addGlobalMonitor', monitor)
        capture = source[source.index('    static func capture('):source.index('    var caret:')]
        self.assertLess(capture.index('kAXSecureTextFieldSubrole'), capture.index('kAXValueAttribute'))
        session = source[source.index('    func captureDictationSelection()'):source.index('    func start()')]
        self.assertIn('onSecure: { secureField = true }', session)
        self.assertLess(session.index('if secureField'), session.index('dictateSelectionPending = false'))
        self.assertIn('hush(); js("dictated"', session)
        self.assertIn('guard let selected else', session)
        self.assertIn('dictateSelection = selected', session)
        self.assertNotIn('selected.text.count <= 6000', session)
        self.assertIn('Click an editable text field, then try dictation again', session)
        start = source[source.index('    func start(dictate: Bool)'):source.index('    func heard(')]
        self.assertLess(start.index('if dictate && !AXIsProcessTrusted()'), start.index('captureDictationSelection()'))
        self.assertIn('Allow Accessibility in System Settings → Privacy & Security → Accessibility', start)


@unittest.skipUnless(shutil.which('node'), 'Node UI logic check')
class DictationUIDataTests(unittest.TestCase):
    def test_dictionary_and_history_actions_use_text_and_search_raw(self):
        page = (ROOT / 'ui/settings.html').read_text()
        code = page[page.index('  const svg = d =>'):page.index("  $('agentsnav').onclick")]
        script = r'''const assert = (x, m) => { if (!x) throw Error(m); };
class Element {
  constructor() { this.children = []; this.value = ''; this.style = {}; }
  append(...x) { this.children.push(...x); }
  replaceChildren(...x) { this.children = x; }
  setAttribute() {}
}
const ids = new Map(), $ = id => { if (!ids.has(id)) ids.set(id, new Element()); return ids.get(id); };
const document = {createElement: () => new Element()}, posts = [];
const post = m => posts.push(m);
let action;
const showNotice = (text, label, run) => { action = run; };
''' + code + r'''
dictations = {words:['<Saarth>'], history:[{id:'1',timestamp:1,app:'Editor',text:'Final <text>',raw:'Raw Sarth'},{id:'2',timestamp:2,app:'Chat',text:'Other text'}], stats:{today:2, words:9, minutes:1, sessions:2}};
paintDictation();
assert([$('dstoday'), $('dsall'), $('dssaved'), $('dssavedunit'), $('dssessions')].map(e => String(e.textContent)).join() === '2,9,1,minutes,2', 'stats absent');
dictations.stats = {today: 0, words: 12345, minutes: 90, sessions: 1}; paintDictation();
assert($('dsall').textContent === '12,345' && $('dssaved').textContent === '1.5' && $('dssavedunit').textContent === 'hours', 'stats not formatted for long use');
const word = $('dictationwords').children[0];
assert(word.children[0].value === '<Saarth>', 'dictionary did not preserve literal text');
assert(word.children[1].hidden === true, 'save icon showed before an edit');
word.children[0].value = 'Saarth'; word.children[0].oninput(); assert(word.children[1].hidden === false, 'save icon hidden after an edit');
word.onsubmit({preventDefault(){}});
assert(posts.at(-1).word === 'Saarth' && posts.at(-1).old === '<Saarth>', 'edit lost original word');
word.children[2].onclick(); assert(posts.at(-1).do === 'dictationWordDelete', 'remove not wired');
$('dictationsearch').value = 'raw sarth'; $('dictationsearch').oninput();
assert($('dictationhistory').children.length === 1, 'raw transcript not searchable');
let row = $('dictationhistory').children[0];
assert(row.children[0].children[1].textContent === 'Final <text>', 'history text did not stay literal');
row.children[1].onclick(); assert(posts.at(-1).do === 'copy' && posts.at(-1).text === 'Final <text>', 'copy not wired');
row.children[2].onclick(); assert(posts.at(-1).do === 'dictationDelete' && posts.at(-1).id === '1', 'delete lost row id');
$('dictationsearch').value = 'chat'; $('dictationsearch').oninput();
assert($('dictationhistory').children.length === 1, 'app not searchable');
const count = posts.length; $('dictationclear').onclick();
assert(posts.length === count, 'clear all did not wait for click');
action(); assert(posts.at(-1).do === 'dictationClear', 'clear all not wired');
$('dictationword').value = 'New'; $('dictationadd').onsubmit({preventDefault(){}});
assert(posts.at(-1).word === 'New' && $('dictationword').value === '', 'add not wired');
dictations = {words: [], history: [], stats: {}}; $('dictationsearch').value = ''; paintDictation();
assert($('dictationwords').hidden && $('dictationnote').textContent.startsWith('No words yet'), 'empty dictionary not a quiet line');
assert($('dictationhistory').children.length === 1 && $('dictationhistory').children[0].className === 'empty', 'empty history not a quiet line');
'''
        result = subprocess.run(['node'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_learned_toast_undo_posts_and_disables_its_button(self):
        page = (ROOT / 'ui/ui.html').read_text()
        method = page[page.index('    learned(word)'):page.index('    line(l)')]
        script = r'''let label, sent, button;
const note = text => { label = text; }, fit = () => {};
const document = {createElement: () => ({})}, part = () => ({remove() {}, append: (...args) => { button = args[1]; }});
const post = message => { sent = message; };
const ui = {''' + method + r'''};
ui.learned('Saarth'); button.onclick();
if (label !== "Learned 'Saarth'" || !button.disabled || !sent.learnedUndo) throw Error('learned undo failed');
'''
        result = subprocess.run(['node'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()

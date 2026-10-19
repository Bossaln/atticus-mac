"""Dictation routing and delivery with fake model, focus, and selection targets."""
import io
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]


class DictationCleanupTests(unittest.TestCase):
    def test_cleanup_is_one_bounded_cheapest_call(self):
        sys.path.insert(0, str(ROOT))
        import atticus
        with patch.object(atticus, 'relevant_rules', return_value='Spell my name Saarth.'), \
             patch.object(atticus, 'meeting_call', return_value=('<cleaned>Clean text.</cleaned>', {})) as call:
            self.assertEqual(atticus.dictate_cleanup('um Clean text. ' + 'x' * 7000), 'Clean text.')
        self.assertEqual(call.call_count, 1)
        args, kwargs = call.call_args
        self.assertEqual(kwargs['model'], 'haiku')
        self.assertEqual(kwargs['label'], 'Dictation cleanup')
        self.assertIn('Spell my name Saarth.', args[1])
        self.assertLessEqual(len(args[1]), 7100)
        with patch.object(atticus, 'meeting_call') as empty:
            self.assertEqual(atticus.dictate_cleanup('   '), '')
            empty.assert_not_called()

    def test_cleanup_accepts_small_grammar_and_saved_spelling_edits(self):
        import atticus
        self.assertEqual(atticus.dictate_result('he go to school', '<cleaned>He goes to school.</cleaned>'), 'He goes to school.')
        with patch.object(atticus, 'relevant_rules', return_value='Spell my name Saarth.'), \
             patch.object(atticus, 'meeting_call', return_value=('<cleaned>My name is Saarth.</cleaned>', {})):
            self.assertEqual(atticus.dictate_cleanup('My name is Sarth.'), 'My name is Saarth.')

    def test_non_claude_cleanup_falls_back_without_starting_claude(self):
        import atticus
        with patch.object(atticus, 'client', return_value='pi'), patch.object(atticus, 'meeting_call') as call:
            self.assertEqual(atticus.dictate_cleanup('Um, keep every word.'), 'keep every word.')
        call.assert_not_called()
        with patch.object(atticus, 'client', return_value='pi'), patch.object(atticus, 'meeting_process') as process, \
             patch('sys.stdin', io.StringIO('Um, keep every word.')), patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.dictate_cleanup_wait()
        process.assert_not_called()
        self.assertEqual(out.getvalue(), 'keep every word.\n')


@unittest.skipUnless(sys.platform == 'darwin', 'macOS Swift regression')
class DictationNativeTests(unittest.TestCase):
    def test_verbatim_skips_ai_cleanup_uses_one_call_and_cancel_drops_result(self):
        source = (ROOT / 'Atticus.swift').read_text()
        start = source[source.index('    func start(dictate: Bool)'):source.index('    func heard(')]
        self.assertIn('if !dictate && !replying { unwarm(); warm = spawn() }', start)
        self.assertIn('if dictateCleanup { warmDictationCleanup() }', start)
        method = source[source.index('    func stopDictationCleanup()'):source.index('    func dictationDeliveryFailed(')]
        swift = r'''import Foundation
var processCalls = 0
func py(_ args: [String], _ extra: [String: String] = [:]) -> Process {
    precondition(args == ["--dictate-cleanup-wait"])
    processCalls += 1
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/bin/cat"); return p
}
struct Selection { let text: String }
final class Harness {
    var dictateSelectionPending = false, dictateCleanup = false, busy = true, dictating = true
    var dictateID = 1, text = "Exact words.", inserted: [String] = []
    var dictateSelection: Selection?, dictateProcess: Process?, dictateInput: FileHandle?, dictateOutput: FileHandle?
    func insertDictation(_ value: String) { inserted.append(value); busy = false; dictating = false }
    func dictationDeliveryFailed(_ value: String, cleanup: Bool = false) { busy = false; dictating = false }
    func cue(_ value: String) {}
    func hide(after: Double) {}
''' + method + r'''}
func pump(_ seconds: Double) {
    let end = Date().addingTimeInterval(seconds)
    while Date() < end { RunLoop.current.run(until: Date().addingTimeInterval(0.005)) }
}
let verbatim = Harness()
verbatim.finishDictation()
precondition(verbatim.inserted == ["Exact words."] && processCalls == 0, "verbatim called AI or changed the transcript")
let clean = Harness(); clean.dictateCleanup = true; clean.dictateSelection = Selection(text: "um selected words")
clean.warmDictationCleanup(); clean.finishDictation(); pump(0.5)
precondition(clean.inserted == ["Exact words."] && processCalls == 1, "cleanup did not use exactly one call or threw away the speech")
let cancelled = Harness(); cancelled.dictateCleanup = true
cancelled.warmDictationCleanup(); cancelled.finishDictation(); cancelled.dictateID += 1; cancelled.dictateProcess?.terminate(); pump(0.5)
precondition(cancelled.inserted.isEmpty && processCalls == 2, "cancelled cleanup inserted late output")
print("dictation routing ok")
'''
        self.assertIn('dictation routing ok', run_swift(self, swift))

    def test_selection_is_replaced_only_while_original_app_stays_front(self):
        source = (ROOT / 'Atticus.swift').read_text()
        method = source[source.index('    func insertDictation('):source.index('    func typed(')]
        swift = r'''import Foundation
struct Prefs { static func bool(_ key: String) -> Bool { false } }
final class AppRef: Equatable {
    let id: Int
    init(_ id: Int) { self.id = id }
    static func == (a: AppRef, b: AppRef) -> Bool { a.id == b.id }
}
final class NSWorkspace {
    static let shared = NSWorkspace()
    var frontmostApplication: AppRef?
}
final class Target {
    let app: AppRef
    var received: [String] = [], preserved = false, deferred = false
    var pending: (() -> Void)?
    init(_ app: AppRef) { self.app = app }
    func apply(_ draft: String, preserveFocus: Bool = false, valid: @escaping () -> Bool, done: @escaping (Bool) -> Void) {
        preserved = preserveFocus
        let work = { [self] in let ok = valid(); if ok { received.append(draft) }; done(ok) }
        if deferred { pending = work } else { work() }
    }
}
final class Harness {
    var dictateSelection: Target?, busy = true, dictating = true, dictateID = 1
    var failed: [String] = []
    func cue(_ value: String) {}
    func js(_ call: String, _ arg: Any? = nil) {}
    func hide(after: Double) {}
    func dictationDeliveryFailed(_ value: String) { failed.append(value); busy = false; dictating = false }
''' + method + r'''}
let user = AppRef(1), other = AppRef(2), target = Target(user), h = Harness()
h.dictateSelection = target; NSWorkspace.shared.frontmostApplication = user
h.insertDictation("replacement")
precondition(target.received == ["replacement"] && target.preserved, "selected text was not replaced through the focus-preserving path")
let missing = Harness(); missing.insertDictation("copy me")
precondition(missing.failed == ["copy me"], "missing target lost the transcript")
let moved = Target(user), h2 = Harness(); h2.dictateSelection = moved; NSWorkspace.shared.frontmostApplication = other
h2.insertDictation("wrong")
precondition(moved.received.isEmpty && h2.failed == ["wrong"] && NSWorkspace.shared.frontmostApplication == other, "dictation stole focus, typed into the old app, or lost the transcript")
let late = Target(user), h3 = Harness(); late.deferred = true; h3.dictateSelection = late; NSWorkspace.shared.frontmostApplication = user
h3.insertDictation("late"); h3.dictateID += 1; h3.dictating = false; late.pending?()
precondition(late.received.isEmpty, "cancelled dictation replaced the selection")
print("dictation target safety ok")
'''
        self.assertIn('dictation target safety ok', run_swift(self, swift))

    def test_delivery_retries_only_a_proven_failure_and_keeps_failed_text(self):
        source = (ROOT / 'Atticus.swift').read_text()
        apply = source[source.index('    func apply(_ draft:'):source.index('    var value:', source.index('    func apply(_ draft:'))]
        insert = source[source.index('    func dictationDeliveryFailed('):source.index('    func typed(')]
        self.assertIn('case .unchanged: fallback()', apply)
        self.assertIn('case .unknown: done(false)', apply)
        self.assertEqual(apply.count('.post(tap: .cghidEventTap)'), 1)
        self.assertNotIn('postToPid', apply)
        self.assertIn('Copied — paste with ⌘V', insert)
        swift = r'''import Foundation
enum Delivery { case landed, unchanged, unknown }
final class FakeTarget {
    var writes = 0, pastes = 0, copied = ""
    func deliver(_ afterWrite: Delivery, _ afterPaste: Delivery, _ text: String) -> Bool {
        writes += 1
        switch afterWrite {
        case .landed: return true
        case .unchanged:
            pastes += 1
            if afterPaste == .landed { return true }
            copied = text; return false
        case .unknown:
            copied = text; return false
        }
    }
}
let delayed = FakeTarget()
precondition(delayed.deliver(.landed, .unknown, "one") && delayed.writes == 1 && delayed.pastes == 0,
             "a delayed verified AX write was pasted twice")
let rejected = FakeTarget()
precondition(rejected.deliver(.unchanged, .landed, "two") && rejected.writes == 1 && rejected.pastes == 1,
             "a proven rejected AX write did not fall back once")
let unknown = FakeTarget()
precondition(!unknown.deliver(.unknown, .landed, "never lose me") && unknown.pastes == 0 && unknown.copied == "never lose me",
             "an unverifiable write retried or lost the transcript")
print("single delivery fallback ok")
'''
        self.assertIn('single delivery fallback ok', run_swift(self, swift))

    def test_verbatim_release_budget_with_fake_finalizer(self):
        source = (ROOT / 'Atticus.swift').read_text()
        settle = float(source.split('static let settle: TimeInterval = ', 1)[1].splitlines()[0])
        self.assertIn('(dictating ? 0.35 : 2)', source)
        swift = f'''import Foundation
let release = Date()
var inserted: TimeInterval?
DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {{
    DispatchQueue.main.asyncAfter(deadline: .now() + {settle * 2}) {{ inserted = Date().timeIntervalSince(release) }}
}}
let end = Date().addingTimeInterval(0.8)
while inserted == nil && Date() < end {{ RunLoop.current.run(until: Date().addingTimeInterval(0.005)) }}
precondition(inserted != nil && inserted! < 0.6, "verbatim release path exceeded its bounded fake budget")
print(String(format: "fake release-to-insert %.3f", inserted!))
'''
        out = run_swift(self, swift)
        self.assertIn('fake release-to-insert', out)

    def test_fn_and_modifier_only_shortcuts_use_flags_events(self):
        source = (ROOT / 'Atticus.swift').read_text()
        helpers = source[source.index('let atticusFnKey'):source.index('func configuredHotkey')]
        recorder = source[source.index('    // "Change shortcut"'):source.index('    func done(', source.index('    // "Change shortcut"'))]
        registration_start = source.index('var specialGlobalHotkeys')
        registration = source[registration_start:source.index('if Prefs.bool("speak")', registration_start)]
        self.assertIn('done((-2, shortcutModifiers(held)', recorder)
        self.assertIn('.function', recorder)
        self.assertIn('addGlobalMonitorForEvents', registration)
        self.assertIn('addLocalMonitorForEvents', registration)
        swift = 'import Cocoa\nimport Carbon\n' + helpers + r'''
let chord: NSEvent.ModifierFlags = [.function, .control]
precondition(shortcutModifiers(chord) & atticusFnKey != 0)
precondition(shortcutModifiers(chord) & controlKey != 0)
precondition(shortcutModifierLabel(chord) == "fn⌃")
print("fn modifier shortcut ok")
'''
        self.assertIn('fn modifier shortcut ok', run_swift(self, swift))

    def test_overlay_states_follow_release_done_fallback_fail_and_cancel(self):
        source = (ROOT / 'Atticus.swift').read_text()
        at = source.index('    func stop()', source.index('final class App'))
        release = next(l for l in source[at:source.index('    func applyReplacement(')].splitlines() if 'js("finishing"' in l)
        escape = source[source.index('    func escape()'):source.index('    func hush()')]
        self.assertLess(escape.index('if dictating { return cancel() }'), escape.index('if engine.isRunning'))
        delivery = source[source.index('    func dictationDeliveryFailed('):source.index('    func typed(')]
        cancel = source[source.index('    func cancel()'):source.index('    // ✕ also ends')]
        swift = r'''import Foundation
struct Prefs { static func bool(_ key: String) -> Bool { false } }
final class AppRef: Equatable { static func == (a: AppRef, b: AppRef) -> Bool { a === b } }
final class NSWorkspace { static let shared = NSWorkspace(); var frontmostApplication: AppRef? }
enum PasteType { case string }
final class NSPasteboard {
    static let general = NSPasteboard()
    var works = true, copied = ""
    func clearContents() {}
    func setString(_ s: String, forType: PasteType) -> Bool { if works { copied = s }; return works }
}
final class Target {
    let app: AppRef; var received: [String] = [], deferred = false, pending: (() -> Void)?
    init(_ app: AppRef) { self.app = app }
    func apply(_ draft: String, preserveFocus: Bool = false, valid: @escaping () -> Bool, done: @escaping (Bool) -> Void) {
        let work = { [self] in let ok = valid(); if ok { received.append(draft) }; done(ok) }
        if deferred { pending = work } else { work() }
    }
}
final class Harness {
    var dictateSelection: Target?, busy = false, dictating = true, dictateID = 1, dictateCleanup = false
    var log: [String] = [], hides: [Double] = []
    func cue(_ value: String) {}
    func hide(after s: Double) { hides.append(s) }
    func js(_ call: String, _ arg: Any? = nil) {
        if let d = arg as? [String: Any] { log.append("\(call) \(d["text"]!) \(d["ok"]!)") } else { log.append("\(call) \(arg as? String ?? "")") }
    }
    func hush() { dictating = false; dictateID += 1; busy = false }
    func shush() {}
    func close(clear: Bool) { log.append("close"); hush() }
    func release() { busy = true
''' + release + '\n    }\n' + delivery + cancel + r'''}
let user = AppRef(); NSWorkspace.shared.frontmostApplication = user
let done = Harness(); done.dictateSelection = Target(user); done.release(); done.insertDictation("hi")
precondition(done.log == ["finishing ", "dictated Inserted true"] && done.hides == [0.6], "done: \(done.log)")
let clean = Harness(); clean.dictateCleanup = true; clean.release()
precondition(clean.log == ["finishing Cleaning up…"], "Clean up mode did not label its wait")
let fallback = Harness(); fallback.release(); fallback.insertDictation("copy me")
precondition(fallback.log == ["finishing ", "dictated Copied — paste with ⌘V true"] && NSPasteboard.general.copied == "copy me" && fallback.hides == [3], "fallback: \(fallback.log)")
NSPasteboard.general.works = false
let fail = Harness(); fail.release(); fail.insertDictation("keep me")
precondition(fail.log == ["finishing ", "dictated Couldn’t insert. Your words are still here. false"] && fail.hides.isEmpty, "fail: \(fail.log)")
NSPasteboard.general.works = true
let cleanupFail = Harness(); cleanupFail.dictationDeliveryFailed("raw words", cleanup: true)
precondition(cleanupFail.log == ["dictated Couldn’t clean up. Copied — paste with ⌘V false"] && NSPasteboard.general.copied == "raw words", "cleanup failure lost the words")
let late = Target(user); late.deferred = true
let cancelled = Harness(); cancelled.dictateSelection = late; cancelled.release(); cancelled.insertDictation("never"); cancelled.cancel(); late.pending?()
precondition(cancelled.log == ["finishing ", "close"] && late.received.isEmpty && cancelled.hides.isEmpty, "cancel: \(cancelled.log)")
print("dictation states ok")
'''
        self.assertIn('dictation states ok', run_swift(self, swift))


@unittest.skipUnless(shutil.which('node'), 'Node runs the overlay state check')
class DictationOverlayTests(unittest.TestCase):
    page = (ROOT / 'ui' / 'ui.html').read_text()

    def test_finishing_skips_fast_inserts_and_ends_with_the_real_wait(self):
        page = self.page
        helper = page[page.index('  let finishTimer = 0;'):page.index('\n  };\n', page.index('  let finishTimer = 0;')) + 5]
        methods = page[page.index('    finishing(label)'):page.index('    line(l)')]
        self.assertIn("if (document.body.classList.contains('dictate')) return window.ui.dictated({ text: s });", page)
        script = r'''
const set = () => { const s = new Set(); return { s, ever: new Set(), add(...c) { c.forEach(x => { s.add(x); this.ever.add(x); }); }, remove(...c) { c.forEach(x => s.delete(x)); }, contains: c => s.has(c) }; };
let states = [], q, turnEl;
const fresh = () => { q = { classList: set(), after(n) { turnEl.kids.push(n); } }; q.classList.add('q', 'live'); turnEl = { kids: [q], append(n) { this.kids.push(n); } }; states = ['listening']; };
const turn = () => turnEl, part = c => c === 'q' ? q : turnEl.kids.find(n => (n.className || '').split(' ').includes(c));
const $ = () => ({ style: {} }), setState = s => states.push(s), fit = () => {};
const document = { createElement: () => ({ className: '', textContent: '', setAttribute() {} }) };
let listening = true, boost = 2;
''' + helper + 'const ui = {\n' + methods + r'''};
const wait = ms => new Promise(r => setTimeout(r, ms)), fail = m => { console.error(m); process.exit(1); };
fresh(); ui.finishing('');
if (q.classList.contains('live') || q.classList.contains('finishing')) fail('release did not stop the caret at once, or flashed the shimmer');
await wait(60); ui.dictated({ text: 'Inserted', ok: true }); await wait(200);
if (q.classList.ever.has('finishing') || states.includes('solving')) fail('a fast Verbatim insert flashed the finishing state');
if (part('dn').textContent !== 'Inserted' || part('dn').className !== 'dn ok' || states.at(-1) !== 'breathing') fail('done state missing');
fresh(); ui.finishing(''); await wait(200);
if (!q.classList.contains('finishing') || states.at(-1) !== 'solving' || part('dn').textContent) fail('a slow Verbatim insert showed no finishing state, or a label');
ui.dictated({ text: 'Copied — paste with ⌘V', ok: true });
if (q.classList.contains('finishing') || part('dn').className !== 'dn ok' || states.join() !== 'listening,solving,breathing') fail('finishing outlived the real wait: ' + states);
fresh(); ui.finishing('Cleaning up…');
if (!q.classList.contains('finishing') || part('dn').textContent !== 'Cleaning up…') fail('Clean up mode did not show its wait in the same frame');
ui.dictated({ text: 'Couldn’t clean up. Copied — paste with ⌘V', ok: false });
if (part('dn').className !== 'dn' || q.classList.contains('finishing')) fail('failure was not one plain line');
fresh(); ui.finishing(''); const old = q; fresh(); await wait(200);
if (old.classList.ever.has('finishing') || states.includes('solving')) fail('a stale release timer touched the next dictation');
'''
        result = subprocess.run(['node', '--input-type=module'], input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_finishing_uses_transform_and_opacity_and_has_a_reduce_motion_path(self):
        page = self.page
        rule = re.search(r'\.q\.finishing::after \{(.*?)\}', page, re.S).group(1)
        for name in re.findall(r'animation: (.*?);', rule)[0].split(','):
            frames = re.search(r'@keyframes ' + name.split()[0] + r' \{(.*?)\}\s*\}?\n', page, re.S).group(1)
            self.assertEqual(set(re.findall(r'([a-z-]+):', frames)) - {'opacity', 'transform'}, set(), name)
        reduce = page[page.index('@media (prefers-reduced-motion: reduce)'):page.index('</style>')]
        self.assertIn('animation: none !important', reduce)
        self.assertIn('.q.finishing { opacity: .6; } .q.finishing::after { content: none; }', reduce)


if __name__ == '__main__':
    unittest.main()

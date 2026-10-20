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
    def test_cleanup_chunks_without_truncating_and_uses_cheapest(self):
        sys.path.insert(0, str(ROOT))
        import atticus
        with patch.object(atticus, 'relevant_rules', return_value='Spell my name Saarth.'), \
             patch.object(atticus, 'meeting_call', return_value=('<cleaned>Clean text.</cleaned>', {})) as call:
            cleaned = atticus.dictate_cleanup('um Clean text. ' + 'x' * 7000)
        self.assertTrue(cleaned.startswith('Clean text.\n'))
        self.assertTrue(cleaned.endswith('x' * 1000))
        self.assertEqual(call.call_count, 2)
        for args, kwargs in call.call_args_list:
            self.assertEqual(kwargs['model'], 'haiku')
            self.assertEqual(kwargs['label'], 'Dictation cleanup')
            self.assertIn('Spell my name Saarth.', args[1])
            self.assertLessEqual(len(args[1]), 7100)
        with patch.object(atticus, 'meeting_call') as empty:
            self.assertEqual(atticus.dictate_cleanup('   '), '')
            empty.assert_not_called()

    def test_cleanup_failure_keeps_all_text_and_removes_fillers_locally(self):
        import atticus
        source = 'I um need this. ' + ('word ' * 1400) + 'Uh, final words.'
        with patch.object(atticus, 'client', return_value='claude'), \
             patch.object(atticus, 'relevant_rules', return_value=''), \
             patch.object(atticus, 'meeting_call', side_effect=RuntimeError('offline')):
            cleaned = atticus.dictate_cleanup(source)
        self.assertIn('final words.', cleaned)
        self.assertNotRegex(cleaned.lower(), r'\b(?:um|uh)\b')
        self.assertGreater(len(cleaned), 6000)

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

    def test_short_dictation_skips_ai_and_cursor_text_reaches_cleanup(self):
        import atticus
        with patch.object(atticus, 'client', return_value='claude'), patch.object(atticus, 'meeting_call') as call:
            self.assertEqual(atticus.dictate_cleanup('Um, okay'), 'okay')
        call.assert_not_called()
        with patch.object(atticus, 'client', return_value='claude'), patch.object(atticus, 'meeting_process'), \
             patch.object(atticus, 'stop_claude'), patch.object(atticus, 'dictate_warmed') as warmed, \
             patch('sys.stdin', io.StringIO('Notes from Saarth\0uh I')), patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.dictate_cleanup_wait()
        warmed.assert_not_called()
        self.assertEqual(out.getvalue(), 'I\n')
        with patch.object(atticus, 'client', return_value='claude'), patch.object(atticus, 'meeting_process'), \
             patch.object(atticus, 'stop_claude'), patch.object(atticus, 'relevant_rules', return_value=''), \
             patch.object(atticus, 'dictate_warmed', return_value='Tell Saarth hi.') as warmed, \
             patch('sys.stdin', io.StringIO('Notes from Saarth\0tell sarth hi')), patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.dictate_cleanup_wait()
        self.assertEqual(out.getvalue(), 'Tell Saarth hi.\n')
        _, text, corrections = warmed.call_args.args
        self.assertEqual(text, 'tell sarth hi')
        self.assertIn('Text before the cursor: "Notes from Saarth"', corrections)

    def test_cleanup_start_failure_still_returns_local_cleanup(self):
        import atticus
        with patch.object(atticus, 'client', return_value='claude'), \
             patch.object(atticus, 'meeting_process', side_effect=OSError('missing')), \
             patch('sys.stdin', io.StringIO('I um need uh every word.')), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.dictate_cleanup_wait()
        self.assertEqual(out.getvalue(), 'I need every word.\n')


@unittest.skipUnless(sys.platform == 'darwin', 'macOS Swift regression')
class DictationNativeTests(unittest.TestCase):
    def test_long_dictation_rollover_stitches_overlap_without_doubling(self):
        source = (ROOT / 'Atticus.swift').read_text()
        helper = source[source.index('func stitchTranscript'):source.index('final class SpeechInputs')]
        swift = 'import Foundation\n' + helper + r'''
precondition(stitchTranscript("We should ship the release today", "the release today before lunch") == "We should ship the release today before lunch")
precondition(stitchTranscript("Keep punctuation, please.", "Punctuation please, and spacing.") == "Keep punctuation, please. and spacing.")
precondition(stitchTranscript("No shared ending", "Start fresh") == "No shared ending Start fresh")
precondition(stitchTranscript("", "First words") == "First words")
print("dictation stitching ok")
'''
        self.assertIn('dictation stitching ok', run_swift(self, swift))
        timer = source[source.index('Timer.scheduledTimer(withTimeInterval: 0.15'):source.index('    func heard(')]
        self.assertIn('rolloverSpeech(listeningID: listeningID)', timer)
        self.assertIn('if !dictating && held > 60', timer)

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
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/bin/sh")
    p.arguments = ["-c", "tr '\\000' '\\n' | tail -n 1"]   // the transcript after the cursor text's NUL
    return p
}
struct Selection { let text: String }
final class Harness {
    var dictateSelectionPending = false, dictateCleanup = false, busy = true, dictating = true
    var dictateID = 1, text = "Exact words.", inserted: [String] = [], dictateBefore = "Notes before the cursor."
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
    func hide(after: Double, shrink: Bool = false) {}
    func prepareDictation(_ value: String, target: Target) -> () -> Void { {} }
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
        self.assertIn('Saved to History', insert)
        self.assertNotIn('NSPasteboard', insert)   # dictation never leaves its words on the clipboard
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

    def test_release_waits_for_final_words_on_the_accurate_model(self):
        # Oct 19, 2026: a 0.35 s dictation guard inserted volatile words ("I", "I saw some stuff like.") before the final result.
        source = (ROOT / 'Atticus.swift').read_text()
        at = source.index('    func stop()', source.index('final class App'))
        stop = source[at:source.index('    func applyReplacement(')]
        guard = stop[stop.index('Finalizing can hang'):]
        self.assertLess(stop.index('finalizeAndFinishThroughEndOfInput()'), stop.index('Finalizing can hang'))
        self.assertIn('DispatchQueue.main.asyncAfter(deadline: .now() + 2)', guard)
        self.assertNotIn('dictating ?', guard[:guard.index('once(false)')])
        module = source[source.index('    func speechModule('):source.index('    func prepareSpeech(')]
        self.assertIn('let tr = speechModule(dictate: dictating)', source)
        self.assertIn('SpeechTranscriber(locale: en, transcriptionOptions: [], reportingOptions: [.volatileResults]', module)
        self.assertIn('transcriptionOptions: [.punctuation], reportingOptions: [.volatileResults]', module)

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

    def test_fn_alone_ignores_arrow_flags_and_yields_to_fn_key_chords(self):
        source = (ROOT / 'Atticus.swift').read_text()
        helpers = source[source.index('let atticusFnKey'):source.index('func configuredHotkey')]
        matcher = source[source.index('func specialHotkey'):source.index('func handleSpecialHotkeys')]
        swift = 'import Cocoa\nimport Carbon\n' + helpers + '\nvar specialGlobalHotkeys: Any?, specialLocalHotkeys: Any?, specialMainDown = false, specialDictateDown = false\n' + matcher + r'''
let fn = (code: -2, mods: atticusFnKey, flags: NSEvent.ModifierFlags.function)
func key(_ type: NSEvent.EventType, _ flags: NSEvent.ModifierFlags, _ code: UInt16) -> NSEvent {
    NSEvent.keyEvent(with: type, location: .zero, modifierFlags: flags, timestamp: 0, windowNumber: 0, context: nil,
                     characters: type == .flagsChanged ? "" : "x", charactersIgnoringModifiers: type == .flagsChanged ? "" : "x", isARepeat: false, keyCode: code)!
}
var down = false, fired: [Bool] = [], chords = 0
let arrow = key(.keyDown, [.function, .numericPad], 124), press = key(.flagsChanged, .function, 63), release = key(.flagsChanged, [], 63)
updateSpecialHotkey(arrow, fn, &down) { fired.append($0) }
updateSpecialHotkey(key(.keyUp, [.function, .numericPad], 124), fn, &down) { fired.append($0) }
precondition(fired.isEmpty && !down, "a plain arrow key (fn flag on its own event) started dictation")
updateSpecialHotkey(press, fn, &down) { fired.append($0) }
updateSpecialHotkey(key(.keyDown, .function, 51), fn, &down, chord: { chords += 1; return true }) { fired.append($0) }
updateSpecialHotkey(release, fn, &down) { fired.append($0) }
precondition(fired == [true] && chords == 1 && !down, "fn+Delete stayed a dictation press: \(fired)")
fired = []
updateSpecialHotkey(press, fn, &down) { fired.append($0) }
updateSpecialHotkey(key(.keyDown, .function, 51), fn, &down, chord: { false }) { fired.append($0) }
updateSpecialHotkey(release, fn, &down) { fired.append($0) }
precondition(fired == [true, false], "a press that already heard words lost its release: \(fired)")
print("fn alone ok")
'''
        self.assertIn('fn alone ok', run_swift(self, swift))
        chord = source[source.index('    func dictateChord()'):source.index('    func review(')]
        self.assertIn('text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty', chord)
        self.assertIn('!toggleTalk', chord)

    def test_paste_borrows_the_clipboard_and_restores_every_type(self):
        source = (ROOT / 'Atticus.swift').read_text()
        helper = source[source.index('func borrowPasteboard'):source.index('struct TextSelection {')]
        swift = 'import Cocoa\n' + helper + r'''
let pb = NSPasteboard(name: NSPasteboard.Name("atticus-test-" + UUID().uuidString)), custom = NSPasteboard.PasteboardType("com.example.private")
let transient = NSPasteboard.PasteboardType("org.nspasteboard.TransientType")
func snapshot() -> [[String: Data]] { (pb.pasteboardItems ?? []).map { i in Dictionary(uniqueKeysWithValues: i.types.compactMap { t in i.data(forType: t).map { (t.rawValue, $0) } }) } }
let a = NSPasteboardItem(); a.setString("user copy", forType: .string); a.setData(Data("{\\rtf1 user}".utf8), forType: .rtf); a.setData(Data([1, 2, 3]), forType: custom)
let b = NSPasteboardItem(); b.setString("second item", forType: .string)
pb.clearContents(); pb.writeObjects([a, b]); let before = snapshot()
let restore = borrowPasteboard("dictated words", pb)!
precondition(pb.string(forType: .string) == "dictated words" && pb.types?.contains(transient) == true, "the paste text was not on the clipboard, or not marked transient")
restore()
precondition(snapshot() == before, "the user's clipboard (every item and type) did not come back")
precondition(!snapshot().contains { $0.values.contains(Data("dictated words".utf8)) }, "dictated text stayed on the clipboard")
pb.clearContents(); let restoreEmpty = borrowPasteboard("dictated words", pb)!; restoreEmpty()
precondition((pb.pasteboardItems ?? []).isEmpty, "an empty clipboard kept the dictated text")
let c = NSPasteboardItem(); c.setString("user copy", forType: .string); pb.clearContents(); pb.writeObjects([c])
let late = borrowPasteboard("dictated words", pb)!
pb.clearContents(); pb.setString("copied meanwhile", forType: .string); late()
precondition(pb.string(forType: .string) == "copied meanwhile", "a newer copy was clobbered")
pb.releaseGlobally()
print("clipboard borrow ok")
'''
        self.assertIn('clipboard borrow ok', run_swift(self, swift))
        for name in ('    func apply(_ draft:',):
            body = source[source.index(name):source.index('    var value:', source.index(name))]
            self.assertIn('borrowPasteboard(draft)', body)
            self.assertNotIn('clearContents', body)

    def test_globe_key_conflict_only_for_fn_alone(self):
        source = (ROOT / 'Atticus.swift').read_text()
        check = source[source.index('func globeKeyTaken()'):source.index('func transcriptKey(')]
        self.assertIn('"AppleFnUsageType"', check)
        self.assertIn('h.code < 0, h.mods == atticusFnKey', check)
        self.assertIn('?? 1) != 0', check)   # unset is the system's own action, not Do Nothing
        self.assertIn('"globeTaken": globeKeyTaken()', source[source.index('    func push()', source.index('final class SettingsWindow')):])
        self.assertIn('case "globeKey"', source)

    def test_overlay_states_follow_release_done_fallback_fail_and_cancel(self):
        source = (ROOT / 'Atticus.swift').read_text()
        at = source.index('    func stop()', source.index('final class App'))
        release = next(l for l in source[at:source.index('    func applyReplacement(')].splitlines() if 'js("finishing"' in l)
        escape = source[source.index('    func escape()'):source.index('    func hush()')]
        self.assertLess(escape.index('if dictating { return cancel() }'), escape.index('if engine.isRunning'))
        delivery = source[source.index('    func dictationDeliveryFailed('):source.index('    func typed(')]
        cancel = source[source.index('    func cancel()'):source.index('    // ✕ also ends')]
        self.assertNotIn('NSPasteboard', delivery)
        swift = r'''import Foundation
struct Prefs { static var on: Set<String> = ["dictateHistory"]; static func bool(_ key: String) -> Bool { on.contains(key) } }
final class AppRef: Equatable { static func == (a: AppRef, b: AppRef) -> Bool { a === b } }
final class NSWorkspace { static let shared = NSWorkspace(); var frontmostApplication: AppRef? }
var saves = true, saved: [String] = []
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
    var dictationAppName = "App"
    func saveDictation(_ value: String, appName: String) -> Bool { if saves { saved.append(value) }; return saves }
    var log: [String] = [], hides: [Double] = [], shrinks: [Bool] = [], words: [String] = []
    func cue(_ value: String) {}
    func hide(after s: Double, shrink: Bool = false) { hides.append(s); shrinks.append(shrink) }
    func js(_ call: String, _ arg: Any? = nil) {
        if let d = arg as? [String: Any] { log.append("\(call) \(d["text"]!) \(d["ok"]!)"); if let w = d["words"] as? String { words.append(w) } } else { log.append("\(call) \(arg as? String ?? "")") }
    }
    func prepareDictation(_ value: String, target: Target) -> () -> Void { {} }
    func hush() { dictating = false; dictateID += 1; busy = false }
    func shush() {}
    func close(clear: Bool) { log.append("close"); hush() }
    func release() { busy = true
''' + release + '\n    }\n' + delivery + cancel + r'''}
let user = AppRef(); NSWorkspace.shared.frontmostApplication = user
let done = Harness(); done.dictateSelection = Target(user); done.release(); done.insertDictation("hi")
precondition(done.log == ["finishing ", "dictated  true"] && done.hides == [0.15] && done.shrinks == [true], "success said something or did not fold: \(done.log)")
let clean = Harness(); clean.dictateCleanup = true; clean.release()
precondition(clean.log == ["finishing Cleaning up…"], "Clean up mode did not label its wait")
let fallback = Harness(); fallback.release(); fallback.insertDictation("keep me safe")
precondition(fallback.log == ["finishing ", "dictated Saved to History false"] && saved == ["keep me safe"] && fallback.hides == [3] && fallback.shrinks == [false], "fallback: \(fallback.log)")
saves = false
let fail = Harness(); fail.release(); fail.insertDictation("keep me")
precondition(fail.log == ["finishing ", "dictated Couldn’t insert. Your words are still here. false"] && fail.hides.isEmpty, "unsaved words faded away: \(fail.log)")
saves = true; Prefs.on = []; saved = []
let off = Harness(); off.release(); off.insertDictation("history off")
precondition(off.log == ["finishing ", "dictated Couldn’t insert. Your words are still here. false"] && off.hides.isEmpty && saved.isEmpty, "History off: \(off.log)")
precondition(off.words == ["history off"] && fallback.words.isEmpty, "unsaved words cannot be copied from the pill")
Prefs.on = ["dictateHistory"]
let cleanupFail = Harness(); cleanupFail.dictationDeliveryFailed("raw words", cleanup: true)
precondition(cleanupFail.log == ["dictated Couldn’t clean up. Saved to History false"] && saved == ["raw words"], "cleanup failure lost the words")
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
const document = { body: { classList: set() }, createElement: () => ({ className: '', textContent: '', setAttribute() {} }) };
let listening = true, boost = 2;
''' + helper + 'const ui = {\n' + methods + r'''};
const wait = ms => new Promise(r => setTimeout(r, ms)), fail = m => { console.error(m); process.exit(1); };
fresh(); ui.finishing('');
if (q.classList.contains('live') || q.classList.contains('finishing')) fail('release did not stop the caret at once, or flashed the shimmer');
await wait(60); ui.dictated({ text: '', ok: true }); await wait(200);
if (q.classList.ever.has('finishing') || states.includes('solving')) fail('a fast Verbatim insert flashed the finishing state');
if (part('dn').textContent !== '' || states.at(-1) !== 'breathing') fail('success said something, or the orb kept working');
fresh(); ui.finishing(''); await wait(200);
if (!q.classList.contains('finishing') || states.at(-1) !== 'solving' || part('dn').textContent) fail('a slow Verbatim insert showed no finishing state, or a label');
ui.dictated({ text: 'Saved to History', ok: false });
if (q.classList.contains('finishing') || part('dn').className !== 'dn' || states.join() !== 'listening,solving,breathing') fail('finishing outlived the real wait: ' + states);
fresh(); ui.finishing('Cleaning up…');
if (!q.classList.contains('finishing') || part('dn').textContent !== 'Cleaning up…') fail('Clean up mode did not show its wait in the same frame');
ui.dictated({ text: 'Couldn’t clean up. Saved to History', ok: false });
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

    def test_locked_pill_wears_a_ring_that_fades_and_respects_reduce_motion(self):
        page = self.page
        ring = re.search(r'body\.dictate::after \{(.*?)\}', page, re.S).group(1)
        self.assertIn('opacity: 0', ring)
        self.assertIn('transition: opacity', ring)
        self.assertIn('pointer-events: none', ring)
        self.assertIn('255,159,10', ring)   # the overlay's orange (Full access, attention)
        self.assertIn('body.dictate.locked::after { opacity: 1; }', page)
        self.assertIn("locked(on) { document.body.classList.toggle('locked', !!on); }", page)
        reduce = page[page.index('@media (prefers-reduced-motion: reduce)'):page.index('</style>')]
        self.assertIn('transition: none !important', reduce)   # Reduce Motion: the ring just appears

    def test_landed_words_fold_the_pill_quietly_and_respect_reduce_motion(self):
        page, source = self.page, (ROOT / 'Atticus.swift').read_text()
        self.assertIn('body.dictate.fold :is(.q, .dn) { opacity: 0; }', page)   # only opacity: the native panel does the shrinking
        self.assertIn("document.body.classList.remove('locked', 'fold')", page)   # the next dictation starts unfolded
        hide = source[source.index('    func hide(after s: Double, shrink'):source.index('    func defaultKey(')]
        self.assertIn('guard shrink, !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion else { return fade() }', hide)
        self.assertIn('f.size.width = min(f.width, f.height)', hide)
        self.assertIn('pill(dictating)', hide)
        insert = source[source.index('    func insertDictation('):source.index('    func typed(')]
        self.assertIn('js("dictated", ["text": "", "ok": true]); hide(after: 0.15, shrink: true)', insert)


if __name__ == '__main__':
    unittest.main()

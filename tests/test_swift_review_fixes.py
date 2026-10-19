"""Regressions from the 1.3.1 Swift/UI review; source-only except for the shortcut matcher harness."""
from pathlib import Path
import shutil
import subprocess
import unittest

from tests import run_swift


ROOT = Path(__file__).resolve().parents[1]


class SwiftReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.swift = (ROOT / "Atticus.swift").read_text()
        self.agents = (ROOT / "ui/agents.html").read_text()
        self.overlay = (ROOT / "ui/ui.html").read_text()
        self.settings = (ROOT / "ui/settings.html").read_text()

    def test_fn_key_match_is_exact_and_modifier_prefixes_conflict(self):
        helpers = self.swift[self.swift.index("let atticusFnKey"):self.swift.index("func configuredHotkey")]
        matcher = self.swift[self.swift.index("func specialHotkey"):self.swift.index("func handleSpecialHotkeys")]
        self.assertIn("func hotkeysConflict", matcher)
        recorder = self.swift[self.swift.index("    func done("):self.swift.index("    func say(", self.swift.index("    func done("))]
        self.assertIn("hotkeysConflict(hotkey(),dictateHotkey())", recorder)
        harness = "import Cocoa\nimport Carbon\n" + helpers + "\nvar specialGlobalHotkeys: Any?, specialLocalHotkeys: Any?, specialMainDown = false, specialDictateDown = false\n" + matcher + r'''
let fnD = (code: 2, mods: atticusFnKey, flags: NSEvent.ModifierFlags.function)
let fnShiftD = (code: 2, mods: atticusFnKey | shiftKey, flags: NSEvent.ModifierFlags([.function, .shift]))
let fnOnly = (code: -2, mods: atticusFnKey, flags: NSEvent.ModifierFlags.function)
precondition(!hotkeysConflict(fnD, fnShiftD))
precondition(hotkeysConflict(fnOnly, fnD))
var down = false, fired: [Bool] = []
let extra = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [.function, .shift],
    timestamp: 0, windowNumber: 0, context: nil, characters: "d", charactersIgnoringModifiers: "d",
    isARepeat: false, keyCode: 2)!
updateSpecialHotkey(extra, fnD, &down) { fired.append($0) }
precondition(fired.isEmpty)
let exact = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [.function],
    timestamp: 0, windowNumber: 0, context: nil, characters: "d", charactersIgnoringModifiers: "d",
    isARepeat: false, keyCode: 2)!
updateSpecialHotkey(exact, fnD, &down) { fired.append($0) }
precondition(fired == [true])
print("special shortcuts stay distinct")
'''
        self.assertIn("special shortcuts stay distinct", run_swift(self, harness))

    def test_special_shortcut_registration_is_reported_as_available(self):
        registration = self.swift[self.swift.index("var ref: EventHotKeyRef?"):self.swift.index("let settings = SettingsWindow()")]
        push = self.swift[self.swift.index("    func push()"):self.swift.index("    func refresh()")]
        self.assertIn("var hotkeyRegistered = false", registration)
        self.assertIn("var dictateHotkeyRegistered = false", registration)
        self.assertIn('"hotkeyTaken": !hotkeyRegistered', push)
        self.assertIn('"dictateHotkeyTaken": !Prefs.str("dictateHotkeyLabel").isEmpty && !dictateHotkeyRegistered', push)

    def test_teaching_caption_scrolls_to_the_latest_instruction(self):
        caption = self.swift[self.swift.index("final class DrawingCaptionView"):self.swift.index("final class ScreenDrawing")]
        self.assertIn("NSScrollView", caption)
        self.assertIn("scrollToEndOfDocument", caption)
        harness = "import Cocoa\n" + caption + r'''
let words = String(repeating: "A readable instruction needs enough words to wrap. ", count: 16)
let view = DrawingCaptionView(frame: CGRect(x: 0, y: 0, width: 480, height: 300), step: 12, total: 12,
                              captions: Array(repeating: words, count: 12))
RunLoop.current.run(until: Date().addingTimeInterval(0.05))
let scroll = view.subviews.compactMap { $0 as? NSScrollView }.first!
let body = scroll.documentView as! NSTextView
precondition(body.frame.height > scroll.contentSize.height)
precondition(scroll.documentVisibleRect.maxY >= body.frame.maxY - 1)
print("latest caption remains reachable")
'''
        self.assertIn("latest caption remains reachable", run_swift(self, harness))

    def test_agent_rename_cancel_feedback_and_delete_confirmation(self):
        rename = self.agents[self.agents.index("const saved="):self.agents.index(" const head=", self.agents.index("const saved="))]
        self.assertIn("e.stopPropagation()", rename)
        self.assertIn("deleting===r.name", rename)
        self.assertIn("namedReply", self.agents)
        named = self.swift[self.swift.index('        } else if kind == "named"'):self.swift.index("        if let row =", self.swift.index('        } else if kind == "named"'))]
        self.assertIn('js("view","namedReply"', named)

    def test_retry_voice_hint_only_names_visible_answers(self):
        respond = self.overlay[self.overlay.index("    respond(text)"):self.overlay.index("    ask([")]
        self.assertNotIn("status('Say “Retry”, “Try Sonnet” or “Not now”'", respond)
        self.assertIn('d.querySelector(\'[data-answer="y"]\')', respond)
        if not shutil.which("node"):
            self.skipTest("Node runs the retry-card behavior check")
        script = r'''
let heard = '', clicked = '';
const buttons = {n:{click(){clicked='n'}}, r:{click(){clicked='r'}}};
const d = {querySelector(s){const m=s.match(/data-answer="(.)"/);return m ? buttons[m[1]] || null : null;}};
const thread = {querySelector(s){return s.startsWith('.pk') ? null : d;}};
const ask = {value:''}, $ = id => id === 'thread' ? thread : ask, status = s => {heard=s};
const ui = {
''' + respond + r'''
};
if (!ui.respond('try sonnet') || clicked || heard !== 'Say “Retry” or “Not now”') process.exit(1);
console.log(heard);
'''
        result = subprocess.run(["node", "--input-type=module"], input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_point_capture_failure_preserves_answer_and_guides_can_be_replaced(self):
        finish = self.swift[self.swift.index("    func finishPoint("):self.swift.index("    func pointThumb")]
        start = self.swift[self.swift.index("    func startPointing()"):self.swift.index("    func finishPointing()")]
        self.assertIn('js("notice","Couldn’t capture that mark.")', finish)
        self.assertNotIn('js("msg","Couldn’t capture that mark.")', finish)
        self.assertIn("if drawing.active { drawing.clear() }", start)
        self.assertIn("notice(s)", self.overlay)

    def test_settings_describe_all_shortcuts_and_remove_dead_pointer_toggle(self):
        self.assertGreaterEqual(self.settings.count("a modifier on its own"), 2)
        self.assertNotIn('data-k="pointer"', self.settings)
        self.assertNotIn(">Show me where<", self.settings)


if __name__ == "__main__":
    unittest.main()

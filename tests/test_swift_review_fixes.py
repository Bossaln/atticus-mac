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

    def test_long_step_callout_starts_at_its_first_words(self):
        callout = self.swift[self.swift.index("final class DrawingCalloutView"):self.swift.index("final class ScreenDrawing")]
        self.assertIn("NSScrollView", callout)
        self.assertNotIn("scrollToEndOfDocument", callout)   # one step per callout: read it from the top
        harness = "import Cocoa\n" + callout + r'''
let words = String(repeating: "A readable instruction needs enough words to wrap. ", count: 20)
let size = DrawingCalloutView.size(words, total: 12)
let view = DrawingCalloutView(frame: CGRect(x: 0, y: 0, width: size.width + 24, height: size.height + 24),
                              card: CGRect(x: 12, y: 12, width: size.width, height: size.height), side: nil, tip: 0, text: words, step: 12, total: 12)
RunLoop.current.run(until: Date().addingTimeInterval(0.05))
let scroll = view.subviews.compactMap { $0 as? NSScrollView }.first!
let body = scroll.documentView as! NSTextView
precondition(body.frame.height > scroll.contentSize.height)
precondition(scroll.documentVisibleRect.minY <= 1)
print("long step stays reachable")
'''
        self.assertIn("long step stays reachable", run_swift(self, harness))

    def test_agent_rename_cancel_feedback_and_delete_confirmation(self):
        rename = self.agents[self.agents.index("const saved="):self.agents.index(" const head=", self.agents.index("const saved="))]
        self.assertIn("e.stopPropagation()", rename)
        self.assertIn("deleting===r.name", rename)
        self.assertIn("namedReply", self.agents)
        named = self.swift[self.swift.index('        } else if kind == "named"'):self.swift.index("        if let row =", self.swift.index('        } else if kind == "named"'))]
        self.assertIn('js("view","namedReply"', named)

    def test_retry_voice_hint_only_names_visible_answers(self):
        respond = self.overlay[self.overlay.index("    respond(text)"):self.overlay.index("    ask([")]
        self.assertNotIn("Sonnet", respond)
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
        self.assertNotIn("drawing.clear()", start)   # pointing keeps a guide up: its marks can be clicked and asked about
        self.assertIn("notice(s)", self.overlay)

    def test_hidden_rewrite_keeps_its_target(self):
        close = self.swift[self.swift.index("    func close(clear: Bool)"):self.swift.index("    func shortcut(", self.swift.index("    func close(clear: Bool)"))]
        harness = r'''import Foundation
final class NSAnimationContext {
    var duration = 0.0
    static func runAnimationGroup(_ changes: (NSAnimationContext) -> Void, completionHandler: () -> Void) {
        changes(NSAnimationContext()); completionHandler()
    }
}
final class Panel { var alphaValue = 1.0; func animator() -> Panel { self } }
final class Drawing { func clear() {} }
func unpoint() {}
final class Harness {
    var replacement: String? = "draft", selection: Int? = 7, lastDone = Date()
    var recent = "/missing", gen = 0
    let panel = Panel(), drawing = Drawing()
    func shush() {}
    func hush() { replacement = nil; selection = nil }
    func gone() {}
''' + close + r'''}
let hidden = Harness(); hidden.close(clear: false)
precondition(hidden.replacement == "draft" && hidden.selection == 7)
let ended = Harness(); ended.close(clear: true)
precondition(ended.replacement == nil && ended.selection == nil)
print("hidden rewrite target kept")
'''
        self.assertIn("hidden rewrite target kept", run_swift(self, harness))

    def test_pointer_respects_reduce_motion(self):
        pointer = self.swift[self.swift.index("func pointAt("):self.swift.index("// Restart Atticus", self.swift.index("func pointAt("))]
        self.assertIn("let still = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion\n    if !still {", pointer)
        self.assertLess(pointer.index("accessibilityDisplayShouldReduceMotion"), pointer.index("l.add(pulse"))
        self.assertIn("if let box, lead(from: box, to: w.frame.insetBy(dx: 8, dy: 8)) {", pointer)
        lead = pointer[pointer.index("func lead("):]   # Reduce Motion: a still leader line, no running head
        self.assertLess(lead.index("if !still {"), lead.index('line.add(run'))

    def test_new_ask_clears_a_held_ring_without_hiding_the_new_answer(self):
        start = self.swift[self.swift.index("    func start(dictate: Bool)"):self.swift.index("    func heard(")]
        run = self.swift[self.swift.index("    func run(_ t: String"):self.swift.index("\n}\n\n// MARK: - Agent panels")]
        unpoint = self.swift[self.swift.index("func unpoint("):self.swift.index("// A line from the box")]
        self.assertIn("unpoint(false)", start)
        self.assertIn("pointContext = nil; unpoint(false)", run)
        self.assertIn("if notify { gone?() }", unpoint)

    def test_released_dictation_drops_queued_level_updates(self):
        start = self.swift[self.swift.index("    func start(dictate: Bool)"):self.swift.index("    func heard(")]
        level = start[start.index('js("level", v)') - 160:start.index('js("level", v)') + 20]
        self.assertIn("listenID == listeningID, self?.engine.isRunning == true", level)

    def test_talking_about_a_drawing_shows_the_listening_orb(self):
        self.assertIn('if replying && !drawingReply { js("draft", "") } else { js("listen")', self.swift)
        self.assertIn('js(drawingReply ? "words" : "draft", now)', self.swift)
        self.assertIn('typed(response, heard: true)', self.swift)

    def test_hidden_box_forgets_hover(self):
        gone = self.swift[self.swift.index("    func gone()"):self.swift.index("    func pill(")]
        self.assertIn("hovering = false", gone)   # else hide() waits on a mouse that left with the panel
        self.assertIn('js("hover", false)', gone)

    def test_unconfirmed_drawing_reply_does_not_leave_the_box_busy(self):
        stop = self.swift[self.swift.index("    func stop() {"):self.swift.index("    func applyReplacement()")]
        branch = stop[stop.index("if let old = offerText"):stop.index("return }", stop.index("if let old = offerText"))]
        self.assertIn("busy = proc?.isRunning == true", branch)

    def test_agent_card_never_takes_return_from_typing_in_another_app(self):
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        monitor = panels[panels.index("keyMonitor ="):panels.index("localKeys =")]
        self.assertIn("app.defaultKey(false)", monitor)
        self.assertIn("kVK_Return", monitor)   # Return itself must still reach the card
        tick = panels[panels.index("    func tick()"):panels.index("    func open(_ id")]
        self.assertNotIn("app.panel.isVisible || Date().timeIntervalSince(lastKey)", tick)
        self.assertIn("Date().timeIntervalSince(lastKey) >= 1.5", tick)

    def test_agent_done_card_uses_the_open_side_of_a_dragged_shelf(self):
        frame = self.swift[self.swift.index("    static func doneFrame("):self.swift.index("    func placeShelf(")]
        self.assertIn("let top = shelf.midY > bounds.midY", frame)
        self.assertIn("top ? shelf.minY - 8 - f.height : shelf.maxY + 8", frame)

    def test_agent_handoff_drops_the_foreground_mini_screen_before_fading(self):
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        accept = panels[panels.index("    func accept("):panels.index("    static func doneFrame")]
        self.assertLess(accept.index("if from != nil { app.mini.reset() }"), accept.index("app.hide(after:3.5)"))

    def test_interrupted_agent_card_releases_pin_and_return(self):
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        tick = panels[panels.index("    func tick()"):panels.index("    func open(_ id")]
        interrupted = tick[tick.index("if ping != nil"):]
        self.assertIn('app.agentCard = ""', interrupted)
        self.assertIn("app.pinned = false", interrupted)
        self.assertIn("app.defaultKey(false)", interrupted)
        self.assertIn('app.js("agentCancelled")', interrupted)

    def test_agent_show_brings_the_done_card_after_the_ask_ends(self):
        spawn = self.swift[self.swift.index("    func spawn()"):self.swift.index("    func unwarm()")]
        self.assertIn('if line.hasPrefix("▤ ") { self.showAgent = String(line.dropFirst(2)); continue }', spawn)
        ended = spawn[spawn.index("p.terminationHandler"):]
        self.assertLess(ended.index("self.busy = false"), ended.index("agentsUI.show(self.showAgent)"))   # tick() drops a card shown while busy
        self.assertLess(ended.index("agentsUI.show(self.showAgent)"), ended.index("self.hide(after:"))
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        show = panels[panels.index("    func show(_ id:String)"):panels.index("    func tick()")]
        self.assertIn("openView(id)", show)
        self.assertIn('ping = id', show)
        self.assertIn('app.js("agentDone",row)', show)

    def test_moved_guide_explains_why_it_closed(self):
        drawing = self.swift[self.swift.index("final class ScreenDrawing"):self.swift.index("// The box can take typing")]
        tick = drawing[drawing.index("    func tick()"):]
        stale = tick[tick.index("guard Self.current(target)"):]
        self.assertLess(stale.index('status?("The screen changed. Ask again to continue.")'), stale.index("clear()"))

    def test_in_app_accessibility_calls_are_bounded(self):
        init = self.swift[self.swift.index("    override init() {\n        let cfg = WKWebViewConfiguration()"):self.swift.index("    func userContentController(_ c: WKUserContentController")]
        self.assertIn("AXUIElementSetMessagingTimeout(AXUIElementCreateSystemWide(), 0.5)", init)

    def test_sleep_or_lock_releases_recording_and_shortcut_state(self):
        prepare = self.swift[self.swift.index("    func prepareForInactiveSession()"):self.swift.index("    func dictateShortcut(", self.swift.index("    func prepareForInactiveSession()"))]
        self.assertIn("shortcutDown = false; dictateShortcutDown = false", prepare)
        self.assertIn("quietAudio.end(immediate: true)", prepare)
        observers = self.swift[self.swift.index("var specialGlobalHotkeys"):self.swift.index("func specialHotkey(")]
        self.assertIn("NSWorkspace.willSleepNotification", observers)
        self.assertIn("NSWorkspace.didWakeNotification", observers)
        self.assertIn("NSWorkspace.sessionDidResignActiveNotification", observers)
        self.assertIn("specialMainDown = false; specialDictateDown = false", observers)

    def test_display_changes_clear_stale_drawings_and_keep_agent_windows_reachable(self):
        app_init = self.swift[self.swift.index("    override init() {\n        let cfg = WKWebViewConfiguration()"):self.swift.index("    func userContentController(_ c: WKUserContentController")]
        screen = app_init[app_init.index("NSApplication.didChangeScreenParametersNotification"):]
        self.assertIn("drawing.clear()", screen)
        self.assertIn("The screen changed. Ask again to continue.", screen)
        self.assertIn("if hadDrawing && (engine.isRunning || dictating) { hush() }", screen)
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("    func js(_ surface:", self.swift.index("final class AgentPanels"))]
        self.assertIn("NSApplication.didChangeScreenParametersNotification", panels)
        self.assertGreaterEqual(panels.count("MeetingFrame.clamp"), 2)

    def test_agent_permission_poll_stops_after_one_grant(self):
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("    func receive(_ event:", self.swift.index("final class AgentPanels"))]
        allow = panels[panels.index("    func allow("):]
        granted = allow[allow.index("if Onboarding.granted"):]
        self.assertLess(granted.index("t.invalidate()"), granted.index('self.send(["action":"granted"'))
        self.assertGreaterEqual(granted.count('["_a"] as? String == ask'), 1)

    def test_settings_describe_all_shortcuts_and_remove_dead_pointer_toggle(self):
        self.assertGreaterEqual(self.settings.count("a modifier on its own"), 2)
        self.assertNotIn('data-k="pointer"', self.settings)
        self.assertNotIn(">Show me where<", self.settings)


if __name__ == "__main__":
    unittest.main()

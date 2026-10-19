"""Screen drawing boundaries and coordinate mapping; native windows run only through the VM runner."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests import scratch_dir
import atticus

ROOT = Path(__file__).resolve().parents[1]


class DrawingTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)

    def test_shapes_and_ax_anchors(self):
        shapes = [{'kind':k,'rect':[10,20,30,40]} for k in ('rect','circle')]
        shapes += [{'kind':k,'points':[[10,20],[30,40]]} for k in ('line','arrow','path')]
        shapes += [{'kind':'label','at':[10,20],'text':'Leg B'},{'kind':'pointer','at':[20,30]}]
        payload = {'steps':[{'id':'teach','shapes':shapes,'say':'This is the side.'}]}
        self.assertEqual(len(atticus.drawing(payload)['steps'][0]['shapes']),7)
        anchored = {'steps':[{'target':'Exact control','wait':True,'shapes':[{'kind':'rect'},{'kind':'pointer'},{'kind':'label','text':'Here'}]}]}
        self.assertEqual(atticus.drawing(anchored)['steps'][0]['target'],'Exact control')

    def test_bad_coordinates_and_unbounded_payloads_are_rejected(self):
        good = {'steps':[{'shapes':[{'kind':'rect','rect':[1,2,3,4]}]}]}
        for rect in ([0,0,0,1],[0,0,-2,1],[True,0,1,1],[float('nan'),0,1,1],[float('inf'),0,1,1],[100001,0,1,1],[0,0,1],'bad'):
            value = copy.deepcopy(good); value['steps'][0]['shapes'][0]['rect'] = rect
            with self.subTest(rect=rect), self.assertRaises(ValueError): atticus.drawing(value)
        for step in ({'shapes':[]},{'shapes':[{'kind':'html','text':'bad'}]},
                     {'shapes':[{'kind':'pointer'}]}, {'wait':True,'shapes':[{'kind':'rect','rect':[0,0,1,1]}]},
                     {'timeout':1000,'shapes':[{'kind':'rect','rect':[0,0,1,1]}]}):
            with self.subTest(step=step), self.assertRaises(ValueError): atticus.drawing({'steps':[step]})
        with self.assertRaises(ValueError): atticus.drawing({'steps':good['steps']*13})
        for kind in ('line','arrow','path'):
            with self.assertRaises(ValueError):
                atticus.drawing({'steps':[{'shapes':[{'kind':kind,'points':[[1,2],[3,4]],'rect':[1]}]}]})

    def test_actual_retina_and_two_display_pixel_mapping(self):
        mapping = {'1':{'frame':[0,0,1440,900],'pixels':[2880,1800]},
                   '2':{'frame':[-1920,-180,1920,1080],'pixels':[1280,720]}}
        step = lambda n,p: {'screen':n,'say':'Look here.','shapes':[{'kind':'pointer','at':p}]}
        result = atticus.drawing({'steps':[step(1,[1440,900]),step(2,[640,360])]},mapping)
        self.assertEqual(result['steps'][0]['shapes'][0]['at'],[720,450])
        self.assertEqual(result['steps'][1]['shapes'][0]['at'],[-960,360])
        for pixel in ([-1,0],[1281,0],[0,721]):
            with self.assertRaises(ValueError): atticus.drawing({'steps':[step(2,pixel)]},mapping)
        with self.assertRaises(ValueError): atticus.drawing({'steps':[step(3,[0,0])]},mapping)

    def test_disabled_tool_and_prompt_budget(self):
        with patch.object(atticus,'pref',side_effect=lambda k,d: False if k == 'draw' else d):
            self.assertNotIn('--draw',atticus.system_prompt(atticus.ASK_FIRST))
            with self.assertRaisesRegex(ValueError,'off'): atticus.draw({'steps':[]})
        prompt = atticus.system_prompt(atticus.ASK_FIRST)
        installed = str(Path.home()/'Applications/Atticus.app/Contents/Resources/atticus.py')
        self.assertIn('--draw',prompt)
        self.assertLessEqual(len(prompt.replace(atticus.ME,installed)),10000)
        self.assertIn('draw',atticus.switches())
        self.assertFalse(atticus.replayable(atticus.DRAW + " '{}'"))

    def test_confirmation_and_request_relay(self):
        data = {'steps':[{'say':'Look here.','shapes':[{'kind':'pointer','at':[10,10]}]}]}
        target = {'pid':123,'windowID':'17','windowFrame':[0,0,800,600]}
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root)},clear=False), \
             patch.object(atticus,'draw_target',return_value=target), patch.object(atticus,'emit') as emit:
            with patch.object(atticus,'wait_commit',return_value=False):
                with self.assertRaises(ValueError): atticus.draw(data)
            emit.assert_not_called()
            def shown(lines):
                Path(json.loads(lines[0][2:])['receipt']).write_text('shown')
            emit.side_effect = shown
            with patch.object(atticus,'wait_commit',return_value=True):
                self.assertEqual(atticus.draw(data),'Guide shown (step 1 of 1). Leave it running.')
            value = json.loads(emit.call_args.args[0][0][2:])
            self.assertEqual(value['target'],target)
            self.assertEqual(value['state'],atticus.hands_state())
            self.assertTrue(value['teaching'])

    def test_teaching_steps_keep_order_and_visible_captions(self):
        data = {'steps':[
            {'id':'triangle','say':'Draw the right triangle.','shapes':[{'kind':'path','points':[[10,10],[10,80],[90,80],[10,10]]}]},
            {'id':'labels','say':'Label the three sides.','shapes':[{'kind':'label','at':[20,50],'text':'a'}]},
            {'id':'formula','say':'Now use a² + b² = c².','shapes':[{'kind':'label','at':[20,20],'text':'a² + b² = c²'}]},
            {'id':'example','say':'For 3 and 4, c is 5.','shapes':[{'kind':'label','at':[20,35],'text':'3² + 4² = 5²'}]},
        ]}
        value = atticus.drawing(data)
        self.assertTrue(value['teaching'])
        self.assertEqual([step['id'] for step in value['steps']],['triangle','labels','formula','example'])
        self.assertEqual([step['say'] for step in value['steps']],[step['say'] for step in data['steps']])
        with self.assertRaisesRegex(ValueError,'visible say caption'):
            atticus.drawing({'steps':[{'shapes':[{'kind':'pointer','at':[10,10]}]}]})

    def test_app_lifecycle_connects_to_clear(self):
        source = (ROOT/'Atticus.swift').read_text()
        app = source.split('final class App: NSObject, WKScriptMessageHandler {',1)[1]
        for start,end in [('func hush()', 'func stopOfferInput()'),('func run(_ t:', '// MARK: - Agent panels')]:
            self.assertIn('drawing.clear()',app.split(start,1)[1].split(end,1)[0])
        self.assertIn('if drawing.active { cancel(); return }',app)
        self.assertIn('!stuck, !drawing.active',app)
        self.assertIn('!mini.holds, !drawing.active',app)
        ask_finish = app.split('func spawn()',1)[1].split('func unwarm()',1)[0]
        self.assertNotIn('drawing.clear()',ask_finish)

    def test_teaching_dismissal_caption_and_voice_policy(self):
        source = (ROOT/'Atticus.swift').read_text()
        drawing = source.split('final class ScreenDrawing {',1)[1].split('// The box can take typing',1)[0]
        self.assertIn('r.steps[...index].flatMap(\\.shapes)',drawing)
        self.assertIn('render(shapes,animate:animate,previous:previousPointer,append:true)',drawing)
        self.assertIn('r.steps[...index].compactMap(\\.say)',drawing)
        self.assertIn('caption.onClose = { [weak self] in self?.clear() }',drawing)
        self.assertIn('guard step.wait != true || hit?.contains(point) == true',drawing)
        self.assertIn('deadline = r.teaching ? .distantFuture',drawing)
        self.assertIn('else if !r.teaching { clear() }',drawing)
        self.assertIn('if speechEnabled()',drawing)
        self.assertIn('shown = active && (!r.teaching || captionPanel?.isVisible == true)',drawing)

    def test_user_mark_reaches_the_ask_and_has_bounded_fallback(self):
        with tempfile.NamedTemporaryFile(prefix='atticus-point-',suffix='.jpg') as image:
            value = {'bounds':[10,20,40,50], 'path':[[12,22],[20,30]], 'image':image.name,
                     'element':'Fixture AXButton: Continue'}
            context, shots = atticus.point_context(value)
            self.assertIn('path',context)
            self.assertIn('Fixture AXButton',context)
            self.assertEqual(shots[0][0],os.path.realpath(image.name))
        for bad in ({}, {'bounds':[0,0,1,1],'path':[],'element':'x'},
                    {'bounds':[0,0,-1,1],'path':[[0,0]],'element':'x'},
                    {'bounds':[0,0,1,1],'path':[[float('nan'),0]],'element':'x'}):
            with self.subTest(bad=bad):
                self.assertEqual(atticus.point_context(bad),('',[]))
        app = (ROOT/'Atticus.swift').read_text().split('final class App: NSObject, WKScriptMessageHandler {',1)[1]
        self.assertIn('if let point { request["point"] = point }',app)
        self.assertIn('if drawing.hasInput { drawing.clear(); return }',app)
        self.assertIn('if !dictate && !drawing.hasInput { drawing.clear() }',app)

    def test_point_controls_reach_the_app(self):
        app = (ROOT/'Atticus.swift').read_text().split('final class App: NSObject, WKScriptMessageHandler {',1)[1]
        for wiring in ('drawing.inputMode ? finishPointing() : startPointing()', 'if b["pointDone"] != nil { finishPointing() }',
                       'if b["pointClear"] != nil, drawing.hasInput { drawing.clear() }', 'Prefs.set("pointCoached", true)',
                       '!Prefs.bool("pointCoached") { js("pointCoach") }'):
            self.assertIn(wiring,app)
        start = app.split('func startPointing()',1)[1].split('func finishPointing()',1)[0]
        self.assertLess(start.index('drawing.beginInput'),start.index('panel.orderFrontRegardless()'),'the box must stay above the pointing overlay')
        finish = app.split('func finishPoint(',1)[1].split('func startPointing()',1)[0]
        self.assertLess(finish.index('removeItem(atPath:old)'),finish.index('pointContext = context'),'a redrawn mark must delete the last crop')
        self.assertNotIn('thumb',finish.split('pointContext = context',1)[0].split('var context',1)[1],'the thumbnail is for the box, not the model request')
        ui = (ROOT/'ui'/'ui.html').read_text()
        self.assertIn('Click, circle or scribble on anything, then ask',ui)
        self.assertNotIn('Draw on screen',ui)   # that name belongs to Atticus's own drawings
        for page in ('README.md','ui/settings.html','ui/onboarding.html'):
            self.assertIn('Point at your screen',(ROOT/page).read_text(),page)


@unittest.skipUnless(shutil.which('node'),'Node runs the box state check')
class PointBoxTests(unittest.TestCase):
    def test_point_states_with_fake_page(self):
        page = (ROOT/'ui'/'ui.html').read_text()
        setup = page[page.index('  // Point at your screen. The app owns'):page.index("  $('mic').onclick")]
        methods = page[page.index('    point(value) {'):page.index('    finished() {')]
        script = r'''
const el = (more = {}) => ({ dataset: {}, hidden: false, innerHTML: '', textContent: '', attrs: {}, src: '',
  classList: { s: new Set(), toggle(c, on) { on ? this.s.add(c) : this.s.delete(c); }, contains(c) { return this.s.has(c); } },
  setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return this.attrs[k]; }, removeAttribute(k) { delete this.attrs[k]; if (k === 'src') this.src = ''; }, ...more });
const parts = { '.chip i': el(), '.done': el(), '.cancel': el(), '.rm': el(), '.gotit': el(), '.hint': el(), img: el({ hidden: true }) };
const els = { point: el({ innerHTML: '<svg></svg>' }), pointbar: el({ querySelector: s => parts[s] }), comp: el(), status: el() };
const $ = id => els[id], messages = [], post = m => messages.push(m), fit = () => {}, comps = [];
const status = s => { els.status.textContent = s; };
let working = false;
const comp = (on, focus) => { comps.push([on, !!focus]); els.comp.classList.toggle('open', on); if (on) coachShow(); };
''' + setup + 'const ui = {\n' + methods + r'''};
const fail = m => { console.error(m); process.exit(1); }, img = parts.img;
if (parts['.chip i'].innerHTML !== '<svg></svg>') fail('the chip has no pointer glyph for marks without a picture');
ui.pointCoach(); if (bar.dataset.s) fail('coach mark showed with the button hidden');
comp(true); if (bar.dataset.s !== 'coach' || !parts['.hint'].innerHTML.includes('Point at your screen')) fail('coach mark missing');
parts['.gotit'].onclick(); if (bar.dataset.s || messages.filter(m => m.pointCoached).length !== 1) fail('Got it did not end the coach mark');
comp(true); if (bar.dataset.s) fail('coach mark came back');
ui.point({ active: true, marked: false });
if (bar.dataset.s !== 'on' || parts['.hint'].textContent !== 'Click, circle or scribble on anything, then ask' || bar.classList.contains('has')) fail('pointing hint missing');
if (els.status.textContent !== 'Pointing…' || els.point.getAttribute('aria-pressed') !== 'true' || !els.point.classList.contains('active') || comps.at(-1).join() !== 'true,true') fail('pointing is not unmistakable: ' + els.status.textContent);
ui.point({ active: true, marked: true, thumb: 'data:image/jpeg;base64,AA' });
if (!bar.classList.contains('has') || img.hidden || img.src !== 'data:image/jpeg;base64,AA' || parts['.hint'].textContent) fail('a mark did not show its thumbnail');
ui.point({ active: false, marked: true });
if (bar.dataset.s !== 'marked' || img.src !== 'data:image/jpeg;base64,AA' || els.status.textContent !== 'Marked' || els.point.getAttribute('aria-pressed') !== 'false') fail('Done lost the chip');
parts['.rm'].onclick(); parts['.cancel'].onclick(); parts['.done'].onclick();
if (messages.filter(m => m.pointClear).length !== 2 || !messages.some(m => m.pointDone)) fail('chip and buttons do not reach the app');
ui.point(false);
if (bar.dataset.s || !img.hidden || img.src || els.status.textContent !== '' || els.point.classList.contains('marked')) fail('clearing left the chip or status');
status('Thinking…'); ui.point(false); if (els.status.textContent !== 'Thinking…') fail('clearing a mark wiped another status');
ui.point({ active: false, marked: true, thumb: '' }); if (!img.hidden) fail('an empty thumbnail showed a broken image');
working = true; const before = messages.length; els.point.onclick();
if (messages.slice(before).some(m => m.point) || els.status.textContent !== 'Finish or stop the current answer first') fail('pointing during an answer gave no reason');
'''
        result = subprocess.run(['node','--input-type=module'],input=script,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


HARNESS = r'''
import Cocoa
func applySharing(_ window: NSWindow) { window.sharingType = .readOnly }
__DRAWING__
let app = NSApplication.shared; app.setActivationPolicy(.regular)
let window = NSWindow(contentRect:CGRect(x:120,y:100,width:850,height:560),styleMask:[.titled,.closable],backing:.buffered,defer:false)
window.title = "Atticus teaching fixture"; window.isReleasedWhenClosed = false; window.appearance = NSAppearance(named:.darkAqua)
window.backgroundColor = NSColor(calibratedWhite:0.12,alpha:1)
let title = NSTextField(labelWithString:"Learn by doing"); title.textColor = .white; title.font = .systemFont(ofSize:26,weight:.semibold); title.frame = CGRect(x:40,y:475,width:740,height:40); window.contentView!.addSubview(title)
let body = NSTextField(labelWithString:"A² + B² = C²"); body.textColor = .white; body.font = .systemFont(ofSize:32,weight:.medium); body.frame = CGRect(x:55,y:300,width:500,height:55); window.contentView!.addSubview(body)
let button = NSButton(checkboxWithTitle:"Try this control",target:nil,action:nil); button.frame = CGRect(x:400,y:185,width:200,height:38); window.contentView!.addSubview(button)
window.makeKeyAndOrderFront(nil); app.activate()
func pump(_ seconds: Double) { RunLoop.current.run(until:Date().addingTimeInterval(seconds)) }
pump(0.3)
let keyBefore = app.keyWindow
let frontBefore = NSWorkspace.shared.frontmostApplication?.processIdentifier
let info = (CGWindowListCopyWindowInfo(.optionIncludingWindow,CGWindowID(window.windowNumber)) as! [[String:Any]])[0]
let frame = CGRect(dictionaryRepresentation:info[kCGWindowBounds as String] as! CFDictionary)!
let target: [String:Any] = ["pid":ProcessInfo.processInfo.processIdentifier,"windowID":String(window.windowNumber),"windowFrame":[frame.minX,frame.minY,frame.width,frame.height]]
let x=frame.minX, y=frame.minY
let steps: [[String:Any]] = [
 ["id":"geometry","wait":true,"hit":[x+50,y+150,230,220],"shapes":[
  ["kind":"path","points":[[x+70,y+330],[x+270,y+330],[x+270,y+170],[x+70,y+330]],"color":"blue"],
  ["kind":"rect","rect":[x+70,y+330,200,200],"color":"green"],
  ["kind":"label","at":[x+100,y+330],"text":"Leg A"],
  ["kind":"label","at":[x+270,y+200],"text":"Leg B"],
  ["kind":"pointer","at":[x+190,y+230]]]],
 ["id":"control","wait":true,"hit":[x+400,y+350,200,38],"shapes":[
  ["kind":"circle","rect":[x+390,y+345,210,50],"color":"yellow"],
  ["kind":"arrow","points":[[x+640,y+280],[x+495,y+345]]],
  ["kind":"label","at":[x+495,y+345],"text":"Try this control"],
  ["kind":"pointer","at":[x+410,y+370]]]],
 ["id":"finish","shapes":[["kind":"line","points":[[x+60,y+120],[x+650,y+120]],"color":"blue"],
  ["kind":"label","at":[x+450,y+210],"text":"You did it"],
  ["kind":"pointer","at":[x+450,y+240]]]]]
func data(_ steps: [[String:Any]], teaching: Bool = false) -> Data { try! JSONSerialization.data(withJSONObject:["steps":steps,"teaching":teaching,"target":target,"state":"fixture"]) }
let drawing = ScreenDrawing()
var marked: [CGPoint] = []
drawing.beginInput { marked = $0 }
precondition(drawing.panels.count == NSScreen.screens.count && drawing.panels.allSatisfy { !$0.ignoresMouseEvents && !$0.canBecomeKey && !$0.canBecomeMain })
precondition(app.keyWindow === keyBefore && NSWorkspace.shared.frontmostApplication?.processIdentifier == frontBefore,
             "Point input changed the focused app or key window")
precondition(drawing.panels.allSatisfy { ($0.contentView as? DrawingView)?.pointing == true && $0.acceptsMouseMovedEvents },"Pointing has no crosshair cursor")
drawing.startInput(CGPoint(x:x+100,y:y+200)); drawing.moveInput(CGPoint(x:x+140,y:y+240)); drawing.endInput(CGPoint(x:x+140,y:y+240))
precondition(marked.count == 2 && drawing.inputMode && drawing.panels.allSatisfy { !$0.ignoresMouseEvents },"A stroke ended pointing before Done")
drawing.startInput(CGPoint(x:x+300,y:y+300)); drawing.endInput(CGPoint(x:x+300,y:y+300))
precondition(marked == [CGPoint(x:x+300,y:y+300)] && drawing.inputPath.count == 1,"A new stroke did not replace the last mark")
drawing.finishInput()
precondition(!drawing.inputMode && drawing.hasInput && drawing.panels.allSatisfy { $0.ignoresMouseEvents && ($0.contentView as? DrawingView)?.pointing == false },"Done did not keep the mark and hand clicks back")
drawing.startInput(CGPoint(x:x+10,y:y+10)); precondition(drawing.inputPath.count == 1,"A click after Done changed the mark")
drawing.clear(); precondition(!drawing.hasInput && drawing.panels.isEmpty,"Point input did not clear")
var cleared = 0; drawing.inputCleared = { cleared += 1 }
drawing.beginInput { _ in }; drawing.finishInput()
precondition(!drawing.hasInput && drawing.panels.isEmpty && cleared == 1,"Done with no mark did not cancel")
drawing.inputCleared = nil
precondition(drawing.receive(data(steps)))
precondition(drawing.panels.count == NSScreen.screens.count)
precondition(app.keyWindow === keyBefore && NSWorkspace.shared.frontmostApplication?.processIdentifier == frontBefore,
             "Drawing changed the focused app or key window")
for panel in drawing.panels {
 precondition(!panel.canBecomeKey && !panel.canBecomeMain && panel.ignoresMouseEvents && !panel.isKeyWindow && !panel.isMainWindow)
 precondition(panel.collectionBehavior.contains(.canJoinAllSpaces) && panel.collectionBehavior.contains(.fullScreenAuxiliary))
 precondition(panel.styleMask.contains(.nonactivatingPanel))
}
func shot(_ name: String) {
 drawing.deadline = .distantFuture // screenshot encoding is not part of the timeout behavior under test
 pump(0.4)
 let file = NSTemporaryDirectory()+name+".png", p = Process(); p.executableURL = URL(fileURLWithPath:"/usr/sbin/screencapture"); p.arguments = ["-x",file]
 try! p.run(); p.waitUntilExit()
 if let bytes = try? Data(contentsOf:URL(fileURLWithPath:file)), !bytes.isEmpty { print("DRAW_SCREENSHOT \(name) \(bytes.base64EncodedString())") }
 else { preconditionFailure("Fixture screenshot failed") }
}
shot("01-geometry")
precondition(drawing.active,"Guide cleared before click")
drawing.ready = .distantPast
drawing.clicked(CGPoint(x:x+800,y:y+500)); precondition(drawing.index == 0,"Outside click advanced step")
drawing.clicked(CGPoint(x:x+100,y:y+200)); precondition(drawing.index == 1,"Target click did not advance")
shot("02-control")
drawing.advance(); precondition(drawing.index == 2)
shot("03-finish")
let panels = drawing.panels
var cleanups = 0; drawing.cleanup = { cleanups += 1 }
drawing.clear(); precondition(cleanups == 1,"AX session was not restored on clear"); precondition(!drawing.active && drawing.voice == nil && drawing.timer == nil && drawing.monitors.isEmpty && panels.allSatisfy { !$0.isVisible })
let anchored: [[String:Any]] = [["target":"Exact control","wait":true,"shapes":[["kind":"rect"],["kind":"pointer"],["kind":"label","text":"Here"]]],steps[2]]
let nativeTarget = try! JSONDecoder().decode(DrawingWindow.self,from:JSONSerialization.data(withJSONObject:target))
let anchor = CGRect(x:x+400,y:y+350,width:200,height:38)
var value = 0
drawing.resolve = { _,_ in (anchor,AXUIElementCreateApplication(getpid()),nativeTarget) }
drawing.readValue = { _ in NSNumber(value:value) }
precondition(drawing.receive(data(anchored)))
precondition(drawing.hit == anchor,"AX frame was not used")
drawing.ready = .distantPast; value = 1; drawing.tick(); precondition(drawing.index == 1,"Value change did not advance")
let motion = DrawingView(frame:CGRect(x:0,y:0,width:100,height:100))
let shape = DrawingShape(kind:"line",points:[[1,2],[30,40]])
motion.render([shape],animate:false,previous:nil); precondition(motion.layer!.sublayers!.allSatisfy { $0.animationKeys() == nil },"Reduced motion animated")
motion.render([shape],animate:true,previous:nil); precondition(motion.layer!.sublayers!.first!.animation(forKey:"draw") != nil)
let speech = Process(); speech.executableURL = URL(fileURLWithPath:"/bin/sleep"); speech.arguments = ["30"];try! speech.run(); drawing.voice=speech
drawing.clear(); speech.waitUntilExit(); precondition(!speech.isRunning && drawing.voice == nil,"Cancel left voice running")
precondition(drawing.receive(data(steps)))
drawing.deadline = .distantPast; drawing.tick(); precondition(!drawing.active,"Timeout did not clear")
precondition(drawing.receive(data(steps)))
window.setFrameOrigin(CGPoint(x:window.frame.minX+30,y:window.frame.minY)); pump(0.2); drawing.tick(); precondition(!drawing.active,"Window movement did not clear")
var bad = target; bad["windowFrame"] = [0,0,-1,1]
let invalid = try! JSONSerialization.data(withJSONObject:["steps":steps,"teaching":false,"target":bad,"state":"fixture"])
precondition(!drawing.receive(invalid),"Native accepted invalid frame")
precondition(!drawing.receive(data(steps)),"Stale screenshot geometry was shown")
window.setFrameOrigin(CGPoint(x:window.frame.minX-30,y:window.frame.minY)); pump(0.1)
precondition(drawing.receive(data(steps)))
window.orderOut(nil); pump(0.1); drawing.tick(); precondition(!drawing.active,"Closed window did not clear")
let outside = [["shapes":[["kind":"pointer","at":[99999,99999]]]]]
precondition(!drawing.receive(data(outside)),"Native accepted off-display coordinates")
let mixed = [["shapes":[["kind":"line","points":[[1,2],[3,4]],"rect":[1]]]]]
precondition(!drawing.receive(data(mixed)),"Native accepted coordinates for another shape kind")
print("Native drawings: click-through, never key/main, all displays/spaces, target click, next, clear, timeout, moved window, validation passed")
window.orderOut(nil)
'''


@unittest.skipUnless(sys.platform == 'darwin','macOS native drawing fixture')
class NativeDrawingTests(unittest.TestCase):
    def test_product_typechecks(self):
        result = subprocess.run(['swiftc','-typecheck',str(ROOT/'Atticus.swift')],capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_native_drawings_and_fixture_screenshots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = (ROOT/'Atticus.swift').read_text()
            drawing = source[source.index('// Screen drawings use Quartz'):source.index('// The box can take typing')]
            (root/'main.swift').write_text(HARNESS.replace('__DRAWING__',drawing))
            result = subprocess.run(['swiftc',str(root/'main.swift'),'-o',str(root/'fixture')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result = subprocess.run([str(root/'fixture')],capture_output=True,text=True,timeout=25,
                                    env={**os.environ,'ATTICUS_DIR':folder})
            self.assertEqual(result.returncode,0,result.stdout[-1500:]+result.stderr[-2000:])
            # VM artifacts travel through stdout because the runner shuts the guest down immediately.
            self.assertEqual(result.stdout.count('DRAW_SCREENSHOT '),3)
            print(result.stdout,flush=True)


@unittest.skipUnless(sys.platform == 'darwin','macOS Swift drawing anchor check')
class DrawingAnchorTests(unittest.TestCase):
    def test_ids_keep_identity_across_expected_value_changes(self):
        from tests import run_swift
        source = (ROOT/'Atticus.swift').read_text()
        method = source[source.index('    static func drawAnchor('):source.index('    static func point(_ text:')]
        harness = r'''import Cocoa
typealias AXUIElement = Int
struct DrawingWindow { let pid:Int32,windowID:String,windowFrame:[Double] }
struct MiniScreen { static func bounds(_ info:[String:Any])->CGRect? { CGRect(x:10,y:20,width:300,height:200) } }
func CGWindowListCopyWindowInfo(_ option: CGWindowListOption,_ id:UInt32)->CFArray? { [["fixture":true]] as CFArray }
enum Hands {
 struct Failure: Error { let message:String;init(_ message:String){self.message=message} }
 struct Node:Codable { var id:Int,role:String,label:String,path:[Int],value:String }
 struct Map:Codable { var pid:Int32,windowID:String,windowFrame:[Double],nodes:[Node] }
 static var fresh = Map(pid:1,windowID:"5",windowFrame:[10,20,300,200],nodes:[Node(id:9,role:"AXButton",label:"Control",path:[2,3],value:"on")])
 static func app(_ pid:String)throws->Int {1}
 static func capture(_ app:Int)throws->Map {fresh}
 static func at(_ path:[Int],_ app:Int)throws->AXUIElement { precondition(path == [2,3]);return 42 }
 static func visibleFrame(_ e:AXUIElement)->CGRect { CGRect(x:40,y:50,width:60,height:20) }
 static func array(_ r:CGRect)->[Double] {[r.minX,r.minY,r.width,r.height]}
 static func resolve(_ label:String,map:Map,a:Int)throws->(Node,AXUIElement?) { throw Failure("ID resolution must preserve its original path") }
''' + method + r''' }
let file = NSTemporaryDirectory()+UUID().uuidString
var old=Hands.fresh;old.nodes[0].id=1;old.nodes[0].value="off"
try! JSONEncoder().encode(old).write(to:URL(fileURLWithPath:file));defer {try? FileManager.default.removeItem(atPath:file)}
let result = try! Hands.drawAnchor("1",state:file)
precondition(result.0 == CGRect(x:40,y:50,width:60,height:20) && result.1 == 42,"Value change lost target identity")
for mutation in 0..<3 {
 Hands.fresh=old
 if mutation == 0 { Hands.fresh.nodes[0].label="Different control" }
 else if mutation == 1 { Hands.fresh.nodes[0].path=[5] }
 else { Hands.fresh.windowFrame[0] += 30 }
 do { _ = try Hands.drawAnchor("1",state:file);preconditionFailure("Changed target was accepted") } catch {}
}
print("Stable AX anchor identity and stale-target rejection passed")
'''
        self.assertIn('Stable AX anchor',run_swift(self,harness))

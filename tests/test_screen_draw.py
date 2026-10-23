"""Screen drawing boundaries and coordinate mapping; native windows run only through the VM runner."""
import copy
import io
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

    def test_large_text_lines_for_worked_math(self):
        mapping = {'2':{'frame':[-1920,0,1920,1080],'pixels':[1280,720]}}
        steps = [{'screen':2,'say':'Split the 12.','shapes':[{'kind':'text','text':'12x⁵ = (3·4)·x⁵','at':[640,360],'size':'l'}]},
                 {'say':'Check it.','shapes':[{'kind':'text','text':'3·4 = 12 ✓','color':'green'}]}]
        value = atticus.drawing({'steps':steps},mapping)
        self.assertEqual(value['steps'][0]['shapes'][0],{'kind':'text','text':'12x⁵ = (3·4)·x⁵','at':[-960,540],'size':'l'})
        self.assertTrue(value['teaching'])
        for bad in ({'kind':'text'},{'kind':'text','text':''},{'kind':'text','text':'x'*301},{'kind':'text','text':'a','size':'xl'},
                    {'kind':'text','text':'a','rect':[1,2,3,4]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError): atticus.drawing({'steps':[{'say':'s','shapes':[bad]}]})
        self.assertIn('text "text" (one large line',atticus.DRAW_HELP)
        self.assertIn('Drawings stay through later asks',atticus.DRAW_HELP)

    def test_filled_diagram_parts_and_sized_labels(self):
        shapes = [{'kind':'circle','rect':[100,100,300,220],'color':'green','fill':True},
                  {'kind':'rect','rect':[130,130,240,160],'color':'blue','fill':False},
                  {'kind':'label','at':[250,210],'text':'Cell membrane','size':'l'}]
        value = atticus.drawing({'steps':[{'say':'Compare the two layers.','shapes':shapes}]})
        self.assertEqual(value['steps'][0]['shapes'],shapes)
        self.assertIn('circle may be an ellipse; add "fill":true',atticus.DRAW_HELP)
        self.assertIn('optional "size":"s"|"m"|"l"',atticus.DRAW_HELP)
        for bad in ({'kind':'circle','rect':[1,2,3,4],'fill':'yes'},
                    {'kind':'line','points':[[1,2],[3,4]],'fill':True},
                    {'kind':'label','at':[1,2],'text':'x','size':'xl'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                atticus.drawing({'steps':[{'say':'s','shapes':[bad]}]})

    def test_help_names_the_order_and_keys_the_validator_takes(self):
        help_ = atticus.DRAW_HELP
        self.assertLess(help_.index(atticus.LOOK),help_.index(atticus.DRAW + " '<JSON>'"))   # draw() refuses without this ask's --look
        for said in ('"size":"s"|"m"|"l"','"screen":N on the step (never in a shape)','(exactly 2; path for more)'): self.assertIn(said,help_)
        for bad in ({'kind':'text','text':'a','s':'l'},{'kind':'label','at':[1,1],'text':'a','screen':2},{'kind':'line','points':[[0,0],[1,1],[2,2]]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError): atticus.drawing({'steps':[{'say':'s','shapes':[bad]}]})

    def test_explain_asks_get_a_diagram_not_marks_on_words(self):
        help_ = atticus.DRAW_HELP   # Oct 20 "draw and explain cell wall vs membrane": two rects around the study guide's words
        self.assertIn('Pick the kind from the ask, not from what is on screen',help_)
        self.assertLess(help_.index('- Locate ('),help_.index('Fit the mark'),help_.index('- Explain ('))   # rect/circle fitting is for locating only
        for said in ('draw the idea itself','clear space','otherwise draw your own',"marks around on-screen words are not an explanation"): self.assertIn(said,help_)
        self.assertNotIn('build on the on-screen material',help_)
        mapping = {'2':{'frame':[1440,0,1920,1080],'pixels':[1280,720]}}   # the logged ask drew on screen 2 in --look pixels
        logged = {'steps':[{'id':'1','screen':2,'say':'The membrane…','shapes':[{'kind':'rect','rect':[626,484,270,16],'color':'blue'}]},
                           {'id':'2','screen':2,'say':'The cell wall…','shapes':[{'kind':'rect','rect':[702,509,88,15],'color':'green'}]}]}
        diagram = {'steps':[{'screen':2,'say':'Every cell has a thin, flexible membrane that picks what gets in.','shapes':[
                                {'kind':'circle','rect':[940,120,140,140],'color':'blue'},{'kind':'label','at':[960,280],'text':'membrane: every cell'}]},
                            {'screen':2,'say':'Plants, fungi and bacteria add a rigid wall outside it.','shapes':[
                                {'kind':'rect','rect':[1100,110,160,160],'color':'green'},{'kind':'circle','rect':[1115,125,130,130],'color':'blue'},
                                {'kind':'label','at':[1110,280],'text':'wall + membrane'},{'kind':'arrow','points':[[792,516],[1100,190]],'color':'green'}]},
                            {'screen':2,'say':'Side by side.','shapes':[{'kind':'text','text':'membrane: flexible gate, every cell','at':[940,330]},
                                {'kind':'text','text':'wall: rigid, outside, stops bursting'}]}]}
        for value in (logged,diagram): self.assertTrue(atticus.drawing(value,mapping)['teaching'])   # both valid: only the help tells them apart

    def test_follow_up_sees_the_drawing_and_a_selected_mark(self):
        drawn = {'steps':[{'say':'The shared x.','shapes':[{'kind':'circle','rect':[600,170,60,60],'color':'red'}]}],'shown':1}
        context = atticus.drawing_context(drawn)
        self.assertIn('still on screen, step 1 of 1',context)
        self.assertIn('"rect":[600,170,60,60]',context)
        self.assertIn('more drawing, run --look && --draw --help (one call), then one --draw',context)   # the help carries the locate/explain split
        for bad in (None,{},{'steps':[]},{'steps':'x'},'steps'):
            self.assertEqual(atticus.drawing_context(bad),'')
        many = {'steps':[{'say':f'Step {i}','shapes':[{'kind':'path','points':[[j,j] for j in range(256)]}]} for i in range(12)]}
        squeezed = atticus.drawing_context(many)
        self.assertIn('"Step 11"',squeezed); self.assertLess(len(squeezed),2300)
        with tempfile.NamedTemporaryFile(prefix='atticus-point-',suffix='.jpg') as image:
            value = {'bounds':[570,140,120,120],'path':[[594,164],[666,236]],'image':image.name,'element':'',
                     'mark':'circle in step 1 of 1: The shared x.'}
            context, shots = atticus.point_context(value)
        self.assertIn('User selected a mark of your drawing',context)
        self.assertIn('The shared x.',context)
        self.assertIn('selected this mark',shots[0][1])
        self.assertEqual(atticus.point_context({**value,'image':'/etc/hosts','mark':'circle'})[0][:30],'User selected a mark of your d')   # text alone still counts
        self.assertEqual(atticus.point_context({**value,'image':'/etc/hosts','mark':7})[0],'')

    def test_pointer_rejects_stale_or_off_picture_coordinates(self):
        displays = [('Laptop',0,0,1440,900,True),('Monitor',-1920,-180,1920,1080,False)]
        with patch.object(atticus,'screens',return_value=displays), patch.object(atticus,'say') as say:
            self.assertEqual(atticus.point('Here. [point 2 640 360]'),'Here.')
            say.assert_called_once_with('@','-960 360 answer')
            say.reset_mock()
            for tag in ('[point 3 20 30]','[point 2 1281 30]','[point 2 20 721]','[point 2 -1 20]','[point nope]'):
                with self.subTest(tag=tag):
                    self.assertEqual(atticus.point('Here. ' + tag),'Here.')
            say.assert_not_called()

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

    def test_retina_scaled_and_non_retina_pixel_mapping(self):
        mapping = {'1':{'frame':[0,0,1440,900],'pixels':[2880,1800]},
                   '2':{'frame':[-1920,-180,1920,1080],'pixels':[1280,720]},
                   '3':{'frame':[1440,0,1920,1080],'pixels':[1920,1080]}}
        step = lambda n,p: {'screen':n,'say':'Look here.','shapes':[{'kind':'pointer','at':p}]}
        second = step(2,[640,360]); second['shapes'].append({'kind':'rect','rect':[0,0,1280,720]})
        result = atticus.drawing({'steps':[step(1,[1440,900]),second,step(3,[960,540])]},mapping)
        self.assertEqual(result['steps'][0]['shapes'][0]['at'],[720,450])
        self.assertEqual(result['steps'][1]['shapes'][0]['at'],[-960,360])
        self.assertEqual(result['steps'][1]['shapes'][1]['rect'],[-1920,-180,1920,1080])
        self.assertEqual(result['steps'][2]['shapes'][0]['at'],[2400,540])
        for pixel in ([-1,0],[1281,0],[0,721]):
            with self.assertRaises(ValueError): atticus.drawing({'steps':[step(2,pixel)]},mapping)
        with self.assertRaises(ValueError): atticus.drawing({'steps':[step(4,[0,0])]},mapping)

    def test_disabled_tool_and_prompt_budget(self):
        with patch.object(atticus,'pref',side_effect=lambda k,d: False if k == 'draw' else d):
            self.assertNotIn('--draw',atticus.system_prompt(atticus.ASK_FIRST))
            with self.assertRaisesRegex(ValueError,'off'): atticus.draw({'steps':[]})
        prompt = atticus.system_prompt(atticus.ASK_FIRST)
        installed = str(Path.home()/'Applications/Atticus.app/Contents/Resources/atticus.py')
        self.assertIn('--draw',prompt)
        self.assertIn('use ' + atticus.DRAW + ' once on Request screen unless user names another',prompt)
        self.assertLessEqual(len(prompt.replace(atticus.ME,installed)),10050)   # +50 for the send-to-running-input rule (1.3.2)
        self.assertIn('draw',atticus.switches())
        self.assertFalse(atticus.replayable(atticus.DRAW + " '{}'"))

    def test_confirmation_and_request_relay(self):
        data = {'steps':[{'say':'Look here.','shapes':[{'kind':'pointer','at':[10,10]}]}]}
        target = {'pid':123,'windowID':'17','windowFrame':[0,0,800,600]}
        (self.root/'draw-screens.json').write_text(json.dumps({
            'screens':{'1':{'frame':[0,0,800,600],'pixels':[1600,1200]}}, 'target':target}))
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

    def test_draw_requires_fresh_screen_context(self):
        data = {'steps':[{'say':'Look here.','shapes':[{'kind':'pointer','at':[10,10]}]}]}
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root)},clear=False), \
             patch.object(atticus,'wait_commit',return_value=True), patch.object(atticus,'emit') as emit, \
             patch.object(atticus,'draw_target') as target:
            with self.assertRaisesRegex(ValueError,'--look before drawing'):
                atticus.draw(data)
        emit.assert_not_called()
        target.assert_not_called()

    def test_failed_look_clears_old_drawing_snapshot(self):
        snapshot=self.root/'draw-screens.json';snapshot.write_text('{"screens":{"1":{"frame":[0,0,10,10],"pixels":[10,10]}}}')
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root)},clear=False),patch.object(atticus,'screens',return_value=[]):
            self.assertEqual(atticus.look(cleanup=False),[])
        self.assertFalse(snapshot.exists())

    def test_look_finds_the_drawing_target_while_it_captures(self):
        import threading
        asked = threading.Event()
        def target(): asked.set(); return {'windowID': '7'}
        def run(args, **_):
            if args[1:2] == ['--look']:
                assert asked.wait(2), 'the target lookup waited for the capture'
                Path(args[-1]).write_bytes(b'x'); return subprocess.CompletedProcess(args, 0)
            return subprocess.CompletedProcess(args, 0, stdout='pixelWidth: 1280\npixelHeight: 800\n')
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root)},clear=False), patch.object(atticus,'screens',return_value=[('Laptop',0,0,1440,900,True)]), \
             patch.object(atticus,'draw_target',target), patch.object(atticus.subprocess,'run',run):
            self.assertEqual(len(atticus.look(cleanup=False)), 1)
        snapshot = json.loads((self.root/'draw-screens.json').read_text())
        self.assertEqual((snapshot['target'], snapshot['screens']['1']['pixels']), ({'windowID': '7'}, [1280, 800]))

    def test_ax_draw_refreshes_the_map_in_the_look_target(self):
        target={'pid':123,'windowID':'17','windowFrame':[0,0,800,600]}
        (self.root/'draw-screens.json').write_text(json.dumps({
            'screens':{'1':{'frame':[0,0,800,600],'pixels':[1600,1200]}},'target':target}))
        data={'steps':[{'target':'Send','wait':True,'shapes':[{'kind':'rect'}]}]}
        def shown(lines): Path(json.loads(lines[0][2:])['receipt']).write_text('shown')
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.root)},clear=False),patch.object(atticus,'wait_commit',return_value=True), \
             patch.object(atticus,'hands_map',return_value=target) as mapped,patch.object(atticus,'emit',side_effect=shown) as emit:
            self.assertIn('Guide shown',atticus.draw(data))
            mapped.assert_called_once_with(target=target)
            self.assertEqual(json.loads(emit.call_args.args[0][0][2:])['target'],target)
            mapped.reset_mock()
            (self.root/'draw-screens.json').write_text(json.dumps({
                'screens':{'1':{'frame':[0,0,800,600],'pixels':[1600,1200]}}}))
            with self.assertRaisesRegex(ValueError,'--look again'): atticus.draw(data)
            mapped.assert_not_called()

    def test_verified_guide_replaces_a_long_final_answer(self):
        long_answer = 'A long duplicate explanation that belongs in the guide.'
        self.assertEqual(atticus.guide_reply([{'error':False,'result':'Guide shown (step 1 of 4). Leave it running.'}],long_answer),
                         'Done. Steps are on screen.')
        self.assertEqual(atticus.guide_reply([{'error':True,'result':'Guide shown (step 1 of 4). Leave it running.'},
                                              {'error':False,'result':long_answer}],long_answer),long_answer)

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
        section = lambda start, end: app.split(start,1)[1].split(end,1)[0]
        self.assertIn('drawing.end()',section('func close(clear: Bool)','\n    }'))   # the box's ✕ takes the drawing with it
        self.assertIn('unpoint(false)',section('func start(dictate: Bool)','func heard('))   # a voice ask clears the old answer ring at key-down
        for start,end in [('func hush()', 'func stopOfferInput()'),('func run(_ t:', '// MARK: - Agent panels'),('func typed(', 'func finish()')]:
            self.assertNotIn('drawing.clear()',section(start,end),start)   # a follow-up keeps the drawing; only a new one replaces it
        self.assertIn('drawing.clearInput(); drawing.deselect()',section('func run(_ t:', '// MARK: - Agent panels'))
        self.assertIn('if let drawn { request["drawing"] = drawn }',app)
        esc = section('func escape()','func hush()')
        self.assertLess(esc.index('} else if busy {'),esc.index('} else if drawing.active || drawing.pending != nil {'))   # Esc stops the answer first, then clears the drawing or its pending next step
        self.assertIn('app.drawing.clear()',source.split('func applicationShouldTerminate',1)[1].split('\n    }',1)[0])
        self.assertIn('!stuck, !drawing.holds',app)
        self.assertIn('mini.holds || drawing.holds',app)
        ask_finish = app.split('func spawn()',1)[1].split('func unwarm()',1)[0]
        self.assertNotIn('drawing.clear()',ask_finish)

    def test_follow_ups_keep_the_guide_display_and_voice_prewarms(self):
        source = (ROOT/'Atticus.swift').read_text()
        app = source.split('final class App: NSObject, WKScriptMessageHandler {',1)[1]
        start = app.split('func start(dictate: Bool)',1)[1].split('func heard(',1)[0]
        typed = app.split('func typed(',1)[1].split('func finish()',1)[0]
        finish = app.split('func finish()',1)[1].split('func spawn()',1)[0]
        self.assertIn('if !dictate && !drawingReply { targetScreen = currentRequestScreen(panel) }',start)
        self.assertIn('if !dictate && (!replying || drawingReply) { unwarm(); warm = spawn() }',start)
        self.assertIn('if !drawing.active { targetScreen = currentRequestScreen(panel) }',typed)
        self.assertIn('hush(keepReply: false, keepWarm: true); typed(response, heard: true)',finish)
        self.assertIn('if transcriptKey(response) == "next" { unwarm(); drawing.next()',finish)

    def test_guide_steps_callouts_and_voice_policy(self):
        source = (ROOT/'Atticus.swift').read_text()
        drawing = source.split('final class ScreenDrawing {',1)[1].split('// The box can take typing',1)[0]
        self.assertIn('r.steps[..<index].enumerated().map { view.render($0.element.shapes,animate:false,previous:nil,append:true,dim:true,step:$0.offset) }',drawing)
        for wiring in ('callout.onClose = { [weak self] in self?.end() }','callout.onNext = { [weak self] in self?.next() }',
                       'callout.onBack = { [weak self] in self?.back() }'):
            self.assertIn(wiring,drawing)
        self.assertIn('guard step.wait != true || hit?.contains(point) == true',drawing)
        self.assertIn('deadline = r.teaching ? .distantFuture',drawing)
        self.assertIn('else if !r.teaching, detached || !proceedGuide() { clear() }',drawing)   # after another ask or a cancel the click only finishes it
        self.assertIn('func hold() { stopVoice(); manual = true; detach() }',drawing)
        self.assertIn('guard Self.inApp(point,windows,pid:target.pid,hit:r.steps[index].wait == true ? hit : nil,front:eligible(target.pid))',drawing)
        self.assertIn('if !words.isEmpty, speechEnabled()',drawing)
        self.assertIn('shown = active && (!r.teaching || calloutPanel?.isVisible == true)',drawing)
        self.assertIn('!manual, autoSteps()',drawing.split('func tick()',1)[1])
        self.assertNotIn('status?(words)',drawing)   # step text lives beside its marks, never in the ask box
        app = source.split('final class App: NSObject, WKScriptMessageHandler {',1)[1]
        self.assertIn('drawing.autoSteps = { Prefs.str("guideSteps") != "next" }',app)
        self.assertIn('(guided ? finish : result)',app)
        self.assertIn('deliver(guided ? finish : result, aloud: !guided)',app)   # a follow-up answer beside an old drawing still speaks
        self.assertIn('guard !marks.isNull else { clear(); return }',drawing)
        self.assertIn('guard screen.intersects(global) else { return }',source)
        self.assertNotIn('drawing.advance()',app)   # a spoken or typed "next" takes over like the Next button
        self.assertIn('"guideSteps": "auto"',source)
        self.assertIn('"guideSteps"', source[source.index('static let retiredKeys'):])   # steps advance by themselves; no Settings row

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
        self.assertIn('if drawing.hasInput { drawing.clearInput(); return }',app)
        self.assertIn('if !dictate && !drawing.hasInput && !busy { drawing.end() }',app)
        self.assertNotIn('if drawing.active { drawing.clear() }',app.split('func startPointing()',1)[1].split('func finishPointing()',1)[0])   # pointing keeps a guide up

    def test_point_controls_reach_the_app(self):
        app = (ROOT/'Atticus.swift').read_text().split('final class App: NSObject, WKScriptMessageHandler {',1)[1]
        for wiring in ('drawing.inputMode ? finishPointing() : startPointing()', 'drawing.inputAway = { [weak self] in self?.finishPointing() }',
                       'if b["pointClear"] != nil { if drawing.hasInput { drawing.clearInput() } else { clearPointContext() } }', 'Prefs.set("pointCoached", true)',
                       'drawing.picked = { [weak self] r, words in self?.finishPoint([CGPoint(x:r.minX,y:r.minY),CGPoint(x:r.maxX,y:r.maxY)],mark:words) }',
                       '!Prefs.bool("pointCoached") { js("pointCoach") }'):
            self.assertIn(wiring,app)
        self.assertNotIn('pointDone',app)
        begin = (ROOT/'Atticus.swift').read_text().split('func beginInput(',1)[1].split('func startInput(',1)[0]
        self.assertIn('panel.level = NSWindow.Level(rawValue:NSWindow.Level.statusBar.rawValue - 1)',begin)   # Atticus's .statusBar panels stay above it, even after a click raises it
        finish = app.split('func finishPoint(',1)[1].split('func startPointing()',1)[0]
        self.assertLess(finish.index('removeItem(atPath:old)'),finish.index('pointContext = context'),'a redrawn mark must delete the last crop')
        self.assertNotIn('thumb',finish.split('pointContext = context',1)[0].split('var context',1)[1],'the thumbnail is for the box, not the model request')
        ui = (ROOT/'ui'/'ui.html').read_text()
        self.assertIn('#comp.pick #model, #comp.pick #point, #comp.pick #mic { opacity: 0;',ui)   # the open Model row never shows the button through
        self.assertIn('Click, circle or scribble on anything, then ask',ui)
        bar = ui.split('<div id="pointbar"',1)[1].split('</div>',1)[0]
        self.assertNotIn('Done',bar); self.assertNotIn('Cancel',bar); self.assertNotIn('pointDone',ui)   # mark, then ask: nothing to confirm
        setup = (ROOT/'ui'/'onboarding.html').read_text()
        coach = ui.split('const coachShow',1)[1].split('};',1)[0]
        for words in ('next to the mic','circle, click or scribble on anything','type or say your question'):
            self.assertIn(words,setup.lower())
        for words in ('circle, click or scribble on anything','type or say your question'):
            self.assertIn(words,coach)   # the first-open tip teaches the same steps as setup
        self.assertIn('id="pa-pt"',setup)   # setup's picture shows the pointer button being clicked
        self.assertNotIn('Draw on screen',ui)   # that name belongs to Atticus's own drawings
        for page in ('README.md','ui/settings.html','ui/onboarding.html'):
            self.assertIn('Point at your screen',(ROOT/page).read_text(),page)


class LiveGuideTests(unittest.TestCase):
    """A walkthrough shows the step visible now; the user's click asks for the next from the fresh screen. The user does every click."""
    target = {'pid':123,'windowID':'17','windowFrame':[0,0,800,600]}
    step = {'say':'Click Insert.','wait':True,'hit':[10,10,80,30],'shapes':[{'kind':'rect','rect':[10,10,80,30]}]}

    def setUp(self):
        self.root = scratch_dir(self)
        self.ask = self.root/'ask'; self.ask.mkdir()
        (self.ask/'draw-screens.json').write_text(json.dumps({'screens':{'1':{'frame':[0,0,800,600],'pixels':[1600,1200]}},'target':self.target}))
        atticus.save_request(str(self.ask),'set up a table')

    def draw(self, steps, target=None):
        def shown(lines): Path(json.loads(lines[0][2:])['receipt']).write_text('shown')
        with patch.dict(os.environ,{'ATTICUS_ASK':str(self.ask)}), patch.object(atticus,'wait_commit',return_value=True), \
             patch.object(atticus,'draw_target',return_value=target or self.target), patch.object(atticus,'emit',side_effect=shown) as emit:
            atticus.draw({'steps':steps})
        return json.loads(emit.call_args.args[0][0][2:])

    def gate(self, cmd, tool='Bash'):
        event = {'tool_name':tool,'tool_input':{'command':cmd} if cmd else {'file_path':'/tmp/x'}}
        with patch.dict(os.environ,{'ATTICUS_CLIENT':'claude','ATTICUS_ASK':str(self.ask)}), patch.object(atticus,'preview_commands'), \
             patch.object(atticus,'ask_user',return_value='n'), patch('sys.stdin',io.StringIO(json.dumps(event))), patch('sys.stdout',new_callable=io.StringIO) as out:
            atticus.gate()
        return json.loads(out.getvalue())['hookSpecificOutput']['permissionDecision'] if out.getvalue() else 'allow'

    def test_a_waiting_step_carries_the_goal_and_static_or_teaching_drawings_do_not(self):
        self.assertIn('never describe or guess steps behind menus or dialogs not open yet',atticus.DRAW_HELP)
        self.assertEqual(self.draw([self.step])['guide'],{'goal':'set up a table','done':['Click Insert.'],'pid':123})
        self.assertNotIn('guide',self.draw([{'say':'Insert is here.','hit':[10,10,80,30],'shapes':[{'kind':'rect','rect':[10,10,80,30]}]}]))   # "where is it": a ring, nothing more
        self.assertNotIn('guide',self.draw([{'say':'Rows run across.','shapes':[{'kind':'line','points':[[1,1],[50,1]]}]}]))   # a lesson stays a lesson
        self.assertNotIn('guide',self.draw([self.step,{'say':'Done.','shapes':[{'kind':'pointer','at':[40,40]}]}]))   # its last step waits for nothing

    def test_a_continuation_extends_its_steps_stays_in_its_app_and_ends(self):
        atticus.private_json(atticus.guide_file(str(self.ask)),{'goal':'set up a table','done':['Click Insert.'],'pid':123})
        value = self.draw([{**self.step,'say':'Click Table.'}])
        self.assertEqual(value['guide'],{'goal':'set up a table','done':['Click Insert.','Click Table.'],'pid':123})
        with self.assertRaisesRegex(ValueError,'guide stopped'): self.draw([self.step],target={**self.target,'pid':999})   # the user went to another app
        atticus.private_json(atticus.guide_file(str(self.ask)),{'goal':'set up a table','done':['step']*(atticus.GUIDE_STEPS-1),'pid':123})
        self.assertNotIn('guide',self.draw([self.step]))   # the cap: this step is the last one asked for

    def test_continuation_requests_are_validated(self):
        good = {'goal':'set up a table','done':['Click Insert.'],'pid':123}
        self.assertEqual(atticus.live_guide(good),good)
        for bad in (None,'x',{**good,'extra':1},{**good,'pid':0},{**good,'pid':True},{**good,'pid':'123'},{**good,'goal':''},
                    {**good,'goal':'x'*2001},{**good,'done':[]},{**good,'done':[1]},{**good,'done':['x']*(atticus.GUIDE_STEPS+1)}):
            with self.subTest(bad=bad): self.assertIsNone(atticus.live_guide(bad))
        context = atticus.guide_context({**good,'done':['Click Insert.','Click Table.']})
        for said in ('"set up a table"','just did "Click Table."','["Click Insert."]','--look again','[complete] + one short line','the user clicks'): self.assertIn(said,context)

    def test_a_continuation_may_only_look_read_and_draw(self):
        me = atticus.ME
        allowed = [f'{atticus.LOOK} && {atticus.DRAW} --help', atticus.LOOK, atticus.DRAW + ' \'{"steps":[]}\'', f'{atticus.HANDS} see', f'{atticus.HANDS} see Pages',
                   f'{atticus.WINDOW} Pages', f'sleep 1; {atticus.LOOK}', f'{atticus.PICK} "Which ledger?" "Q3 ledger" "Q4 ledger"']
        denied = [f'{atticus.HANDS} click Insert', f'{atticus.HANDS} menu Pages "Insert > Table"', f'{atticus.HANDS} type Name "x"', f'{atticus.HANDS} press "cmd+t"',
                  f'{atticus.LOOK} > /tmp/x', f'{atticus.LOOK} | sh', f'{atticus.LOOK} & {atticus.HANDS} click Insert', f'{atticus.LOOK} || {atticus.HANDS} click Insert',
                  f'{atticus.DRAW} "$(osascript -e x)"', f'{atticus.DRAW} `x`', 'osascript -e \'tell application "System Events" to click\'', 'open -a Pages',
                  f'python3 {me} --look', f'X=1 {atticus.LOOK}', f'{atticus.PLACE} Pages left', f'{atticus.TYPE} hello', '', '"unclosed']
        for cmd in allowed: self.assertTrue(atticus.guide_tool('Bash',cmd),cmd)
        for cmd in denied: self.assertFalse(atticus.guide_tool('Bash',cmd),cmd)
        self.assertTrue(atticus.guide_tool('Read',''))
        for tool in ('Write','Edit','WebSearch','WebFetch','mcp__fixture__send'): self.assertFalse(atticus.guide_tool(tool,''),tool)
        self.assertEqual(self.gate(f'{atticus.HANDS} click Insert'),'allow')   # a normal ask: the guide rule stays out of the way
        atticus.private_json(atticus.guide_file(str(self.ask)),{'goal':'set up a table','done':['Click Insert.'],'pid':123})
        self.assertEqual(self.gate(f'{atticus.HANDS} click Insert'),'deny')
        self.assertEqual(self.gate('osascript -e \'tell application "Pages" to activate\''),'deny')
        self.assertEqual(self.gate(None,'WebSearch'),'deny')
        self.assertEqual(self.gate(f'{atticus.LOOK} && {atticus.DRAW} --help'),'allow')
        self.assertEqual(self.gate(None,'Read'),'allow')

    def test_a_declared_walkthrough_only_looks_reads_picks_and_draws_from_its_first_tool(self):
        actions = [f'{atticus.HANDS} click Insert', f'{atticus.TYPE} hello', 'osascript -e \'tell application "Pages" to activate\'', f'{atticus.LOOK} > /tmp/x']
        self.assertEqual(self.gate(actions[0]),'allow')   # an ordinary do-it ask still acts
        atticus.guard_show(str(self.ask))   # run() writes it as soon as [show] streams; main() before every recovery turn
        self.assertTrue(Path(atticus.show_file(str(self.ask))).parent.samefile(Path(atticus.request_file(str(self.ask))).parent))   # beside the user's words, not in the ask folder
        self.assertNotEqual(Path(atticus.show_file(str(self.ask))).parent, self.ask)
        for cmd in actions: self.assertEqual(self.gate(cmd),'deny',cmd)
        self.assertEqual(self.gate(None,'WebSearch'),'deny')
        for cmd in (f'{atticus.LOOK} && {atticus.DRAW} --help', atticus.DRAW + ' \'{"steps":[]}\'', f'{atticus.PICK} "Which ledger?" "Q3 ledger" "Q4 ledger"', f'{atticus.WINDOW} Pages'):
            self.assertEqual(self.gate(cmd),'allow',cmd)
        self.assertEqual(self.gate(None,'Read'),'allow')

    def continuation(self, request, reply='Click Table in the menu that opened. Then choose 3 by 3 and press Insert. ' * 4, drew=True, ran=()):
        seen = {'calls': 0}
        def brain(prompt, *args, **kwargs):
            ask = os.environ['ATTICUS_ASK']
            seen.update(prompt=prompt, main_only=kwargs.get('main_only'), guarded=os.path.exists(atticus.guide_file(ask)), calls=seen['calls'] + 1)
            seen['click'] = self.gate_in(ask, f'{atticus.HANDS} click Table')
            brain.ok, brain.cmds, brain.ran, brain.handoff, brain.work = True, [], list(ran), None, False
            brain.observed = [{'action':'draw','result':'Guide shown (step 1 of 1). Leave it running.' if drew else 'ok','error':False}]
            return reply, .001, []
        brain = unittest.mock.Mock(side_effect=brain)
        fast, learn = unittest.mock.Mock(return_value='Instant fixture'), unittest.mock.Mock(return_value=False)
        workflow = unittest.mock.Mock(side_effect=lambda task, reply, *a: (reply, False))
        with patch.dict(os.environ,{}), patch.multiple(atticus, licensed=lambda: True, ping=lambda: None, fast=fast, learn=learn, remember_workflow=workflow,
                            front=lambda: ('Pages', 'Untitled'), osa=lambda *a: '', screens=lambda: [], describe=lambda *a: '', selection_context=lambda: '',
                            relevant_rules=lambda _: '', recent=lambda: [], workflows=lambda *a: '', screen_for=lambda *a: None, wait_commit=lambda: True,
                            run=brain, remember_turn=lambda *a: None, restore_focus=lambda *a: None, tip=lambda *a: None, start_ai=lambda *a: None,
                            log_turn=lambda *a, **k: None, window_summary=lambda *a: {}), \
             patch.object(atticus.os,'setpgrp'), patch.object(atticus.signal,'signal'), patch.object(atticus.threading,'Thread'), \
             patch('sys.argv',['atticus.py','--wait']), patch('sys.stdin',io.StringIO(json.dumps(request)+'\n')), patch('sys.stdout',new_callable=io.StringIO) as out:
            atticus.main()
        return seen, fast, learn, workflow, out.getvalue()

    def gate_in(self, ask, cmd):
        event = {'tool_name':'Bash','tool_input':{'command':cmd}}
        with patch.dict(os.environ,{'ATTICUS_CLIENT':'claude','ATTICUS_ASK':ask}), patch.object(atticus,'preview_commands'), \
             patch.object(atticus,'ask_user',return_value='n'), patch('sys.stdin',io.StringIO(json.dumps(event))), patch('sys.stdout',new_callable=io.StringIO) as out:
            atticus.gate()
        return json.loads(out.getvalue())['hookSpecificOutput']['permissionDecision'] if out.getvalue() else 'allow'

    def test_the_next_step_is_asked_with_the_goal_and_never_acts_or_repeats_the_answer(self):
        guide = {'goal':'set up a table','done':['Click Insert.'],'pid':123}
        seen, fast, learn, workflow, out = self.continuation({'front':'Pages','task':'set up a table','guide':guide})
        fast.assert_not_called(); learn.assert_not_called()   # no instant replay or learned shortcut runs for the user
        self.assertFalse(workflow.call_args.args[2])
        self.assertTrue(seen['guarded'] and seen['main_only'])
        self.assertEqual(seen['click'],'deny')   # the model cannot click for the user
        self.assertIn('Live guide (data): the user is doing "set up a table" and just did "Click Insert."',seen['prompt'])
        self.assertIn('✓ Done. Steps are on screen.',out); self.assertNotIn('Click Table in the menu',out)   # the step is on screen, not in a big answer
        self.assertEqual(seen['calls'],1)
        seen, *_ , out = self.continuation({'front':'Pages','task':'set up a table','guide':guide}, reply='[show] [complete] Your table is in.', drew=False, ran=[atticus.LOOK])
        self.assertIn('✓ Your table is in.',out); self.assertEqual(seen['calls'],1)   # observed done: one short line, no new drawing
        self.assertNotIn('Showing it on screen',out); self.assertNotIn('[complete]',out)
        seen, fast, *_ = self.continuation({'front':'Pages','task':'set up a table','guide':{**guide,'pid':-1}})
        fast.assert_called_once()   # a forged or broken guide is just an ordinary ask
        self.assertNotIn('Live guide',seen.get('prompt',''))

    def test_the_app_continues_only_after_the_users_step_and_drops_it_on_cancel(self):
        source = (ROOT/'Atticus.swift').read_text()
        app = source.split('final class App: NSObject, WKScriptMessageHandler {',1)[1]
        section = lambda start, end: app.split(start,1)[1].split(end,1)[0]
        self.assertIn('drawing.proceed = { [weak self] in self?.continueGuide($0) }',app)
        resume = section('func continueGuide(','func finish()')
        self.assertIn('drawing.eligible(guide.pid)',resume)   # another app in front: the guide stops
        self.assertIn('if engine.isRunning || dictating { return }',resume)   # the user is talking: their ask wins
        self.assertIn('run(guide.goal, guide: guide)',resume)
        self.assertNotIn('Hands.',resume)
        self.assertIn('drawing.detach()',section('func cancel()','func close('))
        self.assertIn('if guide == nil { drawing.detach() }',section('func run(_ t:','// MARK: - Agent panels'))
        self.assertIn('if let guide { request["guide"] = ["goal":guide.goal, "done":guide.done, "pid":guide.pid] }',app)
        self.assertIn('"Your next step is on screen."',app)
        drawing = source.split('final class ScreenDrawing {',1)[1].split('// The box can take typing',1)[0]
        self.assertNotIn('.post(',drawing)   # a guide never clicks or types for the user
        self.assertIn('dropPending()\n        timer?.invalidate()',drawing)   # clear() takes a waiting next step with it


class ShowDeliveryTests(unittest.TestCase):
    """Every main reply decides how it reaches the user ([show] or [text], or a draft, action or drawing); a broken decision gets one held turn."""
    guide = {'goal':'add a margin note','done':['Click Annotate.'],'pid':123}

    def setUp(self):
        self.root = scratch_dir(self)

    def ask(self, task, *runs, prefs=None, guide=None):
        script, seen = list(runs), []
        def brain(prompt, *args, **kwargs):
            r, ask = script.pop(0), os.environ['ATTICUS_ASK']
            seen.append({'prompt': prompt, 'main_only': kwargs.get('main_only'), 'click': LiveGuideTests.gate_in(self, ask, f'{atticus.HANDS} click Annotate'),
                         'pick': LiveGuideTests.gate_in(self, ask, f'{atticus.PICK} "Which ledger?" "Q3 ledger" "Q4 ledger"')})
            brain.ok, brain.cmds, brain.ran, brain.handoff, brain.work = r.get('ok', True), [], r.get('ran', []), None, False
            brain.modes, brain.error = set(r.get('modes', ())), r.get('error', '')
            brain.observed = r.get('observed', [{'action': 'draw', 'error': False, 'result': 'Guide shown (step 1 of 1). Leave it running.'}] if r.get('drew') else [])
            return r['reply'], .001, []
        brain = unittest.mock.Mock(side_effect=brain)
        pref = (lambda k, d=None: prefs.get(k, d)) if prefs else (lambda k, d=None: d)
        request = {'front':'Lumen Ledger','task':task, **({'guide': guide} if guide else {})}
        with patch.dict(os.environ,{}), patch.multiple(atticus, licensed=lambda: True, ping=lambda: None, fast=lambda *a: None, learn=lambda *a: False,
                            remember_workflow=lambda task, reply, *a: (reply, False), front=lambda: ('Lumen Ledger', 'Draft'), osa=lambda *a: '', screens=lambda: [],
                            describe=lambda *a: '', selection_context=lambda: '', relevant_rules=lambda _: '', recent=lambda: [], workflows=lambda *a: '',
                            screen_for=lambda *a: None, wait_commit=lambda: True, run=brain, remember_turn=lambda *a: None, restore_focus=lambda *a: None,
                            tip=lambda *a: None, start_ai=lambda *a: None, log_turn=lambda *a, **k: None, window_summary=lambda *a: {}, pref=pref, report=lambda *a: None), \
             patch.object(atticus.os,'setpgrp'), patch.object(atticus.signal,'signal'), patch.object(atticus.threading,'Thread'), \
             patch('sys.argv',['atticus.py','--wait']), patch('sys.stdin',io.StringIO(json.dumps(request)+'\n')), \
             patch('sys.stdout',new_callable=io.StringIO) as out:
            atticus.main()
        self.assertFalse(script, 'every scripted model turn runs')
        return seen, out.getvalue()

    def test_a_walkthrough_answered_in_text_is_shown_once_on_screen(self):
        seen, out = self.ask('Show me how to add a margin note here',
                             {'reply': 'Open the Annotate menu, then choose Margin Note.', 'modes': {'show'}},   # [show] in a note before a tool
                             {'reply': 'Step one is on screen.', 'drew': True})
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0]['click'], 'allow')   # fake run(): only run() itself writes the marker as [show] streams (FlowTests)
        self.assertTrue(seen[1]['main_only'])   # the recovery stays in the box the user is watching
        self.assertEqual((seen[1]['click'], seen[1]['pick']), ('deny', 'allow'))   # and only looks, reads, picks and draws
        self.assertIn('Your text answer was not shown', seen[1]['prompt'])
        self.assertIn('✓ Done. Steps are on screen.', out)
        self.assertNotIn('[show]', out); self.assertNotIn('Annotate menu', out)
        seen, out = self.ask('Show me how to add a margin note here',   # the tag in the final text alone is enough
                             {'reply': '[show] Open the Annotate menu, then choose Margin Note.'}, {'reply': 'On screen.', 'drew': True})
        self.assertEqual(len(seen), 2)

    def test_intent_declared_before_a_clarifying_choice_survives_it(self):
        pick = f'{atticus.PICK} "Which ledger?" "Q3 ledger" "Q4 ledger"'
        seen, out = self.ask('Show me how to lock this ledger',
                             {'reply': 'Choose Protect, then Lock Sheet.', 'modes': {'show'}, 'ran': [pick, f'{atticus.WINDOW} "Lumen Ledger"'],
                              'observed': [{'action': pick, 'error': False, 'result': 'Q4 ledger'}]},
                             {'reply': 'On screen.', 'drew': True})
        self.assertEqual(len(seen), 2)
        self.assertIn('Prior work', seen[1]['prompt']); self.assertIn('Q4 ledger', seen[1]['prompt'])   # the user's pick carries into the recovery
        self.assertIn('✓ Done. Steps are on screen.', out)

    def test_decided_text_drafts_actions_and_drawn_guides_run_once(self):
        place = f'{atticus.PLACE} "Quill Notes" left laptop'
        for reply, ran in (('[text] A margin note sits beside the text it explains.', []), ('[text] Written steps: open Annotate, then Margin Note.', []),
                           ('[draft] Dear Ms. Vale, the ledger is ready.', []), ('[text]\n[draft] Dear Ms. Vale, the ledger is ready.', []),
                           ('Moved Quill Notes to the left screen.', [place])):   # a real action is its own delivery
            with self.subTest(reply=reply):
                seen, out = self.ask('Tell me about margin notes', {'reply': reply, 'ran': ran})
                self.assertEqual(len(seen), 1); self.assertNotIn('Showing it on screen', out); self.assertNotIn('[text]', out)
        seen, out = self.ask('Show me how to add a margin note here', {'reply': '[show] Steps are up.', 'drew': True})
        self.assertEqual(len(seen), 1); self.assertIn('✓ Done. Steps are on screen.', out)

    def test_an_undecided_reply_gets_one_held_turn_to_decide_never_a_silent_text_answer(self):
        answer = 'Open the Annotate menu, then choose Margin Note.'
        seen, out = self.ask('Can I add a margin note here?', {'reply': answer, 'ran': [f'{atticus.WINDOW} "Lumen Ledger"']}, {'reply': '[text]'})
        self.assertEqual(len(seen), 2); self.assertTrue(seen[1]['main_only'])
        self.assertIn('began with neither [show] nor [text]: ' + json.dumps(answer), seen[1]['prompt'])
        self.assertEqual((seen[1]['click'], seen[1]['pick']), ('deny', 'allow'))   # deciding cannot act for the user
        self.assertIn('✓ ' + answer, out); self.assertNotIn('Showing it on screen', out)   # [text] alone: that answer stands
        seen, out = self.ask('Can I add a margin note here?', {'reply': answer}, {'reply': '[show] On screen.', 'drew': True})
        self.assertEqual(len(seen), 2); self.assertIn('✓ Done. Steps are on screen.', out); self.assertNotIn(answer, out)
        seen, out = self.ask('Can I add a margin note here?', {'reply': answer}, {'reply': answer})   # undecided twice: bounded, and an honest failure
        self.assertEqual(len(seen), 2)
        self.assertIn('! I couldn’t tell whether to show this on screen or write it out. Please ask again and say which.', out)
        self.assertNotIn(answer, out); self.assertNotIn('✓', out); self.assertNotIn('[text]', out)
        seen, out = self.ask('Can I add a margin note here?', {'reply': answer}, {'reply': '[show] Could not read the screen.', 'error': 'Screen Recording is off.'})
        self.assertEqual(len(seen), 2); self.assertIn('Couldn’t show this on screen: Screen Recording is off.', out); self.assertNotIn('Steps are on screen', out)

    def test_a_live_guide_ends_on_observed_completion_and_an_instruction_only_step_is_drawn(self):
        seen, out = self.ask('add a margin note', {'reply': '[show]\n[complete] The margin note is in.', 'ran': [atticus.LOOK]}, guide=self.guide)
        self.assertEqual(len(seen), 1); self.assertEqual(seen[0]['click'], 'deny')
        self.assertIn('✓ The margin note is in.', out); self.assertNotIn('Showing it on screen', out); self.assertNotIn('Couldn’t show', out)
        seen, out = self.ask('add a margin note', {'reply': '[show] Now click Margin Note in the menu.', 'ran': [atticus.LOOK]},
                             {'reply': 'On screen.', 'drew': True, 'ran': [atticus.LOOK]}, guide=self.guide)
        self.assertEqual(len(seen), 2); self.assertEqual(seen[1]['click'], 'deny')
        self.assertIn('Your text answer was not shown', seen[1]['prompt']); self.assertIn('[complete] + one short line', seen[1]['prompt'])
        self.assertIn('✓ Done. Steps are on screen.', out); self.assertNotIn('click Margin Note', out)
        seen, out = self.ask('add a margin note', {'reply': '[complete] Done.'}, {'reply': '[complete] The margin note is in.', 'ran': [atticus.LOOK]}, guide=self.guide)
        self.assertEqual(len(seen), 2); self.assertIn('✓ The margin note is in.', out)   # done is believed only after a fresh --look
        seen, out = self.ask('add a margin note', {'reply': '[text] Click Margin Note.'}, {'reply': '[text] Click Margin Note.'}, guide=self.guide)
        self.assertEqual(len(seen), 2); self.assertIn('Couldn’t show this on screen', out)   # [text] is no way out of a live guide's next step

    def test_drawings_off_or_unavailable_answer_in_text_and_say_why(self):
        for reply in ('[show] Open Annotate, then Margin Note.', 'Open Annotate, then Margin Note.'):
            seen, out = self.ask('Show me how to add a margin note here', {'reply': reply}, prefs={'draw': False})
            self.assertEqual(len(seen), 1); self.assertIn('✓ Open Annotate, then Margin Note.', out)   # no contract without drawings
        seen, out = self.ask('Show me how to add a margin note here', {'reply': '[show] Open Annotate, then Margin Note.'},
                             {'reply': 'Done, it is on screen.', 'ok': False, 'error': 'Screen Recording is off for Atticus.',
                              'observed': [{'action': 'draw', 'error': True, 'result': 'Screen Recording is off for Atticus.'}]})
        self.assertEqual(len(seen), 2)   # one recovery, never a loop
        self.assertIn('Open Annotate, then Margin Note.', out)
        self.assertIn('Couldn’t show this on screen: Screen Recording is off for Atticus.', out)
        self.assertNotIn('Done, it is on screen', out); self.assertNotIn('Steps are on screen', out)   # no success claimed without draw()'s receipt

    def test_devin_and_pi_read_draws_receipt_from_their_ask_folder(self):
        ask = self.root/'client-ask'; ask.mkdir()
        self.assertEqual(atticus.shown_receipts(str(ask)), [])
        (ask/'guide-shown').write_text('Guide shown (step 1 of 2). Leave it running.')
        self.assertTrue(atticus.guide_shown(atticus.shown_receipts(str(ask))))
        self.assertFalse(atticus.guide_shown([{'error': True, 'result': 'Guide shown (step 1 of 1).'}, {'error': False, 'result': 'I showed it.'}]))
        self.assertIn('First output, before any tool or choice: [show] for UI where/how asks', atticus.DRAWING)
        for body in ('[draft] Please type [text] here', '[draft] counts[text] += el[show]', 'Explain the literal [show] marker [complete]'):   # only the first output is a tag
            self.assertEqual(atticus.untagged(body), body); self.assertEqual(atticus.declare(body), set())
            self.assertEqual(atticus.untagged('[text] ' + body), body); self.assertEqual(atticus.declare('[text] ' + body), {'text'})
        self.assertEqual(atticus.untagged('[text][draft] x'), '[draft] x'); self.assertEqual(atticus.untagged('[show]\n[complete] Done.'), 'Done.')


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
const parts = { '.chip i': el(), '.rm': el(), '.gotit': el(), '.hint': el(), img: el({ hidden: true }) };
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
if (markShot() !== 'data:image/jpeg;base64,AA') fail('the next ask would not carry the marked crop');
ui.point({ active: false, marked: true });
if (bar.dataset.s !== 'marked' || img.src !== 'data:image/jpeg;base64,AA' || els.status.textContent !== 'Marked' || els.point.getAttribute('aria-pressed') !== 'false') fail('leaving point mode lost the chip');
parts['.rm'].onclick();
if (messages.filter(m => m.pointClear).length !== 1) fail('the chip does not reach the app');
ui.point(false);
if (bar.dataset.s || !img.hidden || img.src || els.status.textContent !== '' || els.point.classList.contains('marked')) fail('clearing left the chip or status');
if (markShot()) fail('a cleared mark would still go with the next ask');
status('Thinking…'); ui.point(false); if (els.status.textContent !== 'Thinking…') fail('clearing a mark wiped another status');
ui.point({ active: false, marked: true, thumb: '' }); if (!img.hidden || markShot()) fail('an empty thumbnail showed a broken image');
working = true; const before = messages.length; els.point.onclick();
if (messages.slice(before).some(m => m.point) || els.status.textContent !== 'Finish or stop the current answer first') fail('pointing during an answer gave no reason');
'''
        result = subprocess.run(['node','--input-type=module'],input=script,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        listen = page[page.index('    listen(keep) {'):page.index('    level(v) {')]
        self.assertIn("!document.body.classList.contains('dictate') && markShot()",listen)   # the sent bubble shows the crop; dictation never does
        run = (ROOT/'Atticus.swift').read_text().split('    func run(_ t: String',1)[1]
        self.assertLess(run.index('pointContext = nil'),run.index('drawing.clearInput()'))   # sending takes the mark off the screen but keeps its crop for the worker


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
func refused(_ d: Data) -> String {   // which check turned a guide away
 guard let r = try? JSONDecoder().decode(DrawingRequest.self,from:d) else { return "did not decode" }
 let w = (CGWindowListCopyWindowInfo(.optionIncludingWindow,CGWindowID(window.windowNumber)) as? [[String:Any]])?.first?[kCGWindowBounds as String]
 return "valid \(ScreenDrawing.valid(r)) on displays \(ScreenDrawing.onDisplays(r)) window current \(ScreenDrawing.current(r.target)) (now \(String(describing: w)), sent \(r.target.windowFrame)) screens \(NSScreen.screens.map(\.frame))"
}
let drawing = ScreenDrawing()
var marked: [CGPoint] = []
drawing.beginInput { marked = $0 }
precondition(drawing.inputPanels.count == NSScreen.screens.count && drawing.inputPanels.allSatisfy { !$0.ignoresMouseEvents && !$0.canBecomeKey && !$0.canBecomeMain })
precondition(app.keyWindow === keyBefore && NSWorkspace.shared.frontmostApplication?.processIdentifier == frontBefore,
             "Point input changed the focused app or key window")
precondition(drawing.inputPanels.allSatisfy { ($0.contentView as? DrawingView)?.pointing == true && $0.acceptsMouseMovedEvents },"Pointing has no crosshair cursor")
drawing.startInput(CGPoint(x:x+100,y:y+200)); drawing.moveInput(CGPoint(x:x+140,y:y+240)); drawing.endInput(CGPoint(x:x+140,y:y+240))
precondition(marked.count == 2 && drawing.inputMode && drawing.inputPanels.allSatisfy { !$0.ignoresMouseEvents },"A stroke ended pointing at once")
precondition(drawing.inputPanels.allSatisfy { $0.level.rawValue < NSWindow.Level.statusBar.rawValue },"Pointing can cover Atticus's own panels")
drawing.startInput(CGPoint(x:x+300,y:y+300)); drawing.endInput(CGPoint(x:x+300,y:y+300))
precondition(marked == [CGPoint(x:x+300,y:y+300)] && drawing.inputPath.count == 1,"A new stroke did not replace the last mark")
drawing.inputAway = { drawing.finishInput() }
drawing.hoverInput(CGPoint(x:x+340,y:y+340)); precondition(drawing.inputMode,"Moving near the mark ended pointing")
drawing.hoverInput(CGPoint(x:x+500,y:y+300))
precondition(!drawing.inputMode && drawing.hasInput && drawing.inputPanels.allSatisfy { $0.ignoresMouseEvents && ($0.contentView as? DrawingView)?.pointing == false },"Moving off the mark did not keep it and hand clicks back")
drawing.startInput(CGPoint(x:x+10,y:y+10)); precondition(drawing.inputPath.count == 1,"A click after pointing changed the mark")
drawing.clear(); precondition(!drawing.hasInput && drawing.inputPanels.isEmpty,"Point input did not clear")
drawing.beginInput { _ in }; drawing.hoverInput(nil); precondition(drawing.inputMode,"Leaving before any mark ended pointing")
drawing.inputAway = nil
var cleared = 0; drawing.inputCleared = { cleared += 1 }
drawing.finishInput()
precondition(!drawing.hasInput && drawing.inputPanels.isEmpty && cleared == 1,"Turning pointing off with no mark did not cancel")
drawing.inputCleared = nil
precondition(drawing.receive(data(steps)),refused(data(steps)))
precondition(drawing.panels.count == NSScreen.screens.count)
drawing.beginInput { _ in }; precondition(drawing.active && drawing.panels.count == NSScreen.screens.count,"Pointing cleared the guide")
drawing.clearInput(); precondition(drawing.active && drawing.inputPanels.isEmpty,"Clearing a mark took the guide")
var picked = ""; drawing.picked = { _, words in picked = words }
let markView = drawing.panels.compactMap { $0.contentView as? DrawingView }.first { $0.hits.contains { $0.shape == 2 } }!
let legA = markView.hits.first { $0.shape == 2 }!.area.boundingBoxOfPath.offsetBy(dx:markView.origin.x,dy:markView.origin.y)
drawing.pick(CGPoint(x:legA.midX,y:legA.midY))
precondition(picked.hasPrefix("label \"Leg A\" in step 1 of 3") && drawing.selected?.shape == 2 && drawing.manual,"Clicking a mark did not select it: \(picked)")
precondition(markView.layer!.sublayers!.contains { $0.name == "pick" },"The selected mark has no highlight")
drawing.deselect(); precondition(drawing.selected == nil && !markView.layer!.sublayers!.contains { $0.name == "pick" })
drawing.manual = false; drawing.picked = nil
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
let lesson: [[String:Any]] = [["say":"Draw the square.","shapes":[["kind":"rect","rect":[x+60,y+150,200,200]]]],
                              ["say":"Label its side.","shapes":[["kind":"label","at":[x+160,y+250],"text":"x"]]]]
precondition(drawing.receive(data(lesson,teaching:true)) && drawing.calloutPanel?.isVisible == true,"Whiteboard step had no callout")
precondition(!drawing.calloutPanel!.frame.intersects(CGRect(x:x+60,y:NSScreen.screens[0].frame.maxY-(y+350),width:200,height:200)),"Callout covered its mark")
drawing.advanceAt = .distantPast; drawing.tick(); precondition(drawing.index == 1,"Auto step did not advance")
drawing.back(); precondition(drawing.index == 0 && drawing.manual,"Back did not return to the last step")
drawing.advanceAt = .distantPast; drawing.tick(); precondition(drawing.index == 0,"Auto steps fought the user's Back")
drawing.next(); precondition(drawing.index == 1); drawing.next(); precondition(!drawing.active,"Done on the last step did not clear")
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
// A live guide: the user's click on its last step asks for the next once the app settles; Esc, another ask or drawing drops that.
let pid = ProcessInfo.processInfo.processIdentifier
func live(_ step: [String:Any] = steps[1], teaching: Bool = false, guidePid: Int32 = pid) -> Data {
 try! JSONSerialization.data(withJSONObject:["steps":[step],"teaching":teaching,"target":target,"state":"fixture",
                                             "guide":["goal":"Set up the fixture","done":["Click the control."],"pid":guidePid]])
}
var asked: [DrawingGuide] = []; drawing.proceed = { asked.append($0) }
var front = true; drawing.eligible = { $0 == pid && front }   // which app is in front, without touching the real one
precondition(!drawing.session,"A static drawing or lesson started a guide session")
precondition(drawing.receive(live()) && drawing.request?.guide != nil,refused(live()))
let liveButtons = (drawing.calloutPanel?.contentView?.subviews ?? []).compactMap { ($0 as? NSButton)?.title }
precondition(liveButtons.contains("Next") && !liveButtons.contains("Done"),"A live step has no Next for clicks Atticus cannot see: \(liveButtons)")
precondition((drawing.panels + [drawing.calloutPanel!]).allSatisfy { $0.level.rawValue > NSWindow.Level.popUpMenu.rawValue },"Marks sit under the menu a click opened")
drawing.ready = .distantPast
drawing.clicked(CGPoint(x:x+800,y:y+500)); precondition(drawing.active && drawing.pending == nil,"An outside click continued the guide")
drawing.clicked(CGPoint(x:x+450,y:y+365))
precondition(!drawing.active && drawing.pending != nil && asked.isEmpty,"The guide asked before the app settled, or kept its stale marks")
precondition(drawing.holds,"The box could close between the click and the next step")   // the user's click lands in this gap
pump(1.2); precondition(asked.count == 1 && asked[0].done == ["Click the control."] && asked[0].pid == pid && drawing.pending == nil,"The click did not ask for the next step")
precondition(drawing.holds && drawing.session,"The box let go of the guide while its next step was being asked")
precondition(drawing.receive(live())); drawing.ready = .distantPast; drawing.clicked(CGPoint(x:x+450,y:y+365)); drawing.clear(); pump(1.2)
precondition(asked.count == 1,"Esc after the click still asked for the next step")
precondition(drawing.receive(live())); drawing.next(); precondition(drawing.pending != nil,"Next on a live step did not continue")
drawing.dropPending(); pump(1.2); precondition(asked.count == 1,"A cancelled ask still continued the guide")
precondition(drawing.receive(live())); drawing.next(); precondition(drawing.receive(data(steps)) && drawing.pending == nil,"A new drawing kept the old guide's next step")
pump(1.2); precondition(asked.count == 1,"A stale continuation fired over a newer drawing")
value = 0; precondition(drawing.receive(live(["target":"Exact control","wait":true,"shapes":[["kind":"rect"]]])))
drawing.ready = .distantPast; value = 1; drawing.tick(); pump(1.2); precondition(asked.count == 2 && !drawing.active,"A value change did not continue the guide")
// A follow-up ask (typed, or the shortcut held over the guide) or a cancel keeps the marks, but the old goal stops continuing on its own.
precondition(drawing.receive(live())); drawing.hold(); drawing.ready = .distantPast; drawing.clicked(CGPoint(x:x+450,y:y+365)); pump(1.2)
precondition(!drawing.active && drawing.pending == nil && asked.count == 2,"A click on the old target resumed its goal after another ask")
precondition(drawing.receive(live())); drawing.detach(); precondition(drawing.active,"Cancel took the guide's marks")
value = 0; precondition(drawing.receive(live(["target":"Exact control","wait":true,"shapes":[["kind":"rect"]]]))); drawing.detach()
drawing.ready = .distantPast; value = 1; drawing.tick(); pump(1.2); precondition(!drawing.active && asked.count == 2,"A value change resumed a cancelled guide")
precondition(drawing.receive(live())); drawing.hold(); drawing.next(); pump(1.2); precondition(asked.count == 3,"An explicit Next after a follow-up did not continue")
precondition(drawing.receive(live()) && !drawing.detached,"A new guide kept the old one's detach")
drawing.clear()
precondition(drawing.holds,"Clearing a step's marks ended the guide the user is in")
var changes = 0; drawing.changed = { changes += 1 }
drawing.end(); precondition(!drawing.holds && changes == 1,"Closing did not release the guide, or the box was not told to go home")
drawing.end(); drawing.changed = nil; precondition(changes == 1,"Ending nothing moved the box")
// The user switched apps while the next step was being read: it never shows. Static drawings do not depend on the front app.
front = false
let receipt = NSTemporaryDirectory() + "live-receipt-\(UUID().uuidString)"
var stale = try! JSONSerialization.jsonObject(with:live()) as! [String:Any]; stale["receipt"] = receipt
precondition(!drawing.receive(try! JSONSerialization.data(withJSONObject:stale)) && !drawing.active,"A stale guide showed in an app the user left")
precondition((try? String(contentsOfFile:receipt,encoding:.utf8))?.contains("no longer in front") == true,"A stale guide left its ask waiting"); try? FileManager.default.removeItem(atPath:receipt)
precondition(drawing.receive(data(steps)),"A static drawing needed its app in front"); drawing.clear(); front = true
// Clicks: the target app's windows at any layer; the system's menu bar only on the waiting target while the app is in front.
func win(_ owner: Int32, _ layer: Int, _ r: CGRect) -> [String:Any] { [kCGWindowOwnerPID as String:NSNumber(value:owner),kCGWindowLayer as String:layer,kCGWindowBounds as String:r.dictionaryRepresentation] }
let guided: Int32 = pid+1, other: Int32 = pid+2, bar = Int(CGWindowLevelForKey(.mainMenuWindow)), menuTitle = CGRect(x:200,y:0,width:50,height:24), onTitle = CGPoint(x:220,y:10)
let menuBar = [win(other,bar,CGRect(x:0,y:0,width:3000,height:24)),win(other,-2147483623,CGRect(x:0,y:0,width:3000,height:2000))]
precondition(ScreenDrawing.inApp(onTitle,menuBar,pid:guided,hit:menuTitle,front:true),"A click on the app's own menu-bar title was not seen")
precondition(!ScreenDrawing.inApp(onTitle,menuBar,pid:guided,hit:menuTitle,front:false),"A menu-bar click counted for an app that is not in front")
precondition(!ScreenDrawing.inApp(CGPoint(x:400,y:10),menuBar,pid:guided,hit:menuTitle,front:true) && !ScreenDrawing.inApp(onTitle,menuBar,pid:guided,hit:nil,front:true),"A menu-bar click off the waiting target counted")
precondition(!ScreenDrawing.inApp(onTitle,[win(other,bar+1,menuTitle)] + menuBar,pid:guided,hit:menuTitle,front:true),"Another app's menu-bar item counted")
precondition(!ScreenDrawing.inApp(onTitle,[win(other,0,menuTitle)],pid:guided,hit:menuTitle,front:true),"Another app's window counted")
precondition(ScreenDrawing.inApp(onTitle,[win(guided,101,menuTitle)] + menuBar,pid:guided,hit:nil,front:false),"A click in the app's own menu was not seen")
var still = steps[1]; still["wait"] = false   // "where is it": a ring that waits for nothing
precondition(!drawing.receive(live(guidePid:pid+1)) && !drawing.receive(live(still)) && !drawing.receive(live(lesson[0],teaching:true)),"Native accepted a guide for another app, a step that waits for nothing, or a lesson")
precondition(drawing.receive(data([still])),refused(data([still]))); drawing.next(); pump(1.2)
precondition(!drawing.active && asked.count == 3,"Static pointing asked for more steps")
drawing.proceed = nil
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


GEOMETRY = r'''
import Cocoa
func applySharing(_ window: NSWindow) {}
__DRAWING__
let gap = ScreenDrawing.gap, t = CGRect(x:100,y:100,width:80,height:20)
func inEllipse(_ p: CGPoint, _ e: CGRect) -> Bool { let dx = (p.x-e.midX)/(e.width/2), dy = (p.y-e.midY)/(e.height/2); return dx*dx+dy*dy <= 1 }
let corners = [CGPoint(x:t.minX,y:t.minY),CGPoint(x:t.maxX,y:t.minY),CGPoint(x:t.minX,y:t.maxY),CGPoint(x:t.maxX,y:t.maxY)]
precondition(ScreenDrawing.ring(t,circle:false).insetBy(dx:1.5+gap,dy:1.5+gap) == t,"A box's stroke must sit outside its target")
precondition(corners.allSatisfy { inEllipse($0,ScreenDrawing.ring(t,circle:true).insetBy(dx:1.5,dy:1.5)) },"A circle's stroke cut through its target")
let tip = ScreenDrawing.arrowTip(from:CGPoint(x:300,y:110),to:CGPoint(x:140,y:110),avoiding:[t])
precondition(!t.insetBy(dx:-gap,dy:-gap).contains(tip) && tip.x > t.maxX && tip.x < t.maxX+gap+4,"An arrow head landed on its target: \(tip)")
precondition(ScreenDrawing.arrowTip(from:.zero,to:CGPoint(x:50,y:50),avoiding:[t]) == CGPoint(x:50,y:50),"An arrow to open space moved")
precondition(!t.contains(ScreenDrawing.beside(CGPoint(x:t.midX,y:t.midY),[t])) && ScreenDrawing.beside(CGPoint(x:5,y:5),[t]) == CGPoint(x:5,y:5))
let lead = ScreenDrawing.leader(from:CGRect(x:600,y:80,width:340,height:120),to:t)!
precondition(lead.0 == CGPoint(x:600,y:110) && !t.insetBy(dx:-gap,dy:-gap).contains(lead.1) && lead.1.x > t.maxX && lead.1.x < t.maxX+gap+4,"The leader line does not run from the box edge to just outside its target: \(lead)")
precondition(ScreenDrawing.leader(from:CGRect(x:190,y:90,width:340,height:120),to:t) == nil,"A target beside the box got a leader line")
let area = CGRect(x:0,y:0,width:1000,height:800), keep = [t.insetBy(dx:-gap,dy:-gap)], tag = CGSize(width:60,height:26)
let onTarget = ScreenDrawing.labelBox(tag,at:CGPoint(x:t.midX,y:t.midY),keepOff:keep,in:area)
precondition(!keep[0].intersects(onTarget) && area.contains(onTarget),"A label covered the thing it names")
precondition(ScreenDrawing.labelBox(tag,at:CGPoint(x:500,y:500),keepOff:keep,in:area).origin == CGPoint(x:512,y:470),"A free label moved")
precondition(area.contains(ScreenDrawing.labelBox(tag,at:CGPoint(x:995,y:2),keepOff:[],in:area)),"A label left the screen")
let square = CGRect(x:300,y:300,width:200,height:200), inside = ScreenDrawing.labelBox(tag,at:CGPoint(x:380,y:420),keepOff:[square],in:area)
precondition(inside.origin == CGPoint(x:392,y:390),"An area-model label was pushed out of its box")
let edgeLabel = ScreenDrawing.labelBox(tag,at:CGPoint(x:490,y:420),keepOff:[square],in:area)
precondition(!edgeLabel.intersects(square) || square.insetBy(dx:2*gap,dy:2*gap).contains(edgeLabel),"A label crossed a mark's edge")

let view = DrawingView(frame:CGRect(x:0,y:0,width:1000,height:800)); view.origin = CGPoint(x:-200,y:50)
let g = CGRect(x:100,y:300,width:120,height:24)
let drawn = view.render([DrawingShape(kind:"circle",rect:[100,300,120,24]),DrawingShape(kind:"label",at:[160,312],text:"x² + 6x"),
                         DrawingShape(kind:"arrow",points:[[500,312],[160,312]],color:"blue")],animate:false,previous:nil)
precondition(drawn.contains(g),"Drawn bounds miss the ring")
let layers = view.layer!.sublayers!, global = { (r: CGRect) in r.offsetBy(dx:view.origin.x,dy:view.origin.y) }
for text in layers.compactMap({ $0 as? CATextLayer }) { precondition(!global(text.frame).intersects(g),"Label text sits on its target") }
let arrow = layers.compactMap { $0 as? CAShapeLayer }.first { $0.strokeColor == NSColor.systemBlue.cgColor }!
precondition(global(arrow.path!.boundingBoxOfPath).minX > g.maxX,"Arrow head sits on its target")
let diagram = DrawingView(frame:CGRect(x:0,y:0,width:1000,height:800))
diagram.render([DrawingShape(kind:"circle",rect:[100,100,300,220],color:"green",fill:true),
                DrawingShape(kind:"label",at:[250,210],text:"Cell membrane",color:"blue",size:"l")],animate:false,previous:nil)
let part = diagram.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first { $0.strokeColor == NSColor.systemGreen.cgColor }!
precondition(part.path!.boundingBoxOfPath == CGRect(x:100,y:100,width:300,height:220) && (part.fillColor?.alpha ?? 0) > 0,
             "A filled ellipse is not an exact, visible diagram part")
precondition(diagram.layer!.sublayers!.compactMap { $0 as? CATextLayer }.first!.frame.height > 20,"A large diagram label stayed tiny")
let dim = DrawingView(frame:view.frame); dim.render([DrawingShape(kind:"line",points:[[1,2],[30,40]])],animate:false,previous:nil,dim:true)
precondition(dim.layer!.sublayers!.allSatisfy { $0.opacity == 0.5 },"Earlier whiteboard steps are not quieter")
let boardFrame = CGRect(x:0,y:0,width:300,height:100), boardPad: CGFloat = 8
let boardLines = [
    ScreenDrawing.BoardLine(text:NSAttributedString(string:"First"),rect:CGRect(x:8,y:10,width:100,height:20),step:0,shape:0),
    ScreenDrawing.BoardLine(text:NSAttributedString(string:"Middle"),rect:CGRect(x:8,y:70,width:100,height:20),step:1,shape:0),
    ScreenDrawing.BoardLine(text:NSAttributedString(string:"Later"),rect:CGRect(x:8,y:150,width:100,height:30),step:2,shape:0)]
let laterPage = ScreenDrawing.boardPage((boardFrame,boardPad,boardLines),through:2)!
precondition(laterPage.lines.contains { $0.step == 2 } && laterPage.lines.allSatisfy { $0.rect.minY >= boardPad && $0.rect.maxY <= boardFrame.maxY-boardPad },
             "Long whiteboard dropped or clipped the active step")
let earlierPage = ScreenDrawing.boardPage((boardFrame,boardPad,boardLines),through:0)!
precondition(earlierPage.lines.map(\.step) == [0],"Back could not page earlier whiteboard text into view")

let size = CGSize(width:240,height:120), marks = CGRect(x:100,y:100,width:200,height:50)
var (card, side) = ScreenDrawing.calloutFrame(size,marks:marks,avoid:[],in:area)
precondition(side == .minX && card.minX > marks.maxX && card.minX-marks.maxX < 24 && !card.intersects(marks),"Callout is not beside its marks")
let edge = CGRect(x:700,y:100,width:250,height:50)
(card, side) = ScreenDrawing.calloutFrame(size,marks:edge,avoid:[],in:area)
precondition(side == .maxX && card.maxX < edge.minX && area.contains(card),"No room on the right did not flip left")
let earlier = CGRect(x:310,y:0,width:300,height:400)
(card, side) = ScreenDrawing.calloutFrame(size,marks:marks,avoid:[earlier],in:area)
precondition(side != nil && !card.intersects(earlier) && !card.intersects(marks) && area.contains(card),"Callout covered an earlier step")
(card, side) = ScreenDrawing.calloutFrame(size,marks:area.insetBy(dx:10,dy:10),avoid:[],in:area)
precondition(side == nil && area.contains(card),"No-room fallback left the screen")

func buttons(_ v: NSView) -> [NSButton] { v.subviews.compactMap { $0 as? NSButton } }
func labels(_ v: NSView) -> [String] { v.subviews.compactMap { ($0 as? NSTextField)?.stringValue } }
func click(_ b: NSButton) { b.sendAction(b.action,to:b.target) }
var events: [String] = []
func callout(_ text: String, _ step: Int, _ total: Int) -> DrawingCalloutView {
    let s = DrawingCalloutView.size(text,total:total)
    let v = DrawingCalloutView(frame:CGRect(x:0,y:0,width:s.width+24,height:s.height+24),card:CGRect(x:12,y:12,width:s.width,height:s.height),side:.minX,tip:40,text:text,step:step,total:total)
    v.onNext = { events.append("next") }; v.onBack = { events.append("back") }; v.onClose = { events.append("close") }
    return v
}
let first = callout("Complete the square: add 9 to both sides.",1,3)
precondition(labels(first) == ["Step 1 of 3"],"Progress missing")
precondition(buttons(first).first { $0.title == "Back" }?.isEnabled == false && buttons(first).contains { $0.title == "Next" })
click(buttons(first).first { $0.title == "Next" }!); click(buttons(first).first { $0.toolTip == "Close guide" }!)
let last = callout("So x² + 6x = (x + 3)² − 9.",3,3)
click(buttons(last).first { $0.title == "Back" }!); click(buttons(last).first { $0.title == "Done" }!)
precondition(events == ["next","close","back","next"],"Controls did not reach the guide: \(events)")
let single = callout("Click Share.",1,1)
precondition(labels(single).isEmpty && buttons(single).map(\.title) == ["Done"],"A one-step guide shows step controls")
let liveSize = DrawingCalloutView.size("Click Insert.",total:1)
let liveStep = DrawingCalloutView(frame:CGRect(x:0,y:0,width:liveSize.width+24,height:liveSize.height+24),card:CGRect(x:12,y:12,width:liveSize.width,height:liveSize.height),
                                  side:.minX,tip:40,text:"Click Insert.",step:1,total:1,more:true)
precondition(buttons(liveStep).map(\.title) == ["Next"],"A live guide's step ends in Done instead of asking for the next")
let long = callout(String(repeating:"A readable instruction needs enough words to wrap. ",count:20),2,4)
let scroll = long.subviews.compactMap { $0 as? NSScrollView }.first!, body = scroll.documentView as! NSTextView
body.layoutManager!.ensureLayout(for:body.textContainer!)
precondition(DrawingCalloutView.size(body.string,total:4).height < 400 && body.frame.height > scroll.contentSize.height,"Long step text is not scrollable")
let bubble = DrawingCalloutView.bubble(CGRect(x:12,y:12,width:200,height:100),side:.minX,tip:60)
precondition(bubble.boundingBoxOfPath.minX < 12-DrawingCalloutView.notch+1 && bubble.contains(CGPoint(x:8,y:60)),"The notch does not point at the marks")
let plain = DrawingCalloutView.bubble(CGRect(x:12,y:12,width:200,height:100),side:nil,tip:60).boundingBoxOfPath
precondition([plain.minX-12,plain.minY-12,plain.maxX-212,plain.maxY-112].allSatisfy { abs($0) < 0.01 },"A card with no room beside its marks grew a notch")

let pickView = DrawingView(frame:CGRect(x:0,y:0,width:1000,height:800))
pickView.render([DrawingShape(kind:"circle",rect:[100,100,80,20]),DrawingShape(kind:"arrow",points:[[400,110],[200,110]],color:"blue"),
                 DrawingShape(kind:"label",at:[500,500],text:"x"),DrawingShape(kind:"text",text:"board only")],animate:false,previous:nil,step:2)
let ringFrame = ScreenDrawing.ring(CGRect(x:100,y:100,width:80,height:20),circle:true)
precondition(pickView.mark(at:CGPoint(x:ringFrame.midX,y:ringFrame.minY))?.shape == 0,"A ring's stroke takes no click")
precondition(pickView.mark(at:CGPoint(x:140,y:110)) == nil,"A ring took the click meant for its target")
precondition(pickView.mark(at:CGPoint(x:300,y:110)).map { $0.shape == 1 && $0.step == 2 } == true,"An arrow takes no click")
let arrowLayer = pickView.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first { $0.strokeColor == NSColor.systemBlue.cgColor }!
precondition(arrowLayer.path!.boundingBoxOfPath.height >= 10,"The arrow has no head")
precondition(!pickView.hits.contains { $0.shape == 3 },"Text drew outside its board")
pickView.highlight((2,1)); precondition(pickView.layer!.sublayers!.filter { $0.name == "pick" }.count == 1,"The selected mark has no highlight")
pickView.highlight(nil); precondition(!pickView.layer!.sublayers!.contains { $0.name == "pick" })

let laptop = ScreenDrawing.textSize(nil,display:CGRect(x:0,y:0,width:1512,height:982)), monitor = ScreenDrawing.textSize(nil,display:CGRect(x:0,y:0,width:1920,height:1080))
precondition(laptop >= 26 && laptop <= 32 && monitor >= 29 && monitor <= 34 && ScreenDrawing.textSize("l",display:.zero) > ScreenDrawing.textSize("s",display:.zero),"Text is not readable: \(laptop) \(monitor)")
if let main = NSScreen.screens.first {
    let d = CGDisplayBounds(main.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as! CGDirectDisplayID)
    let near = CGRect(x:d.minX+80,y:d.minY+200,width:200,height:60)
    let worked = [DrawingStep(id:nil,say:"Split it.",target:nil,shapes:[DrawingShape(kind:"text",text:"12x⁵ = 3x² · 4x³")],wait:nil,hit:nil,timeout:nil),
                  DrawingStep(id:nil,say:"Check.",target:nil,shapes:[DrawingShape(kind:"circle",rect:[near.minX,near.minY,near.width,near.height]),
                              DrawingShape(kind:"text",text:"3 · 4 = 12",size:"s")],wait:nil,hit:nil,timeout:nil)]
    let b = ScreenDrawing.board(worked,near:near)!
    precondition(b.lines.map { [$0.step,$0.shape] } == [[0,0],[1,1]] && b.lines[1].rect.minY > b.lines[0].rect.maxY,"Lines are not stacked in order")
    precondition(b.lines.allSatisfy { b.frame.contains($0.rect) } && !b.frame.intersects(near) && b.lines[0].rect.height >= 22,"The board covered its marks or text is small")
    var pinned = worked; pinned[0] = DrawingStep(id:nil,say:"Here.",target:nil,shapes:[DrawingShape(kind:"text",at:[d.minX+300,d.minY+300],text:"x")],wait:nil,hit:nil,timeout:nil)
    precondition(ScreenDrawing.board(pinned,near:near)!.frame.origin == CGPoint(x:d.minX+300,y:d.minY+300),"The board ignored its at")
    let boardView = DrawingView(frame:CGRect(origin:.zero,size:d.size)); boardView.origin = d.origin
    boardView.renderBoard(b.frame,b.lines,current:1,animate:false)
    precondition(boardView.hits.count == 2 && boardView.layer!.sublayers!.compactMap { $0 as? CATextLayer }.first!.opacity == 0.7,"Board lines are not selectable, or the earlier line is not quieter")
}

let screenA = CGRect(x:0,y:0,width:1512,height:944), screenB = CGRect(x:1512,y:0,width:1920,height:1050), box = CGRect(x:14,y:800,width:340,height:120)
precondition(ScreenDrawing.clearSpot(box,avoiding:[CGRect(x:600,y:300,width:100,height:100)],in:[screenA,screenB]) == box.origin,"A clear box moved")
let covering = CGRect(x:0,y:780,width:400,height:100), spot = ScreenDrawing.clearSpot(box,avoiding:[covering],in:[screenA,screenB])!
let moved = CGRect(origin:spot,size:box.size)
precondition(!moved.intersects(covering) && screenA.insetBy(dx:8,dy:8).contains(moved) && hypot(spot.x-box.minX,spot.y-box.minY) < 200,"The box did not take the nearest clear spot: \(spot)")
let close = CGRect(x:box.maxX+20,y:800,width:100,height:100), roomy = ScreenDrawing.clearSpot(box,avoiding:[close],in:[screenA,screenB])!
precondition(roomy != box.origin && !CGRect(origin:roomy,size:box.size).intersects(close.insetBy(dx:-31,dy:-31)),"The box sat within 32 points of a mark: \(roomy)")
precondition(ScreenDrawing.clearSpot(box,avoiding:[screenA],in:[screenA,screenB]).map { screenB.contains(CGRect(origin:$0,size:box.size)) } == true,"A covered display did not send the box to the other one")
precondition(ScreenDrawing.clearSpot(box,avoiding:[screenA,screenB],in:[screenA,screenB]) == nil,"With no room the box must stay")
precondition(ScreenDrawing.clearSpot(box,avoiding:[screenA,screenB.insetBy(dx:0,dy:100)],in:[screenA,screenB]).map { covered in screenB.contains(CGRect(origin:covered,size:box.size)) } == true,"With no clear room the box must cover the least drawing")
print("Guide geometry: rings outside targets, arrows and labels beside them, callouts beside their marks, Back/Next/Done, selectable marks, text board, box placement")
'''


@unittest.skipUnless(sys.platform == 'darwin','macOS guide geometry check')
class GuideGeometryTests(unittest.TestCase):
    def test_marks_and_callouts_stay_clear_of_targets(self):
        from tests import run_swift
        source = (ROOT/'Atticus.swift').read_text()
        drawing = source[source.index('// Screen drawings use Quartz'):source.index('// The box can take typing')]
        self.assertIn('Guide geometry',run_swift(self,GEOMETRY.replace('__DRAWING__',drawing),timeout=20))

    def test_box_stays_clear_and_put_through_a_guide(self):
        from tests import run_swift
        source = (ROOT/'Atticus.swift').read_text()
        spot = source[source.index('    static func clearSpot('):source.index('\n    }\n',source.index('    static func clearSpot('))+7]
        avoid = source[source.index('    var boxHome: NSPoint?'):source.index('    func glide(')]
        follow = source[source.index('    func followPointerScreen()'):source.index('    func startFollowingPointerScreen()')]
        harness = 'import Cocoa\nenum ScreenDrawing {\n' + spot + '}\n' + r'''
struct Panel { var isVisible = true, frame = NSRect.zero }
final class Drawing { var active = false, session = false, pending = false, occupied: [CGRect] = []; var holds: Bool { active || pending || session } }
var pointerScreen: NSRect?
func pointerFollow(_ f: NSRect) -> NSRect? { pointerScreen }
final class App {
    var panel = Panel(), dragging = false, hovering = false, drawing = Drawing(), glides = 0
    func glide(_ f: NSRect) { glides += 1; panel.frame = f }
    func frame(_ f: NSRect) { panel.frame = f }
    func hide(after s: Double) {}
''' + avoid + follow + r'''}
let app = App(), vf = NSScreen.screens[0].visibleFrame, top = NSScreen.screens[0].frame.maxY
func drain() { RunLoop.main.run(until:Date().addingTimeInterval(0.05)) }
func marks(_ r: NSRect) -> [CGRect] { [CGRect(x:r.minX,y:top-r.maxY,width:r.width,height:r.height)] }   // drawing.occupied is top-left
app.panel.frame = NSRect(x:vf.minX+14,y:vf.maxY-130,width:340,height:120)
let home = app.panel.frame
app.drawing.active = true; app.drawing.session = true; app.drawing.occupied = marks(home); app.avoidDrawing()
let away = app.panel.frame
precondition(app.glides == 1 && away != home && app.boxHome == home.origin,"The box did not leave the guide's marks")
app.drawing.active = false; app.drawing.occupied = []; app.avoidDrawing(); drain()
precondition(app.panel.frame == away && app.boxHome == home.origin,"The box went home between guide steps")
pointerScreen = NSRect(x:9000,y:0,width:340,height:120); app.followPointerScreen()
precondition(app.panel.frame == away && app.boxHome == home.origin,"The pointer pulled the box off its guide spot")
app.drawing.active = true; app.drawing.occupied = marks(home); app.avoidDrawing()
precondition(app.glides == 1 && app.panel.frame == away,"The box moved for a next step that does not cover it")
app.drawing.occupied = marks(away); app.avoidDrawing()
precondition(app.glides == 2 && app.panel.frame != away && app.boxHome == home.origin,"The box stayed under the next step, or forgot its home")
app.drawing.active = false; app.drawing.session = false; app.avoidDrawing(); app.drawing.pending = true; drain()
precondition(app.glides == 2 && app.boxHome == home.origin,"A stale restore raced the guide's next step")
app.drawing.pending = false; app.avoidDrawing(); drain()
precondition(app.glides == 3 && app.panel.frame == home && app.boxHome == nil,"The box did not go home once the guide ended")
app.followPointerScreen(); precondition(app.panel.frame == pointerScreen!,"The box stopped following the pointer after the guide")
pointerScreen = nil; app.panel.frame = home
app.drawing.active = true; app.drawing.occupied = marks(home); app.avoidDrawing(); app.boxHome = nil   // the user dragged it
let placed = app.panel.frame; app.drawing.active = false; app.avoidDrawing(); drain()
precondition(app.panel.frame == placed && app.glides == 4,"A drawing moved a box the user placed")
print("Guide box placement")
'''
        self.assertIn('Guide box placement',run_swift(self,harness,timeout=20))

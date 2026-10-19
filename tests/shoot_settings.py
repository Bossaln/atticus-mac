"""Design screenshots of Settings, setup's provider sheet and the box's question cards, VM only (opt-in, not discovered: run this module by name).

run.sh ~/Projects/atticus tests.shoot_settings  → PNGs printed as base64 lines ("PNG <name> <data>"); the runner copies nothing back.
"""
import base64
import json
import unittest
from tests.shoot_agents_design import CARDS, SETUP, ROOT
from tests.test_agents_native import run_fixture

PREFS = {'hotkeyLabel': '⌃⌥Space', 'login': True, 'corner': 'top-left', 'linger': 'normal', 'soundStart': 'Pop', 'soundDone': 'Glass', 'soundStop': 'Tink',
         'volume': .16, 'client': 'claude', 'model': 'haiku', 'routing': 'balanced', 'instant': True, 'microphone': 'automatic', 'quietAudio': False, 'quietLevel': .18,
         'agentModel': 'sonnet', 'agentUserTools': True, 'fixSetup': False, 'longAsks': 'ask', 'selection': True, 'ahead': True, 'aheadDelay': .7,
         'live': True, 'screen': 'auto', 'openOn': 'here', 'workIn': 'back', 'miniScreen': True, 'speak': False, 'autoCopy': False, 'hideWhenSharing': True,
         'menuIcon': True, 'autoUpdate': True, 'learn': True, 'safe': True, 'pointer': False, 'meeting': False, 'learnMe': True, 'stats': True, 'tips': True,
         'askMe': True, 'draw': True, 'dictateMode': 'verbatim', 'dictateHotkeyLabel': '', 'input': 'voice', 'talkMode': 'hold', 'speechModel': 'speech', 'improve': False, 'draftInsert': 'ask'}
STATE = {'today': {'asks': 3, 'usd': .004, 'secs': 3}, 'week': {'asks': 21, 'usd': .03, 'secs': 3.4}, 'all': {'asks': 140, 'usd': .2, 'secs': 3.8},
         'rules': ['When I say focus mode, close Slack and open Notes'], 'skills': [], 'me': {'facts': []}, 'plan': {'ok': True, 'text': 'Signed in. Claude Max.'}}
PERMS = {'mic': True, 'speech': True, 'ax': True, 'screen': True, 'auto': True, 'chrome': False, 'calendar': True}

# Each scene: JavaScript run on the Settings page, then one shot of the whole window.
SCENES = [
    ('settings-general', "load({});st.tab('general');up()"),
    ('settings-general-mid', "document.querySelector('main').scrollTop=420"),
    ('settings-general-dictate-set', "load({dictateHotkeyLabel:'⌃⌥D',dictateMode:'cleanup'});st.tab('general');document.querySelector('main').scrollTop=180"),
    ('settings-general-dictate-recording', "$('dictatechange').click();st.rec('⌃⌥')"),
    ('settings-general-end', "document.querySelector('main').scrollTop=1e5"),
    ('settings-intelligence', "st.tab('brain');up()"),
    ('settings-intelligence-mid', "document.querySelector('main').scrollTop=420"),
    ('settings-intelligence-end', "document.querySelector('main').scrollTop=1e5"),
    ('settings-intelligence-cheapest', "load({routing:'cheapest'});st.tab('brain');up()"),
    ('settings-intelligence-local-offer', "load({});st.tab('brain');up();st.local([{name:'Ollama',base:'http://localhost:11434',models:['qwen3']}])"),
    ('settings-intelligence-server', "load({apiBase:'http://localhost:11434',apiModel:'qwen3'});st.tab('brain');up();st.models({base:'http://localhost:11434',key:'',list:['qwen3','llama3.2']})"),
    ('settings-intelligence-pi', "load({client:'pi'});st.tab('brain');up()"),
    ('settings-intelligence-devin', "load({client:'devin'});st.tab('brain');up()"),
    ('settings-screen', "load({});st.tab('screen');up()"),
    ('settings-sound', "st.tab('sound');up()"),
    ('settings-memory', "st.tab('memory');up()"),
    ('settings-account', "st.tab('account');up()"),
    ('settings-account-end', "document.querySelector('main').scrollTop=1e5"),
    ('settings-lab', "st.tab('lab');up()"),
    ('settings-about', "st.tab('about');up()"),
]
SETUP_PAGES = ['try', 'mac', 'learn', 'text', 'dictate', 'point', 'work', 'meeting']   # setup's feature pages, in order

# By window ID: a stray system prompt in the VM cannot cover the shot.
SNAP = r'''func snap(_ name:String,_ w:NSWindow){w.sharingType = .readOnly;let p=Process();p.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture");p.arguments=["-x","-o","-l\(w.windowNumber)",out+"/"+name+".png"];try! p.run();p.waitUntilExit();print("shot \(name)")}
'''
SHOTS = SETUP[:SETUP.index('let (ow,ov)=page(')] + SNAP + r'''
let tall=min(1500,screen.visibleFrame.height-120)
let (sw,sv)=page("settings.html",NSSize(width:780,height:tall),"st")   // as SettingsWindow.open, taller to show whole sections
let scenes=try! JSONSerialization.jsonObject(with:Data(#"SCENES"#.utf8)) as! [[String]]
let pages=try! JSONSerialization.jsonObject(with:Data(#"OBPAGES"#.utf8)) as! [String]
let setup=#"const PREFS=PREFS_JSON,STATE=STATE_JSON,up=()=>document.querySelector('main').scrollTop=0,load=p=>{st.load({prefs:{...PREFS,...p},state:STATE});st.perms(PERMS_JSON)};"#
// Each pass switches the whole app's appearance with the pages already loaded, as System Settings does: no reload.
let looks:[(String,NSAppearance.Name)]=[("light",.aqua),("dark",.darkAqua)]
func settingsScene(_ i:Int,_ look:Int){
 if i==0{nsapp.appearance=NSAppearance(named:looks[look].1);sw.orderFrontRegardless()}
 guard i<scenes.count else{sw.orderOut(nil);onboardingScene(look);return}
 sv.evaluateJavaScript(scenes[i][1]){_,e in if let e{print("scene failed \(scenes[i][0]): \(e)");exit(1)}
  after(0.9){snap(scenes[i][0]+"-"+looks[look].0,sw);settingsScene(i+1,look)}}}
// Setup's Change provider sheet with the custom server fields open, then each feature page.
let (ow,ov)=page("onboarding.html",NSSize(width:640,height:640),"ob");ow.orderOut(nil)
func onboardingScene(_ look:Int){
 let name=looks[look].0;ow.orderFrontRegardless()
 ov.evaluateJavaScript("ob.prefs({draw:true,meeting:false,routing:'balanced',longAsks:'ask',dictateMode:'verbatim',dictateHotkeyLabel:''});ob.plan({ok:true,client:'claude',text:'Signed in. Claude Max.'});ob.set({mic:true,speech:true,ax:true,screen:false,auto:true});document.querySelector('[data-go=\"perms\"]').click()"){_,_ in
  after(1.4){snap("setup-perms-"+name,ow)
   ov.evaluateJavaScript("document.getElementById('client-alt').click();document.querySelector('.opt[data-p=\"server\"]').click();ob.models(['qwen3','llama3.2'])"){_,_ in
    after(0.9){snap("setup-provider-"+name,ow)
     ov.evaluateJavaScript("document.getElementById('prov-cancel').click()"){_,_ in after(0.6){featurePage(0,look)}}}}}}}
func featurePage(_ i:Int,_ look:Int){
 guard i<pages.count else{
  guard look+1<looks.count else{print("settings shots ok");exit(0)}
  ow.orderOut(nil);settingsScene(0,look+1);return}
 ov.evaluateJavaScript("document.querySelector('[data-go=\"\(pages[i])\"]').click()"){_,e in if let e{print("page failed \(pages[i]): \(e)");exit(1)}
  after(2.6){snap("setup-"+pages[i]+"-"+looks[look].0,ow);featurePage(i+1,look)}}}
func ready(_ tries:Int){sv.evaluateJavaScript("typeof st"){v,_ in   // a busy VM can take a while to load the page
 guard v as? String == "object" else{if tries>60{print("settings page never loaded");exit(1)};after(0.5){ready(tries+1)};return}
 sv.evaluateJavaScript(setup+"load({});"){_,e in if let e{print("load failed: \(e)");exit(1)};settingsScene(0,0)}}}
after(1.0){ready(0)}
nsapp.run()'''

# The box's question cards side by side: a command approval, the calendar change, Long asks, and a plain offer.
EVENT = 'Dentist → Mon Oct 19, 4:00 PM – 5:00 PM · from Mon Oct 19, 3:00 PM – 4:00 PM · Home · this occurrence only'   # as atticus.calendar_tool words it
ASK = "ui.reset();ui.listen(true);ui.words(WORDS);ui.think();"
BOX = CARDS[:CARDS.index('let row=#"ROW"#')] + SNAP + r'''func fitted(_ name:String,_ done:@escaping()->Void){web.evaluateJavaScript("document.getElementById('card').getBoundingClientRect().height"){value,_ in
 let h=CGFloat((value as? Double) ?? 300);var f=box.frame;f.origin.y=f.maxY-h;f.size.height=h;box.setFrame(f,display:true);after(0.5){snap(name,box);done()}}}
let scenes=try! JSONSerialization.jsonObject(with:Data(#"BOXSCENES"#.utf8)) as! [[String]]
func play(_ i:Int){
 guard i<scenes.count else{print("box shots ok");exit(0)}
 web.evaluateJavaScript(scenes[i][1]){_,error in guard error == nil else{print("scene failed: \(scenes[i][0]): \(error!)");exit(1)};after(1.3){fitted(scenes[i][0]){play(i+1)}}}}
bridge.ready={after(1.0){play(0)}}
nsapp.run()'''
BOX_SCENES = [
    ('box-command', ASK.replace('WORDS', json.dumps('Delete the old notes on my desktop')) + "ui.ask(['Delete this file?','rm ~/Desktop/old-notes.txt','','',''])"),
    ('box-calendar', ASK.replace('WORDS', json.dumps('Move my dentist appointment to 4')) + f"ui.ask(['Move this event?',{json.dumps(EVENT)},'','',''])"),
    ('box-move', ASK.replace('WORDS', json.dumps('Research the best standing desks under $600')) + "ui.line('Searching the web: standing desks under 600');ui.moveReady();ui.moveOffer();"),
    ('box-move-saved', "document.querySelector('.move-option [data-v=never]').click();"),
    ('box-improve', "ui.reset();ui.listen(true);ui.words('Open Notes');ui.think();ui.msg('Opened Notes.');ui.improve();"),
]


class SettingsShots(unittest.TestCase):
    def shots(self, name, body, marker):
        out = ROOT / 'test-artifacts' / 'design' / 'settings'; out.mkdir(parents=True, exist_ok=True)
        run_fixture(self, body.replace('OUTDIR', str(out)), marker)
        for png in sorted(out.glob('*.png')): print('PNG', png.name, base64.b64encode(png.read_bytes()).decode(), flush=True)

    def page_shots(self, scenes, pages):
        self.shots('settings', SHOTS.replace('SCENES', json.dumps(scenes)).replace('OBPAGES', json.dumps(pages)).replace('PREFS_JSON', json.dumps(PREFS))
                   .replace('STATE_JSON', json.dumps(STATE)).replace('PERMS_JSON', json.dumps(PERMS)), 'settings shots ok')

    def test_settings_and_setup(self):
        self.page_shots(SCENES, [])

    def test_setup_feature_pages(self):   # its own run: two appearances of every page would pass the fixture's time limit
        self.page_shots([], SETUP_PAGES)

    def test_box_cards(self):
        self.shots('box', BOX.replace('BOXSCENES', json.dumps(BOX_SCENES)), 'box shots ok')


if __name__ == '__main__':
    unittest.main()

// Fork: die Oberfläche auf Deutsch. Übersetzt sichtbare Texte (Textknoten, title, placeholder, aria-label, alt) mit
// window.ATTICUS_DE aus ui/i18n-de.js (erzeugt von deutsch/i18n.py) und merkt sich die Originale, damit
// atticusLang('en') sie zurückholt. Antworten und die eigenen Worte (.a, .q) bleiben, wie sie sind.
(() => {
  const D = window.ATTICUS_DE || {}, exact = new Map(Object.entries(D.exact || {}));
  const patterns = (D.patterns || []).map(([re, to]) => [new RegExp(re), to]);
  const ATTRS = ['title', 'placeholder', 'aria-label', 'alt'], KEEP = '.q, .a:not(.cancel):not(.stopped), pre, code, textarea, [contenteditable]';
  const orig = new WeakMap(), mine = new WeakMap();   // node -> English text, node -> text this script wrote
  let lang = window.ATTICUS_LANG || 'en';
  const tr = s => {
    const t = s.trim().replace(/\s+/g, ' ');
    if (!t) return s;
    let r = exact.get(t);
    if (r === undefined) for (const [re, to] of patterns) if (re.test(t)) { r = t.replace(re, to); break; }
    return r === undefined ? s : s.match(/^\s*/)[0] + r + s.match(/\s*$/)[0];
  };
  const kept = n => { const p = n.nodeType === 1 ? n : n.parentElement; return !p || /^(SCRIPT|STYLE|TITLE)$/.test(p.nodeName) || !!p.closest(KEEP); };
  const text = n => {
    if (mine.get(n) === n.data || kept(n)) return;   // its own write, or a page script's new English text below
    orig.set(n, n.data);
    const want = lang === 'de' ? tr(n.data) : n.data;
    mine.set(n, want);
    if (want !== n.data) n.data = want;
  };
  const attr = (e, a) => {
    const v = e.getAttribute(a), m = mine.get(e) || {}, o = orig.get(e) || {};
    if (v === null || m[a] === v || kept(e)) return;
    o[a] = v; orig.set(e, o);
    m[a] = lang === 'de' ? tr(v) : v; mine.set(e, m);
    if (m[a] !== v) e.setAttribute(a, m[a]);
  };
  const fix = root => {
    if (root.nodeType === 3) return text(root);
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let n = root.nodeType === 1 ? root : w.nextNode(); n; n = w.nextNode()) {
      if (n.nodeType === 3) text(n); else for (const a of ATTRS) if (n.hasAttribute(a)) attr(n, a);
    }
  };
  new MutationObserver(records => {
    for (const r of records) {
      if (r.type === 'characterData') text(r.target);
      else if (r.type === 'attributes') attr(r.target, r.attributeName);
      else r.addedNodes.forEach(fix);
    }
  }).observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  // Sprache wechseln: jeden übersetzten Text aus seinem Original neu setzen.
  window.atticusLang = l => {
    lang = l; document.documentElement.lang = l;
    const w = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let n = w.currentNode; n; n = w.nextNode()) {
      if (n.nodeType === 3) {
        if (!orig.has(n) || mine.get(n) !== n.data) { text(n); continue; }
        const want = l === 'de' ? tr(orig.get(n)) : orig.get(n); mine.set(n, want); if (want !== n.data) n.data = want;
      } else for (const a of ATTRS) {
        const o = orig.get(n), m = mine.get(n);
        if (!n.hasAttribute(a)) continue;
        if (!o || !(a in o) || m[a] !== n.getAttribute(a)) { attr(n, a); continue; }
        m[a] = l === 'de' ? tr(o[a]) : o[a]; if (m[a] !== n.getAttribute(a)) n.setAttribute(a, m[a]);
      }
    }
  };
  // Der englische Text eines Elements, für Seitencode, der seinen eigenen Text wieder vergleicht.
  window.atticusOrig = e => {
    if (!e) return '';
    let s = ''; const w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) s += orig.has(n) && mine.get(n) === n.data ? orig.get(n) : n.data;
    return s;
  };
  document.documentElement.lang = lang;
  if (document.readyState !== 'loading') fix(document.documentElement);
  else document.addEventListener('DOMContentLoaded', () => fix(document.documentElement));
})();

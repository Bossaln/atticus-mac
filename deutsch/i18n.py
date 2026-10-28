#!/usr/bin/env python3
"""Erzeugt ui/i18n-de.js aus deutsch/i18n/*.json ({englisch: deutsch}, Rohtexte aus dem Quellcode).

Rohtexte können JS-Templates (${…}), Swift-Interpolationen (\\(…)), HTML-Tags und Escapes enthalten: Texte ohne
Platzhalter werden exakte Einträge, Texte mit Platzhaltern Regex-Muster; Tags teilen in die Textknoten, die im DOM landen.
deutsch/i18n/fixes.json gewinnt immer. Aufruf: python3 deutsch/i18n.py
"""
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOLE = re.compile(r'\$\{((?:[^{}]|\{[^{}]*\})*)\}|\\\((.*?)\)(?=[^)]*$|[^)])')   # ${expr} oder \(expr)
TAG = re.compile(r'<[^>]+>')


def unescape(s):
    s = re.sub(r'\\u\{([0-9a-fA-F]+)\}|\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1] or m[2], 16)), s)
    s = re.sub(r"\\(['\"`\\])", r'\1', s).replace('\\n', ' ')
    return html.unescape(s)


def norm(s):
    return ' '.join(s.split())


def holes(s):
    return [m[0] for m in HOLE.finditer(s)]


def entries(en, de):
    """(englisch, deutsch) Rohtexte -> [('exact', en, de) | ('pattern', regex, ersatz)]"""
    if '${' not in en and '\\(' not in en: en, de = unescape(en), unescape(de)
    en_parts, de_parts = TAG.split(en), TAG.split(de)
    if len(en_parts) != len(de_parts): en_parts, de_parts = [TAG.sub(' ', en)], [TAG.sub(' ', de)]
    out = []
    for e, d in zip(en_parts, de_parts):
        e, d = norm(e), norm(d)
        if not re.search(r'[A-Za-z]{2}', e) or e == d or not d: continue
        hs = holes(e)
        if not hs:
            out.append(('exact', e, d)); continue
        literal = HOLE.sub('', e)
        if len(re.findall(r'[A-Za-z]', literal)) < 5 or sorted(holes(d)) != sorted(hs) or len(set(hs)) != len(hs): continue
        rx, last = '^', 0
        for m in HOLE.finditer(e):
            rx += re.escape(unescape(e[last:m.start()])) + '(.+?)'; last = m.end()
        rx += re.escape(unescape(e[last:])) + '$'
        to, last = '', 0
        for m in HOLE.finditer(d):
            to += unescape(d[last:m.start()]).replace('$', '$$') + '$' + str(hs.index(m[0]) + 1); last = m.end()
        to += unescape(d[last:]).replace('$', '$$')
        out.append(('pattern', rx.replace('\\ ', ' '), to))
    return out


def main():
    exact, patterns = {}, {}
    files = sorted(p for p in (ROOT / 'deutsch' / 'i18n').glob('*.json') if p.name != 'fixes.json') + [ROOT / 'deutsch' / 'i18n' / 'fixes.json']
    for f in files:
        if not f.exists(): continue
        for en, de in json.loads(f.read_text()).items():
            for kind, a, b in entries(en, de):
                (exact if kind == 'exact' else patterns)[a] = b
    for k in [k for k in patterns if re.fullmatch(r'\^\(\.\+\?\)\$', k)]: del patterns[k]
    data = {'exact': exact, 'patterns': sorted(patterns.items(), key=lambda p: -len(p[0]))}   # die genauesten Muster zuerst
    js = json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True).replace('</', '<\\/')
    (ROOT / 'ui' / 'i18n-de.js').write_text('// Erzeugt von deutsch/i18n.py aus deutsch/i18n/*.json, nicht von Hand ändern.\nwindow.ATTICUS_DE = ' + js + ';\n')
    print(f'{len(exact)} Texte, {len(patterns)} Muster')


if __name__ == '__main__':
    main()

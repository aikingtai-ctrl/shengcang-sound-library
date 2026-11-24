# -*- coding: utf-8 -*-
"""Apply the sound-finding UI & mirror audio fallback to every upstream refresh (Rollup + Rolldown compatible)."""
from __future__ import annotations

import html as html_mod
import json
import re
import subprocess
import sys
from pathlib import Path


CATEGORIES = [
    ("环境与天气", "环境氛围", "自然 · 城市 · 室内"),
    ("人物动作", "人物拟音", "脚步 · 呼吸 · 衣物"),
    ("物件操作", "物件拟音", "开关门 · 纸张 · 工具"),
    ("动物与生物", "动物生物", "鸟鸣 · 兽类 · 昆虫"),
    ("交通与机器", "交通机械", "汽车 · 火车 · 机械"),
    ("打斗与破坏", "战斗破坏", "拳脚 · 武器 · 爆炸"),
    ("转场与运动", "转场运动", "划过 · 掠过 · 急停"),
    ("冲击与强调", "冲击强调", "重击 · 金属 · 点缀"),
    ("情绪与悬疑", "情绪张力", "低鸣 · 蓄力 · 惊吓"),
    ("科幻与魔法", "科幻魔法", "能量 · 法术 · 传送"),
    ("界面与提示", "界面提示", "点击 · 通知 · 警报"),
    ("音乐与配乐", "音乐", "古风 · 舒缓 · 史诗"),
]
ORIGIN = "https://shengcang-sound-library.jeaess66.chatgpt.site"
BLANK_GIF = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
ARROW_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" class="lucide lucide-arrow-up-right" aria-hidden="true">'
    '<path d="M7 7h10v10"></path><path d="M7 17 17 7"></path></svg>'
)


def sub_once(source: str, pattern: str, repl, name: str, flags: int = 0) -> str:
    updated, count = re.subn(pattern, repl, source, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{name}: expected 1 match for {pattern!r}, got {count}")
    return updated


def collect_missing_audio(site: Path) -> list[str]:
    manifest = next(
        (data for file in site.glob("catalogue-*.json")
         if isinstance((data := json.loads(file.read_text(encoding="utf-8"))), dict)
         and isinstance(data.get("parts"), list)),
        None,
    )
    if manifest is None:
        raise RuntimeError("catalogue manifest missing")
    missing: set[str] = set()
    for part in manifest["parts"]:
        part_path = site / part["url"].lstrip("./")
        if not part_path.is_file():
            continue
        data = json.loads(part_path.read_text(encoding="utf-8"))
        column = data["columns"].index("src")
        dictionary = data.get("dictionary") or []
        for row in data["rows"]:
            value = row[column]
            src = dictionary[value] if isinstance(value, int) else value
            if isinstance(src, str) and src.startswith(("/audio/", "./audio/")):
                relative = src.lstrip("./")
                if not (site / relative).is_file():
                    missing.add(relative.removeprefix("audio/"))
    return sorted(missing)


def _cards_js_literal() -> str:
    return ",".join(
        "{name:`%s`,english:`SOUND`,category:`%s`,categories:[`%s`],image:`cat-%02d`,theme:`mint`,note:`%s`}"
        % (name, category, category, idx, note)
        for idx, (name, category, note) in enumerate(CATEGORIES)
    )


def _upgrade_shared_bundle_fixes(source: str) -> str:
    cards_items = _cards_js_literal()
    if "image:`nature`,theme:`mint`" in source:
        source = sub_once(
            source,
            r"([A-Za-z_$][\w$]*)=\[\{name:`环境与天气`,english:`SOUND`.*?\}\](?=[,;])",
            lambda m: f"{m.group(1)}=[{cards_items}]",
            "upgrade 12 compact category cards unique keys",
            flags=re.S,
        )
    if "className:`collection-art`" in source and BLANK_GIF not in source:
        source = sub_once(
            source,
            r'className:`collection-art`,src:`(?:\.)?/images/\$\{[A-Za-z_$][\w$]*\.image\}\.png`,alt:``,width:1280,height:1280,fetchPriority:[A-Za-z_$][\w$]*\.theme===`featured`\?`high`:`auto`',
            lambda _: f'className:`collection-art`,src:`{BLANK_GIF}`,alt:``,width:1280,height:1280,fetchPriority:`auto`',
            "neutralize hidden collection-art png fetch",
        )
    if ".toLocaleString(),` `" in source:
        source = sub_once(
            source,
            r"([A-Za-z_$][\w$]*)\.toLocaleString\(\),` `,([A-Za-z_$][\w$]*)\.category===`音乐`\?`段配乐`:`条声音`",
            lambda m: f'{m.group(1)}.toLocaleString(`en-US`),` `,{m.group(2)}.category===`音乐`?`段配乐`:`条声音`',
            "pin en-US locale for SSR hydration parity",
        )
    return source


def _audio_helper_js(missing_audio: list[str]) -> str:
    missing_set = "var jtMissingAudio=new Set(" + json.dumps(
        missing_audio, ensure_ascii=False, separators=(",", ":")
    ) + ");\n"
    return (
        missing_set
        + f"function jtAudioSrc(e){{if(typeof e!==`string`)return e;"
        + f"if(e.startsWith(`/api/audio/`))return`{ORIGIN}`+e;"
        + f"let t=e.match(/(?:^|\\/)audio\\/([^?#]+)/);"
        + f"if(!t)return e;"
        + f"if(jtMissingAudio.has(t[1]))return`{ORIGIN}/audio/`+t[1];"
        + f"let b=typeof window!==`undefined`&&window.__JT_BASE__||`/`;"
        + f"return b+`audio/`+t[1]}}\n"
    )


def patch_bundle(source: str, missing_audio: list[str]) -> str:
    audio_helper = _audio_helper_js(missing_audio)
    if "function jtAudioSrc(" in source:
        source = sub_once(
            source,
            r"var jtMissingAudio=new Set\(\[[^\n]*\]\);\nfunction jtAudioSrc\(e\)\{[^\n]*\}\n",
            lambda _: audio_helper,
            "update jtMissingAudio + canonical jtAudioSrc",
        )
        return _upgrade_shared_bundle_fixes(source)

    source = sub_once(
        source,
        r"^((?:import[^;]+;)+)",
        lambda m: m.group(1) + audio_helper,
        "inject jtAudioSrc after imports",
    )

    cards_items = _cards_js_literal()
    source = sub_once(
        source,
        r"([A-Za-z_$][\w$]*)=\[\{name:`环境氛围`,english:`AMBIENCE`.*?\}\](?=[,;])",
        lambda m: f"{m.group(1)}=[{cards_items}]",
        "12 compact category cards",
        flags=re.S,
    )

    # 1. Player audio element assignment
    source = sub_once(
        source,
        r"([:?])([A-Za-z_$][\w$]*)\.src=([A-Za-z_$][\w$]*)\.src,",
        lambda m: f"{m.group(1)}{m.group(2)}.src=jtAudioSrc({m.group(3)}.src),",
        "player audio src",
    )
    # 2. IMA_ADPCM WAV fetch fallback (present in Rolldown bundle)
    if "subtype===`IMA_ADPCM`" in source:
        source = sub_once(
            source,
            r"fetch\(([A-Za-z_$][\w$]*)\.src,\{cache:`no-store`\}\)",
            lambda m: f"fetch(jtAudioSrc({m.group(1)}.src),{{cache:`no-store`}})",
            "IMA_ADPCM fetch audio src",
        )
    # 3. Waveform preview component src prop
    source = sub_once(
        source,
        r"\{src:([A-Za-z_$][\w$]*)\.src,subtype:\1\.subtype",
        lambda m: f"{{src:jtAudioSrc({m.group(1)}.src),subtype:{m.group(1)}.subtype",
        "waveform audio src",
    )
    # 4. Download URL resolver
    source = sub_once(
        source,
        r"function ([A-Za-z_$][\w$]*)\(([A-Za-z_$][\w$]*)\)\{return ([A-Za-z_$][\w$]*)\[\2\.id\]\?\.url\?\?\(\2\.owned\|\|\2\.src\.startsWith\(`/api/`\)\?`\$\{\2\.src\}\?download=1`:\2\.src\)\}",
        lambda m: (
            f"function {m.group(1)}({m.group(2)}){{return jtAudioSrc({m.group(3)}[{m.group(2)}.id]?.url??"
            f"({m.group(2)}.owned||{m.group(2)}.src.startsWith(`/api/`)?`${{{m.group(2)}.src}}?download=1`:{m.group(2)}.src))}}"
        ),
        "download url resolver",
    )
    # 5. Catalogue extended sound detail fallback without hitting 404 /api/sounds/:id
    source = sub_once(
        source,
        r"if\(Object\.hasOwn\(([A-Za-z_$][\w$]*),`owned`\)\)\{([A-Za-z_$][\w$]*)\(\1\);return\}",
        lambda m: (
            f"if(Object.hasOwn({m.group(1)},`owned`)||{m.group(1)}.src.startsWith(`/api/audio/`))"
            f"{{{m.group(2)}({{...{m.group(1)},description:`此条为扩展素材；可试听并查看许可。完整来源信息请在原站核对。`,"
            f"classificationBasis:`按原名称与标签分类，未逐条听感审核。`}});return}}"
        ),
        "catalogue detail modal",
    )
    return _upgrade_shared_bundle_fixes(source)


def build_ssr_collection_grid(html: str) -> str:
    m_counts = re.search(r'\\"categoryCounts\\":(\{[^}]+\})', html)
    if m_counts:
        raw_json = m_counts.group(1).replace('\\"', '"')
        counts = json.loads(raw_json)
    else:
        m_plain = re.search(r'"categoryCounts":(\{[^}]+\})', html)
        counts = json.loads(m_plain.group(1)) if m_plain else {}

    buttons: list[str] = []
    for name, category, note in CATEGORIES:
        cnt = int(counts.get(category, 0))
        unit = "段配乐" if category == "音乐" else "条声音"
        esc_name = html_mod.escape(name, quote=True)
        esc_note = html_mod.escape(note, quote=True)
        buttons.append(
            f'<button class="collection-card mint" aria-label="浏览{esc_name}，{cnt}条声音" aria-pressed="false">'
            f'<img class="collection-art" src="{BLANK_GIF}" alt="" width="1280" height="1280" fetchPriority="auto"/>'
            f'<span class="collection-copy">'
            f'<span class="collection-english">SOUND</span>'
            f'<strong>{esc_name}</strong>'
            f'<span class="collection-note">{esc_note}</span>'
            f'<span class="collection-bottom">'
            f'<span>{cnt:,}<!-- --> <!-- -->{unit}</span>'
            f'{ARROW_SVG}'
            f'</span></span></button>'
        )
    return f'<div class="collection-grid" aria-label="探索声音分类">{"".join(buttons)}</div>'


def build_ssr_category_select(html: str) -> str:
    init_by_cat: dict[str, int] = {}
    init_total = 0
    m_sounds = re.search(r'\\"sounds\\":(\[\{.*?\}\])\}\]\\n"\)', html)
    if m_sounds:
        sounds = json.loads(m_sounds.group(1).replace('\\"', '"').replace('\\\\', '\\'))
        init_total = len(sounds)
        for item in sounds:
            cat = item.get("category")
            if isinstance(cat, str):
                init_by_cat[cat] = init_by_cat.get(cat, 0) + 1
    else:
        m_sel = re.search(r'<select aria-label="声音分类">(.*?)</select>', html, flags=re.S)
        if m_sel:
            for val, num in re.findall(r'<option value="([^"]+)"[^>]*>.*?<!-- -->(\d+)<!-- -->', m_sel.group(1)):
                if val == "全部声音":
                    init_total = int(num)
                else:
                    init_by_cat[val] = int(num)
    opts = [f'<option value="全部声音" selected="">全部声音（<!-- -->{init_total}<!-- -->）</option>']
    for name, category, _ in CATEGORIES:
        c = init_by_cat.get(category, 0)
        esc_cat = html_mod.escape(category, quote=True)
        esc_name = html_mod.escape(name, quote=True)
        opts.append(f'<option value="{esc_cat}">{esc_name}<!-- -->（<!-- -->{c}<!-- -->）</option>')
    return f'<select aria-label="声音分类">{"".join(opts)}</select>'


STYLE = """
<style id="sc-finder-v2">
html .app-shell .hero{display:flex;flex-direction:column;gap:12px}
html .app-shell .hero-content{order:0}
html .app-shell .search-form{order:1;min-height:64px;margin:12px 0 0;background:#fff;border:2px solid #334461;border-radius:14px;box-shadow:0 3px 16px #263a5912}
html .app-shell .search-form:focus-within{border-color:#1d466e;box-shadow:0 0 0 4px #28548020}
html .app-shell .search-form input{font-size:20px;line-height:1.5}
html .app-shell .search-form button{font-size:16px;min-height:46px}
html .app-shell .search-suggestions{order:2;margin:0;font-size:14px}
html .app-shell .search-suggestions button{font-size:15px}
html .app-shell .collection-grid{order:3;grid-template-columns:repeat(4,minmax(0,1fr));align-items:stretch;gap:9px;margin:13px 0 0;padding:0}
html .app-shell .collection-grid:before{content:"按声音类型浏览";grid-column:1/-1;color:#35435c;font-size:18px;font-weight:650}
html .app-shell .collection-card,html .app-shell .collection-card.featured{height:91px;min-width:0;color:#26364e!important;background:#f5f7fa!important;border:1px solid #dce3ec;border-radius:12px;box-shadow:none}
html .app-shell .collection-card:hover{transform:none;background:#eaf0f7!important;box-shadow:none}
html .app-shell .collection-card[aria-pressed=true]{border:2px solid #284c78;background:#eaf2fa!important}
html .app-shell .collection-card[aria-pressed=true]:after{display:none}
html .app-shell .collection-art{display:none!important}
html .app-shell .collection-copy,html .app-shell .featured .collection-copy{inset:12px 14px;gap:2px}
html .app-shell .collection-english{display:none}
html .app-shell .collection-copy>strong,html .app-shell .featured .collection-copy>strong{font-size:18px;letter-spacing:0}
html .app-shell .collection-note,html .app-shell .featured .collection-note{display:block;color:#607086;font-size:12px;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
html .app-shell .collection-bottom{margin-top:3px;font-size:12px}
html .app-shell .collection-bottom>svg{display:none}
html .app-shell .section-heading h2{font-size:24px}
html .app-shell .section-heading p{font-size:15px}
html .app-shell .result-count{font-size:15px}
html .app-shell .filter-toolbar select{font-size:16px;min-height:44px}
html .app-shell .sound-title{font-size:19px}
html .app-shell .sound-meta{font-size:14px}
html .app-shell .hero:has(.search-form input:not(:placeholder-shown)) .collection-grid{display:none}
html .app-shell .hero:has(.search-form input:not(:placeholder-shown)) .search-suggestions{display:none}
@media(max-width:900px){html .app-shell .collection-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:767px){
html .app-shell .search-form{min-height:58px;padding:5px 6px 5px 12px}
html .app-shell .search-form input{font-size:18px;min-width:0}
html .app-shell .search-form button{font-size:13px;min-height:44px;padding:8px 11px}
html .app-shell .collection-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}
html .app-shell .collection-card,html .app-shell .collection-card.featured{height:74px;order:0}
html .app-shell .collection-copy,html .app-shell .featured .collection-copy{inset:9px 10px}
html .app-shell .collection-copy>strong,html .app-shell .featured .collection-copy>strong{font-size:16px}
html .app-shell .collection-note,html .app-shell .featured .collection-note{font-size:11px}
html .app-shell .collection-bottom{margin-top:1px;font-size:11px;margin:0}
}
</style>
"""


def patch(site: Path) -> None:
    chunk_dir = site / "_next" / "static" / "chunks"
    matches = [
        p for p in chunk_dir.glob("library-*.js")
        if "collection-grid" in (txt := p.read_text(encoding="utf-8")) and "sound-library" in txt
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one library bundle, found {len(matches)}")
    bundle = matches[0]
    patched_js = patch_bundle(bundle.read_text(encoding="utf-8"), collect_missing_audio(site))
    bundle.write_bytes(patched_js.encode("utf-8"))
    chk = subprocess.run(["node", "--check", str(bundle)], capture_output=True, text=True)
    if chk.returncode != 0:
        raise RuntimeError(f"JS syntax check failed on {bundle.name}: {chk.stderr}")

    index = site / "index.html"
    html = index.read_text(encoding="utf-8")
    ssr_grid = build_ssr_collection_grid(html)
    html = sub_once(
        html,
        r'<div class="collection-grid" aria-label="探索声音分类">.*?</div>(?=</details>)',
        lambda _: ssr_grid,
        "sync SSR collection-grid for hydration parity",
        flags=re.S,
    )
    ssr_select = build_ssr_category_select(html)
    html = sub_once(
        html,
        r'<select aria-label="声音分类">.*?</select>',
        lambda _: ssr_select,
        "sync SSR category select for hydration parity",
        flags=re.S,
    )
    if 'id="sc-finder-v2"' in html:
        html = sub_once(html, r'<style id="sc-finder-v2">.*?</style>', lambda _: STYLE.strip(), "update sc-finder-v2 style", flags=re.S)
    else:
        if "</head>" not in html:
            raise RuntimeError("HTML </head> missing")
        html = html.replace("</head>", STYLE + "</head>", 1)
    index.write_bytes(html.encode("utf-8"))


if __name__ == "__main__":
    patch(Path(sys.argv[1]).resolve())

# -*- coding: utf-8 -*-
"""Apply the sound-finding UI & mirror audio fallback to every upstream refresh (Rollup + Rolldown compatible)."""
from __future__ import annotations

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


def patch_bundle(source: str, missing_audio: list[str]) -> str:
    missing_set = "var jtMissingAudio=new Set(" + json.dumps(
        missing_audio, ensure_ascii=False, separators=(",", ":")
    ) + ");\n"
    if "function jtAudioSrc(" in source:
        return sub_once(
            source,
            r"var jtMissingAudio=new Set\(\[[^\n]*\]\);\n",
            lambda _: missing_set,
            "update jtMissingAudio",
        )

    audio_helper = (
        missing_set
        + f"function jtAudioSrc(e){{if(typeof e!==`string`)return e;"
        + f"if(e.startsWith(`/api/audio/`))return`{ORIGIN}`+e;"
        + f"let t=e.match(/(?:^|\\/)audio\\/([^?#]+)/);"
        + f"return t&&jtMissingAudio.has(t[1])?`{ORIGIN}/audio/`+t[1]:e}}\n"
    )
    source = sub_once(
        source,
        r"^((?:import[^;]+;)+)",
        lambda m: m.group(1) + audio_helper,
        "inject jtAudioSrc after imports",
    )

    cards_items = ",".join(
        "{name:`%s`,english:`SOUND`,category:`%s`,categories:[`%s`],image:`nature`,theme:`mint`,note:`%s`}"
        % (name, category, category, note)
        for name, category, note in CATEGORIES
    )
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
    return source


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
    if 'id="sc-finder-v2"' in html:
        html = sub_once(html, r'<style id="sc-finder-v2">.*?</style>', lambda _: STYLE.strip(), "update sc-finder-v2 style", flags=re.S)
    else:
        if "</head>" not in html:
            raise RuntimeError("HTML </head> missing")
        html = html.replace("</head>", STYLE + "</head>", 1)
    index.write_bytes(html.encode("utf-8"))


if __name__ == "__main__":
    patch(Path(sys.argv[1]).resolve())

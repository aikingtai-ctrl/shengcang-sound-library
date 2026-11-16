# -*- coding: utf-8 -*-
"""Apply the sound-finding UI to every upstream mirror refresh."""
from __future__ import annotations

import json
import re
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


def replace_one(source: str, old: str, new: str, name: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{name}: expected one anchor, got {count}")
    return source.replace(old, new, 1)


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
        data = json.loads((site / part["url"].lstrip("./")).read_text(encoding="utf-8"))
        column = data["columns"].index("src")
        dictionary = data["dictionary"]
        for row in data["rows"]:
            value = row[column]
            src = dictionary[value] if isinstance(value, int) else value
            if src.startswith(("/audio/", "./audio/")):
                relative = src.lstrip("./")
                if not (site / relative).is_file():
                    missing.add(relative.removeprefix("audio/"))
    return sorted(missing)


def patch_bundle(source: str, missing_audio: list[str]) -> str:
    if "function jtScore(" in source:
        return source
    cards = "Oe=[" + ",".join(
        "{name:`%s`,english:`SOUND`,category:`%s`,categories:[`%s`],image:`nature`,theme:`mint`,note:`%s`}"
        % (name, category, category, note)
        for name, category, note in CATEGORIES
    ) + "]"
    source, count = re.subn(r"Oe=\[\{.*?\}\],ke=", lambda _: cards + ",ke=", source, count=1)
    if count != 1:
        raise RuntimeError("category cards anchor missing")
    funcs = "var jtMissingAudio=new Set(" + json.dumps(missing_audio, ensure_ascii=False, separators=(",", ":")) + ");\n" + r"""function jtAudioSrc(e){if(typeof e!==`string`)return e;if(e.startsWith(`/api/audio/`))return`https://shengcang-sound-library.jeaess66.chatgpt.site`+e;let t=e.match(/(?:^|\/)audio\/([^?#]+)/);return t&&jtMissingAudio.has(t[1])?`https://shengcang-sound-library.jeaess66.chatgpt.site/audio/`+t[1]:e}
function jtScore(e,t){let n=t.trim().toLowerCase().split(/[\s,，、＋+]+/).filter(Boolean),r=(e.title||``).toLowerCase(),i=(e.tags||[]).map(e=>e.toLowerCase()),a=(e.subCategory||``).toLowerCase(),o=(e.category||``).toLowerCase();return n.reduce((e,t)=>e+(r===t?100:r.startsWith(t)?60:r.includes(t)?40:0)+(i.includes(t)?24:i.some(e=>e.includes(t))?12:0)+(a.includes(t)?5:0)+(o.includes(t)?2:0),0)}
function ye(e,t){let n=`${e.title} ${e.category} ${e.subCategory??``} ${(e.tags??[]).join(` `)} ${(e.useCases??[]).join(` `)} ${(e.styleTags??[]).join(` `)} ${(e.materialTags??[]).join(` `)}`.toLowerCase();return t.trim().toLowerCase().split(/[\s,，、＋+]+/).filter(Boolean).every(e=>n.includes(e))}"""
    source, count = re.subn(r"function ye\(e,t\)\{.*?\}(?=function be\()", lambda _: funcs, source, count=1)
    if count != 1:
        raise RuntimeError("search function anchor missing")
    patches = [
        ("A===`new`?t.createdAt-e.createdAt:0",
         "A===`new`?t.createdAt-e.createdAt:f.trim()?jtScore(t,f)-jtScore(e,f)||e.title.localeCompare(t.title,`zh-CN`):0", "relevance"),
        ("onChange:e=>p(e.target.value),placeholder:v===`音乐`",
         "onChange:e=>{if(!f&&e.target.value.trim())$();p(e.target.value)},placeholder:v===`音乐`", "search reset"),
        ("value:`recommended`,children:`默认排序`",
         "value:`recommended`,children:f?`最相关`:`默认排序`", "sort label"),
        ("[Ie,Le]=(0,l.useState)(12)", "[Ie,Le]=(0,l.useState)(24)", "first page"),
        ("Le(12)},[f,v,w", "Le(24)},[f,v,w", "page reset"),
        ("Le(Ie+12)", "Le(Ie+24)", "load more"),
        ("n.src=e.src,Re(e)", "n.src=jtAudioSrc(e.src),Re(e)", "player audio"),
        ("we,{src:e.src,subtype:e.subtype", "we,{src:jtAudioSrc(e.src),subtype:e.subtype", "wave audio"),
        ("function _t(e){return gt[e.id]?.url??(e.owned||e.src.startsWith(`/api/`)?`${e.src}?download=1`:e.src)}",
         "function _t(e){return jtAudioSrc(gt[e.id]?.url??(e.owned||e.src.startsWith(`/api/`)?`${e.src}?download=1`:e.src))}", "download"),
        ("按场景与用途筛选，点击播放即可试听。",
         "按标题和标签精准查找，再按类型、用途与时长缩小范围。扩展音频从源站播放。", "help text"),
        ("if(Object.hasOwn(e,`owned`)){q(e);return}",
         "if(Object.hasOwn(e,`owned`)||e.src.startsWith(`/api/audio/`)){q({...e,description:`此条为扩展素材；可试听并查看许可。完整来源信息请在原站核对。`,classificationBasis:`按原名称与标签分类，未逐条听感审核。`});return}", "catalogue detail"),
    ]
    for old, new, name in patches:
        source = replace_one(source, old, new, name)
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
html .app-shell .collection-bottom{font-size:11px;margin:0}
}
</style>
"""


def patch(site: Path) -> None:
    chunk_dir = site / "_next" / "static" / "chunks"
    matches = [p for p in chunk_dir.glob("library-*.js") if "function ye(" in p.read_text(encoding="utf-8")]
    if len(matches) != 1:
        raise RuntimeError(f"expected one library bundle, found {len(matches)}")
    bundle = matches[0]
    bundle.write_bytes(patch_bundle(bundle.read_text(encoding="utf-8"), collect_missing_audio(site)).encode("utf-8"))
    index = site / "index.html"
    html = index.read_text(encoding="utf-8")
    if 'id="sc-finder-v2"' in html:
        html, count = re.subn(r'<style id="sc-finder-v2">.*?</style>', lambda _: STYLE.strip(), html, count=1, flags=re.S)
        if count != 1:
            raise RuntimeError("existing finder style missing")
    else:
        html = replace_one(html, "</head>", STYLE + "</head>", "HTML head")
    index.write_bytes(html.encode("utf-8"))


if __name__ == "__main__":
    patch(Path(sys.argv[1]).resolve())

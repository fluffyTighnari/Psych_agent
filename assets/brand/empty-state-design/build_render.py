import re
from pathlib import Path

base = Path(__file__).resolve().parent
src = (base / "empty-state-art.html").read_text(encoding="utf-8")
symbols = re.findall(r'<symbol id="art-[^"]+".*?</symbol>', src, flags=re.S)
if len(symbols) != 4:
    raise SystemExit(f"expected 4 symbols, got {len(symbols)}")

ids = ["art-page", "art-window", "art-boat", "art-ring"]
parts = []
for art_id in ids:
    parts.append(
        f'<div class="cell"><svg viewBox="0 0 240 240" role="img" aria-label="{art_id}">'
        f'<use href="#{art_id}" xlink:href="#{art_id}"></use></svg></div>'
    )

html = """<!DOCTYPE html>
<html lang="zh-CN" data-canvas-width="1012" data-canvas-height="1012" style="width:1012px;height:1012px;margin:0">
<head>
<meta charset="utf-8">
<title>空态图形 · 四案 · 独立图</title>
<style>
*{box-sizing:border-box}
.cell{width:506px;height:506px;background:#fffdf9;display:grid;place-items:center}
.cell svg{width:506px;height:506px;display:block}
</style>
</head>
<body style="width:1012px;height:1012px;margin:0;overflow:hidden">
<main data-canvas-root style="width:1012px;height:1012px;margin:0;display:grid;grid-template-columns:506px 506px;grid-template-rows:506px 506px;overflow:hidden">
__CELLS__
</main>
<svg width="0" height="0" style="position:absolute;overflow:hidden" aria-hidden="true">
__SYMBOLS__
</svg>
</body>
</html>
"""
html = html.replace("__CELLS__", "\n".join(parts)).replace("__SYMBOLS__", "\n".join(symbols))
(base / "empty-state-art-render.html").write_text(html, encoding="utf-8")
print("written", base / "empty-state-art-render.html", "symbols", len(symbols))


from pathlib import Path

p = Path(__file__).resolve().parents[1] / "src/persona_ai/web/static/index.html"
text = p.read_text(encoding="utf-8")
marker = '<div class="settings-overlay hidden" id="settings"'
start = text.find(marker)
if start < 0:
    raise SystemExit("settings block not found")
depth = 0
i = start
end = -1
while i < len(text):
    if text.startswith("<div", i):
        depth += 1
        i = text.find(">", i) + 1
        continue
    if text.startswith("</div>", i):
        depth -= 1
        i += 6
        if depth == 0:
            end = i
            break
        continue
    i += 1
if end < 0:
    raise SystemExit("settings block end not found")
block = text[start:end].strip() + "\n\n"
text = text[:start] + text[end:]
insert_after = '  </div>\n\n  <script src="/static/waveform'
idx = text.find(insert_after)
if idx < 0:
    raise SystemExit("insert point not found")
panel_close_end = idx + len("  </div>\n\n")
text = text[:panel_close_end] + block + text[panel_close_end:]
p.write_text(text, encoding="utf-8")
print("ok", len(block))

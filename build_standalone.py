import re, os

with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 内联 Chart.js
with open('chart.umd.min.js', 'r', encoding='utf-8') as f:
    chartjs = f.read()

old = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>'
new = f'<script>\n{chartjs}\n</script>'
if old in html:
    html = html.replace(old, new)
    print("✓ Chart.js inlined")
else:
    print("⚠ Chart.js CDN tag not found — may already be inlined")

# 移除 Google Fonts
html = re.sub(r'\s*<link rel="preconnect" href="https://fonts\.googleapis\.com"[^>]*>\s*', '\n', html)
html = re.sub(r'\s*<link rel="preconnect" href="https://fonts\.gstatic\.com"[^>]*>\s*', '\n', html)
html = re.sub(r'\s*<link href="https://fonts\.googleapis\.com/css2[^"]*"[^>]*>\s*', '\n', html)
print("✓ Google Fonts removed")

# 注入系统字体
font_css = """  <style>
    body, * {
      font-family: "PingFang SC", "Microsoft YaHei", "微软雅黑", "Noto Sans SC",
                   -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    }
    code, .metric-value, .pe-compare-val {
      font-family: "SF Mono", "Cascadia Code", Consolas, "Courier New", monospace !important;
    }
  </style>"""
html = html.replace('</head>', font_css + '\n</head>', 1)
print("✓ System fonts injected")

os.makedirs('dist', exist_ok=True)
with open('dist/index.html', 'w', encoding='utf-8') as f:
    f.write(html)

size = os.path.getsize('dist/index.html') / 1024
print(f"✓ dist/index.html written ({size:.0f} KB)")

# Excalidraw 容器内文本定位修复

当使用 cairosvg 将 Excalidraw JSON 渲染为 PNG 时，带有 `containerId` 的文本（绑定在形状内部的文字）会出现在错误位置，因为 Excalidraw 的 JSON 坐标是近似值，需要基于容器尺寸重新计算。

## 问题

Excalidraw 在 `.excalidraw` 文件中存储的文本元素 `x`/`y` 坐标是近似值（由浏览器布局引擎填充）。直接使用这些坐标渲染 SVG 会导致文字跑出形状框外。

## 修复方法

对于每个带有 `containerId` 的文本元素，找到其对应的容器形状，然后根据容器尺寸和文本内容重新计算居中位置：

```python
def calc_text_inside_container(text_el, container_el, font_size):
    """根据容器尺寸重新计算文本居中位置"""
    cx = container_el.get("x", 0)
    cy = container_el.get("y", 0)
    cw = container_el.get("width", 100)
    ch = container_el.get("height", 100)
    text = text_el.get("text", "")
    lines = text.replace("\\n", "\n").split("\n")
    line_height = font_size + 4
    text_height = len(lines) * line_height
    max_line = max(len(l) for l in lines) if lines else 1
    text_width = max_line * font_size * 0.55  # 中文字符近似宽度
    tx = cx + (cw - text_width) / 2
    ty = cy + (ch - text_height) / 2 + font_size
    return tx, ty, lines, line_height
```

## 渲染流程

1. 创建元素索引，建立 `containerId` → 容器映射
2. 先渲染所有非文本元素（矩形、椭圆、菱形、箭头、独立文本）
3. 对有 `containerId` 的文本元素，调用 `calc_text_inside_container` 重新计算坐标
4. 将 SVG 传递给 cairosvg 渲染为 PNG

完整可运行的渲染脚本参考 `/tmp/render_v2.py`（会话 2026-06-25）。

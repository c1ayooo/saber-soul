# Excalidraw 绘图指南

> 供 saber-soul 工作流调用。需要画图时加载本文件。

## 颜色调色板

| 用途 | 填充色 | Hex |
|------|--------|-----|
| 主要/输入 | 浅蓝 | `#a5d8ff` |
| 成功/输出 | 浅绿 | `#b2f2bb` |
| 警告/外部 | 浅橙 | `#ffd8a8` |
| 处理/特殊 | 浅紫 | `#d0bfff` |
| 错误/关键 | 浅红 | `#ffc9c9` |
| 决策/备注 | 浅黄 | `#fff3bf` |
| 存储/数据 | 浅青 | `#c3fae8` |

## 元素格式

### 矩形（圆角）
```json
{ "type": "rectangle", "id": "r1", "x": 100, "y": 100, "width": 200, "height": 80,
  "roundness": { "type": 3 }, "backgroundColor": "#a5d8ff", "fillStyle": "solid",
  "boundElements": [{ "id": "t_r1", "type": "text" }] }
```

### 带文字的矩形
```json
{ "type": "text", "id": "t_r1", "x": 105, "y": 110, "width": 190, "height": 25,
  "text": "Hello", "fontSize": 20, "fontFamily": 1,
  "textAlign": "center", "verticalAlign": "middle",
  "containerId": "r1", "originalText": "Hello", "autoResize": true }
```

### 菱形
```json
{ "type": "diamond", "id": "d1", "x": 100, "y": 100, "width": 150, "height": 150,
  "backgroundColor": "#fff3bf", "fillStyle": "solid" }
```

### 箭头
```json
{ "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 150, "height": 0,
  "points": [[0,0],[150,0]], "endArrowhead": "arrow",
  "startBinding": { "elementId": "r1", "fixedPoint": [1, 0.5] },
  "endBinding": { "elementId": "r2", "fixedPoint": [0, 0.5] } }
```

## 字体
- 正文/标签：fontSize >= 16
- 标题：fontSize >= 20
- 禁止 fontSize < 14

## 已知陷阱

1. **containers 字典覆盖**：构建 `containers` 字典时，text 元素用 `containerId` 设置占位时会覆盖已存在的 shape 对象。必须加保护：`if el["containerId"] not in containers: containers[el["containerId"]] = None`

2. **SVG viewBox 引号**：`viewBox="0 0 {w} {h}"` 必须闭合双引号。缺失会导致 SVG 解析器把后续全部内容吞掉，画布空白。

3. **中文渲染**：本地用 cairosvg 渲染时，SVG 必须用 `font-family="Microsoft YaHei, sans-serif"`。`sans-serif` 单独不够。

## 工作流

```bash
# 1. 写 .excalidraw 文件
# 2. 上传获取分享链接
python3 ~/.hermes/skills/creative/excalidraw/scripts/upload.py path/to/diagram.excalidraw

# 3. 本地渲染 PNG（无浏览器时）
/home/c1ay/.hermes/hermes-agent/venv/bin/python3 ~/.hermes/skills/creative/excalidraw/scripts/render_excalidraw.py input.excalidraw output.png

# 4. 飞书插图（三步法）
#    a. 创建空图片块（block_type=27）→ 拿到 block_id
#    b. POST /drive/v1/medias/upload_all 上传PNG（parent_node=block_id）→ file_token
#    c. PATCH /docx/v1/documents/{doc_id}/blocks/{block_id} → {"replace_image": {"token": file_token}}
```

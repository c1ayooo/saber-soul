# Excalidraw 脚本路径备忘

excalidraw Hermes skill 已被删除（内容合并进 saber-soul），但脚本文件保留在原路径：

## 脚本位置

| 脚本 | 路径 |
|------|------|
| 渲染器（Excalidraw JSON → PNG） | `~/.hermes/skills/creative/excalidraw/scripts/render_excalidraw.py` |
| 上传器（获取分享链接） | `~/.hermes/skills/creative/excalidraw/scripts/upload.py` |

## 运行方式

```bash
# 渲染为 PNG
/home/c1ay/.hermes/hermes-agent/venv/bin/python3 \
  ~/.hermes/skills/creative/excalidraw/scripts/render_excalidraw.py \
  input.excalidraw output.png

# 上传获取分享 URL
python3 ~/.hermes/skills/creative/excalidraw/scripts/upload.py input.excalidraw
```

## 已知陷阱

1. `containers` 字典中 text 元素的 containerId 不能覆盖已有 shape 条目
2. SVG viewBox 引号必须闭合，否则画布空白
3. 中文需 font-family="Microsoft YaHei, sans-serif"

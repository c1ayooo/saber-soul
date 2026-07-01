# 图片插入已知陷阱

## 空图片块残留

三步法（create block → upload → PATCH）中任何一步失败（SSL 错误、超时、断网），文档中会留下空的图片块（block_type=27，image token 为空）。飞书客户端渲染为"一直加载不出来"的占位块。

**症状：**
```
0: type=27 [IMAGE token=abc123]    ← 正常
1: type=27 [IMAGE token=]          ← ❌ 空块
```

**清理：** 插入后扫描文档，删除 token 为空的所有 type=27 块（从后往前删避免索引偏移）。

**预防：** 不要在 index=0 处插入图片。插在 index=2~3（第一段正文之后），这样即使产生空块也在段落之间而非文档顶部。

## SSL 网络错误

上传图片到 drive/v1/medias/upload_all 时偶发 SSL EOF 错误。重试 1-3 次即可恢复。

## parent_node 必须用 block_id

`parent_node` 参数必须传图片块的 `block_id`，不是文档的 `doc_token`。传错时 upload 成功但 PATCH 返回 HTTP 400。

## 图片必须裁剪

Excalidraw 导出的 PNG 通常内容偏左/偏上，右侧/下方有大片空白。插入前必须裁剪到内容边界。

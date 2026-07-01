# AttachEnvData — 浏览器指纹关联画像

## 数据流

```
handleHTTP (handler.go)
  └─ handleLogin(bodyStr, srcIP) → 返回 envData map[string]interface{}
       └─ checkLogin() → saveEnvReport() → 写入 logs/env_report.jsonl + 返回 envJSON
  └─ if envData != nil && h.profiler != nil → h.profiler.AttachEnvData(srcIP, envData)
       └─ profile/engine.go → AttachEnvData(srcIP, envData)
            ├─ 查找或创建 Profile{SrcIP, FirstSeen, LastSeen}
            └─ p.EnvData = envData  // 直接覆盖（每次登录更新）
```

## 关键代码

### handler.go — handleHTTP 中调用

```go
if path == "/api/auth/login" && method == "POST" {
    var envData map[string]interface{}
    status, headers, respBody, envData = handleLogin(bodyStr, srcIP)
    if envData != nil && h.profiler != nil {
        h.profiler.AttachEnvData(srcIP, envData)
    }
}
```

### profile/engine.go — AttachEnvData 方法

```go
func (e *Engine) AttachEnvData(srcIP string, envData map[string]interface{}) {
    e.mu.Lock()
    defer e.mu.Unlock()
    p, ok := e.profiles[srcIP]
    if !ok {
        p = &Profile{SrcIP: srcIP, FirstSeen: time.Now().Unix(), LastSeen: time.Now().Unix()}
        e.profiles[srcIP] = p
    }
    p.EnvData = envData
}
```

### Profile 结构体增加 EnvData 字段

```go
type Profile struct {
    // ... 原有字段
    EnvData       map[string]interface{} `json:"env_data,omitempty"`
}
```

## 注意

- env_data 是 map[string]interface{}，序列化为 JSON 后直接展示在前端
- 字段命名已在采集阶段完成（m1/m2/u1/u2/c1/s1/z1 等），后端不做转换
- 同一 IP 多次登录会覆盖 env_data（保留最新一次）
- 重启后从 JSONL 重建时，env_report.jsonl 不参与重建（仅 _all.jsonl）
- 前端攻击者画像详情中自动展示 env_data 内容

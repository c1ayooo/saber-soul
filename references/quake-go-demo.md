# Quake API Go 调用示例

360 Quake API 调用示例（Go 语言），可直接编译运行。

## API 说明

| 项目 | 值 |
|------|-----|
| 接口 | `POST https://quake.360.net/api/v3/search/quake_service` |
| 认证 | Header: `X-QuakeToken: <token>` |
| 请求体 | `{"query": "查询语句", "start": 0, "size": 100}` |
| 来源 | `~/.hermes/tools/quake_query.py` |

## 代码

```go
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
)

const quakeAPI = "https://quake.360.net/api/v3/search/quake_service"

type QuakeService struct {
	IP     string `json:"ip"`
	Port   int    `json:"port"`
	Service struct {
		Name    string `json:"name"`
		Version string `json:"version"`
		HTTP    struct {
			Host   string `json:"host"`
			Title  string `json:"title"`
			Server string `json:"server"`
		} `json:"http"`
	} `json:"service"`
	Org      string `json:"org"`
	Hostname string `json:"hostname"`
	Location struct {
		Country  string `json:"country"`
		Province string `json:"province"`
		City     string `json:"city"`
	} `json:"location"`
}

type QuakeResponse struct {
	Code    int            `json:"code"`
	Message string         `json:"message"`
	Data    []QuakeService `json:"data"`
	Meta    struct {
		Total int `json:"total"`
	} `json:"meta"`
}

func queryQuake(token, query string, size int) (*QuakeResponse, error) {
	body, _ := json.Marshal(map[string]interface{}{
		"query": query,
		"start": 0,
		"size":  size,
	})
	req, _ := http.NewRequest("POST", quakeAPI, bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-QuakeToken", token)

	resp, err := (&http.Client{}).Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	b, _ := io.ReadAll(resp.Body)
	var r QuakeResponse
	json.Unmarshal(b, &r)
	return &r, nil
}

func main() {
	token := os.Getenv("QUAKE_API_KEY")
	if token == "" {
		fmt.Println("请设置 QUAKE_API_KEY 环境变量")
		os.Exit(1)
	}

	query := "domain:qq.com"
	if len(os.Args) > 1 {
		query = os.Args[1]
	}

	result, _ := queryQuake(token, query, 10)
	fmt.Printf("共 %d 条结果\n", result.Meta.Total)
	for _, svc := range result.Data {
		fmt.Printf("%s:%d | %s | %s\n", svc.IP, svc.Port,
			svc.Service.HTTP.Title, svc.Service.HTTP.Server)
	}
}
```

## 常用查询

| 查询类型 | query 示例 |
|---------|-----------|
| IP 反查 | `ip:1.2.3.4` |
| 域名 | `domain:example.com` |
| ICP | `icp: "京ICP备010000号"` |
| 组织 | `org: "公司名称"` |
| 端口 | `port:6379` |
| 服务 | `service:redis` |
| 多条组合 | `port:11434 AND body:"model" AND country:CN` |

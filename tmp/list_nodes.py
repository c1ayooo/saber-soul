#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/c1ay/.hermes/skills/saber-soul')
from lib.feishu_auth import api_request, get_tenant_access_token

get_tenant_access_token()
space_id = '7649299101007432657'

# List root-level nodes
nodes = api_request('GET', f'/wiki/v2/spaces/{space_id}/nodes', query={'page_size': 50})
for item in nodes.get('items', []):
    title = item.get('title', '?')
    node_token = item['node_token']
    print(f'{title}  →  {node_token}')

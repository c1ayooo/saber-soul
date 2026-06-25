#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/c1ay/.hermes/skills/saber-soul')
from lib.feishu_auth import api_request, get_tenant_access_token

get_tenant_access_token()
space_id = '7649299101007432657'

# List children of 4-安全开发 using parent_node_token query param
root = 'A5qKwYLl0ikz7Vk1vc9cvlRcnTb'
nodes = api_request('GET', f'/wiki/v2/spaces/{space_id}/nodes', query={'parent_node_token': root, 'page_size': 50})
for item in nodes.get('items', []):
    title = item.get('title', '?')
    nt = item['node_token']
    print(f'{title} -> {nt}')

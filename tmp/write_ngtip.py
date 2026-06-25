#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/c1ay/.hermes/skills/saber-soul')
from lib.feishu_doc import FeishuDoc

doc = FeishuDoc()
folder_token = 'O6UAwGzufiT9Nuke2SDcvQkun2g'  # 4.3-自动化检测

# Doc 1: 平台功能API
content1 = open('tmp/ngtip_platform_api.md', encoding='utf-8').read()
r1 = doc.write('NGTIP 平台功能 API 参考', content1, folder_token=folder_token)
print(f'Doc1: success={r1.success} url={r1.doc_url}')
if r1.error:
    print(f'  Error: {r1.error}')

# Doc 2: 情报查询API  
content2 = open('tmp/ngtip_query_api.md', encoding='utf-8').read()
r2 = doc.write('NGTIP 情报查询 API 参考', content2, folder_token=folder_token)
print(f'Doc2: success={r2.success} url={r2.doc_url}')
if r2.error:
    print(f'  Error: {r2.error}')

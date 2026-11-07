"""Read receipts only. Execution registration is an explicit Python embedding API."""
import argparse
import json
from pathlib import Path
from . import ExecutorRegistry


def main(argv=None):
    parser=argparse.ArgumentParser(description='本地执行回执：仅查看已保存请求；执行须由Python显式注册命名callable。')
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--request-id')
    args=parser.parse_args(argv); workspace=Path(args.workspace).expanduser().resolve()
    if not (workspace/'executors'/'requests.sqlite3').is_file(): parser.error('工作区尚无执行请求账本')
    try:
        registry=ExecutorRegistry(workspace,None)
        print(json.dumps(registry.get_request(args.request_id) if args.request_id else registry.list_requests(),ensure_ascii=False,indent=2))
        return 0
    except (ValueError,KeyError) as exc: parser.error(str(exc))


if __name__=='__main__': raise SystemExit(main())

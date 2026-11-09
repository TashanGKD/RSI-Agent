"""No timers. No arguments prints usage; explicit tick is a preview by default."""
import argparse
import json
from pathlib import Path
from . import Scheduler


def main(argv=None):
    parser=argparse.ArgumentParser(description='本地调度：单次预览／显式提交复查；不创建后台或计时器。')
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--db',help='默认 <workspace>/notebook/notebook.sqlite3，必须已存在')
    parser.add_argument('--source-file',help='默认 <workspace>/source.json，仅已保存资料')
    parser.add_argument('--apply',action='store_true',help='显式提交本次到期复查，可能调用秘书模型')
    parser.add_argument('--status',action='store_true',help='仅查看调度收据')
    args=parser.parse_args(argv); workspace=Path(args.workspace).expanduser().resolve()
    try:
        if args.status:
            if not (workspace/'scheduler'/'runs.sqlite3').is_file(): parser.error('工作区尚无调度账本')
            service=Scheduler(workspace,None,None); result=service.status()
        else:
            db=Path(args.db).expanduser().resolve() if args.db else workspace/'notebook'/'notebook.sqlite3'
            source=Path(args.source_file).expanduser().resolve() if args.source_file else workspace/'source.json'
            if not db.is_file() or not source.is_file(): parser.error('需要已存在的隔离记事本与来源文件；不自动选择正式库')
            from modules.notebook import NotebookService
            from modules.secretary import SecretaryService
            notebook=NotebookService(db,source,workspace)
            # Preview never instantiates a model runner or starts a worker.
            secretary=SecretaryService(notebook,workspace) if args.apply else None
            service=Scheduler(workspace,notebook,secretary); result=service.tick(apply=args.apply)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    except (ValueError,KeyError) as exc: parser.error(str(exc))


if __name__=='__main__': raise SystemExit(main())

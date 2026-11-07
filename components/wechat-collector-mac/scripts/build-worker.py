"""Build an isolated worker; never overwrite a current app or worker.

Example:
 python scripts/pack-oneshot-helper.py --accepted-helper /absolute/accepted/wxkey --output /absolute/new/oneshot-helper.pack
 python scripts/build-worker.py --helper-payload /absolute/new/oneshot-helper.pack --output-dir /absolute/new/worker-output
No arguments/help perform no build, copy, execution or filesystem mutation.
The output directory must not exist. Build files stay in a fresh private .runtime workspace.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper-payload',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args(argv)
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root/'src/MacWorker/foundation'))
    import helper_payload
    try:
        payload=args.helper_payload;output=args.output_dir
        if not payload.is_absolute() or not output.is_absolute():raise ValueError()
        if any(p.is_symlink() for p in (payload,*payload.parents,output,*output.parents)):raise ValueError()
        if output.exists() or not output.parent.is_dir():raise ValueError()
        fd=os.open(payload,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
        try:
            import stat
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not 0<before.st_size<=helper_payload.ENCODED_LIMIT:raise ValueError()
            raw=bytearray()
            while len(raw)<=helper_payload.ENCODED_LIMIT:
                block=os.read(fd,min(65536,helper_payload.ENCODED_LIMIT+1-len(raw)))
                if not block:break
                raw.extend(block)
            import connection
            if len(raw)!=before.st_size or connection._fpin(os.fstat(fd))!=connection._fpin(before) or connection._fpin(payload.lstat())!=connection._fpin(before):raise ValueError()
            helper_payload.decode(bytes(raw))
        finally:os.close(fd)
        # The validated bytes, not a mutable caller input path, enter the TOC.
        workspace=Path(tempfile.mkdtemp(prefix='worker-c8-build-',dir=root/'.runtime'));workspace.chmod(0o700)
        sealed=workspace/'oneshot-helper.pack';sealed.write_bytes(raw);sealed.chmod(0o600)
        output.mkdir(mode=0o700)
        arguments=[sys.executable,'-m','PyInstaller','--onefile','--name','mac-worker',
                   '--paths',str(root/'src/MacWorker/foundation')]
        for name in ('library','media','attachment_names','security','crypto','capture','playback','connection','connection_driver','helper_payload','archive_lock','archive_lock_driver','archive_read'):
            arguments+=['--hidden-import',name]
        # Keep the legacy helper for consumers which have not moved to --connect.
        for source,destination in ((root/'src/MacWorker/foundation/decode-voice.cjs','.'),
                (Path(os.environ['WECHAT_COLLECTOR_SILK_WASM_DIR']),'node_modules/silk-wasm'),
                (Path(os.environ['WECHAT_COLLECTOR_HELPER_BIN_DIR']),'vendor'),(sealed,'vendor')):
            arguments+=['--add-data',str(source)+':'+destination]
        arguments+=['--distpath',str(output),'--workpath',str(workspace/'work'),'--specpath',str(workspace),str(root/'src/MacWorker/mac_worker.py')]
        subprocess.run(arguments,check=True,cwd=workspace)
        return 0
    except Exception:
        print('isolated worker build rejected or failed',file=sys.stderr)
        return 64

if __name__=='__main__':raise SystemExit(main())

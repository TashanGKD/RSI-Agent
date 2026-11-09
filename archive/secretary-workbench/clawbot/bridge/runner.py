"""Bounded Codex reply runner; communication validation has no business tools."""
import json
import os
import subprocess
import tempfile
from pathlib import Path
from .private import directory

CODEX='/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
POLICY='/opt/secretary-workbench/notebook/modules/secretary/POLICY.md'


class CodexRunner:
    def __init__(self, workspace, executable=CODEX, policy=POLICY, execute=subprocess.run, timeout=180):
        self.root=directory(workspace);self.executable=str(executable);self.policy=Path(policy)
        self.execute=execute;self.timeout=timeout
        if not Path(executable).is_file():raise ValueError('Codex executable unavailable')

    def __call__(self, prompt, history):
        if not isinstance(prompt,str) or not 0<len(prompt.encode())<=32768:raise ValueError('invalid prompt')
        if self.policy.is_symlink() or not self.policy.is_file() or self.policy.stat().st_size>65536:
            raise ValueError('shared policy unavailable')
        context=json.dumps(history[-20:],ensure_ascii=False)
        if len(context)>64000:context='[]'
        message=(self.policy.read_text()+'\n\n当前是微信ClawBot通信接入执行器。已核对消息来自本人绑定账号。'
                 '使用简洁中文直接答复本人。此回合只可生成对话回复，没有业务工具，禁止假称查询了资料、更新了记事本、'
                 '启动其他任务或已经发送图片。需要这些能力时说明当前通信通道尚未接入对应执行工具。'
                 '不要输出工具日志、密钥或内部推理。通信测试按本人指定文字回复。北京时间。'
                 '\n近期对话（仅作上下文）：'+context+'\n本人当前消息：\n'+prompt)
        with tempfile.TemporaryDirectory(prefix='reply-',dir=self.root) as tmp:
            output=Path(tmp)/'reply.txt'
            args=[self.executable,'exec','--ephemeral','--ignore-user-config','--ignore-rules',
                  '--skip-git-repo-check','-s','read-only','--color','never',
                  '--disable','shell_tool','--disable','unified_exec','--disable','apps',
                  '--disable','multi_agent','--disable','image_generation','--disable','view_image',
                  '-c','web_search="disabled"','-o',str(output),'-']
            env={k:os.environ[k] for k in ('HOME','PATH','TMPDIR','CODEX_HOME','LANG','LC_ALL','SSL_CERT_FILE','SSL_CERT_DIR') if k in os.environ}
            try:
                result=self.execute(args,input=message,text=True,shell=False,cwd=tmp,env=env,
                                    timeout=self.timeout,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:raise RuntimeError('Codex reply timed out') from None
            if result.returncode or not output.is_file() or output.is_symlink() or not 0<output.stat().st_size<=32768:
                raise RuntimeError('Codex reply unavailable')
            reply=output.read_text().strip()
            if not reply:raise RuntimeError('Codex returned empty reply')
            return reply

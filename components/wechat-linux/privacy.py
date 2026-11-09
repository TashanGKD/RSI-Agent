"""Keep credential-bearing memos local rather than forwarding them to a model."""
import re
LABEL=re.compile(r'(?:密码|口令|验证码|助记词|私钥|password|passwd|api[_ -]?key|access[_ -]?token|secret|token)(?:\s*(?:[:：=]|是|就是|为)|\s+(?=[A-Za-z0-9]))',re.I)
CJK_SECRET=re.compile(r'密码(?!学)|口令(?!文件|接口|设计|协议)|验证码|助记词|私钥')
KEY=re.compile(r'-----BEGIN [^-]*PRIVATE KEY-----|\bsk-[a-zA-Z0-9_-]{20,}|Authorization\s*:\s*Bearer',re.I)

def model_text(text):
    if LABEL.search(text) or CJK_SECRET.search(text) or KEY.search(text):
        return '本人通过普通微信保存了一条包含账号或口令的私人备忘。此自动转交只包含本段脱敏说明，不包含凭据原文。原始备忘继续保存在本地受保护信源。请只确认已在本地保留，不复述、不上传凭据，也不要据此登录、付款或执行其他动作。'
    return text

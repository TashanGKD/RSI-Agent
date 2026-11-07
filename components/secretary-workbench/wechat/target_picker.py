"""Mouse-only visible-session picker. Never types a name or presses Enter."""
import base64,hashlib,io,json

def point(value,bounds):
    if not isinstance(value,list) or len(value)!=2 or any(type(x) is not int for x in value):raise ValueError('two integer coordinates required')
    l,t,r,b=bounds
    if not l<value[0]<r or not t<value[1]<b:raise ValueError('point must stay inside visible session names; search/editor/message controls are forbidden')
    return value

def check_sidebar(pixels,wanted):
    if not isinstance(wanted,str) or hashlib.sha256(pixels).hexdigest()!=wanted:raise ValueError('session list changed; inspect target_prepare again')

def open_visible(control,main,position):
    # No key(), paste(), or message-producing primitive is used in navigation.
    control.focus(main);control.wait(150);control.click(*position);control.wait(600)

def dispatch(tool,r):
    from linux_tool import ROOT,secret
    from sender import UI,inspect_target
    from image_client import Controls,locked
    from PIL import Image
    target=tool.resolve(r['peer']);ui=UI(ROOT)
    with locked(ROOT):
        c=Controls(ROOT)
        try:
            windows=c.windows()
            if len(windows)!=1 or windows[0]['title']!='Weixin':raise ValueError('visible-session picking requires only the main WeChat window, no dialog/viewer')
            main=windows[0];cfg=json.loads(secret(ROOT/'native-ui.json'))
            if main['width']<900 or main['height']<600 or cfg['header_box'][0]!=main['x']+314:raise ValueError('unsupported session-list layout')
            bindings=json.loads(secret(ROOT/'tool-targets.json')) if (ROOT/'tool-targets.json').exists() else {}
            configs=[cfg,*bindings.values()];screen=ui.screenshot()
            if not any(hashlib.sha256(screen.crop(tuple(x['header_box'])).tobytes()).hexdigest()==x['header_sha256'] for x in configs):raise ValueError('current main window must be visually verified/bound before picking')
            c.focus(main);c.wait(150);screen=ui.screenshot();bounds=[main['x']+134,main['y']+82,main['x']+314,main['y']+650]
            raw=screen.crop(tuple(bounds))
            if r['action']=='target_prepare':
                # Preserve names/timestamps only; conceal message previews that
                # can contain private self-memos. This is navigation evidence.
                masked=Image.new('RGB',raw.size,'white')
                # Current verified light-theme names are dark, previews gray.
                # Avoid fragile row-height assumptions; selected white names
                # can disappear, so this is a locator, never semantic identity.
                masked.putdata([(0,0,0) if max(px[:3])<70 else (255,255,255) for px in raw.convert('RGB').getdata()])
                b=io.BytesIO();masked.save(b,format='PNG')
                return {'state':'target_context_ready','peer':target['username'],'expectedTitle':target['displayName'],'viewport':bounds,'sidebar_sha256':hashlib.sha256(raw.tobytes()).hexdigest(),'session_names_png_base64':base64.b64encode(b.getvalue()).decode(),'previewFilter':'dark name pixels in current light theme; not semantic redaction','keyboardUsed':False,'instruction':'Inspect names and choose a visible row with open_target, then verify the full opened header. No automatic search/typing is available.'}
            p=point(r.get('point'),bounds);check_sidebar(raw.tobytes(),r.get('sidebar_sha256'));open_visible(c,main,p)
            result=inspect_target(r,target);result.update(keyboardUsed=False,messagesSent=0,openedByMouseOnly=True)
            return result
        finally:c.close()

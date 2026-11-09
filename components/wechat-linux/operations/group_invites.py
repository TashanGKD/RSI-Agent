"""Owned, exact member invitations in the existing SDK and executor."""
import hashlib,json,sqlite3,time
from .contract import digest
from .runtime import BeforeEffect
from . import groups,navigation

def invite_plan(account,requested,contacts,current,pending):
    plan=groups.member_plan(account,requested,contacts,current_members=current)
    plan['existingPending']=[{'peer':v,'sourceId':pending[v]} for v in requested if v not in current and v in pending]
    plan['eligible']=[v for v in plan['eligible'] if v not in pending]
    plan['deferred']=[v for v in plan['deferred'] if v['peer'] not in pending]
    return plan

def invitation_proof(peer,account,before,selected,actual,pending):
    if not peer.endswith('@chatroom') or account not in actual:raise ValueError('exact native group/self membership required')
    joined=sorted(set(selected)&set(actual))
    waiting=[{'peer':v,'sourceId':pending[v]} for v in selected if v not in actual and v in pending]
    if set(joined)|{v['peer'] for v in waiting}!=set(selected):raise ValueError('all selected invitation effects not proved')
    return {'state':'accepted','peer':peer,'groupPeer':peer,'actualMembers':sorted(set(actual)),
            'memberCount':len(set(actual)),'joinedMembers':joined,'pendingMembers':waiting,
            'allSelectedMembersPresent':not waiting,'newMembersSincePreparation':sorted(set(actual)-set(before)),
            'selfMembershipVerified':True,'ordinaryChatSendClicks':0,'automaticInvitationMessagesMayExist':True,
            'phoneReceiptConfirmed':False,'automaticReplay':False}

def system_pending_targets(text,names):
    start='已向';end='发送群聊邀请，为了减少打扰，需对方同意邀请后才会进入群聊'
    if not isinstance(text,str) or not text.startswith(start) or not text.endswith(end):return set()
    clause=text[len(start):-len(end)];paths={0:(1,frozenset())};size=len(clause)
    # Count complete tokenisations up to ambiguity, without recursive stacks or
    # exponential collections of alternative member sets.
    for offset in range(size+1):
        if offset not in paths:continue
        ways,seen=paths[offset]
        for name,uid in names.items():
            if not name or not clause.startswith(name,offset):continue
            stop=offset+len(name)
            if stop<size and clause[stop]!='、':continue
            next_offset=stop if stop==size else stop+1
            old=paths.get(next_offset)
            count=min(2,ways+(old[0] if old else 0))
            paths[next_offset]=(count,old[1] if old else seen|{uid})
    result=paths.get(size)
    return set(result[1]) if result and result[0]==1 else set()


def invite_picker_proof(window,identity,parent,host):
    return groups.picker_proof(window,identity,parent,host,expected_title='WeixinAdd Members')

def share_box(w):return (w['x']+345,w['y']+470,w['x']+740,w['y']+530)
def share_unselected(image,w):
    # Disabled/enabled caption colours are not selected history. The right
    # value area must remain empty; no history-control activation is in this
    # recipe, and the caller reviews the actual final picker as well.
    value=image.crop((w['x']+540,w['y']+478,w['x']+710,w['y']+522)).convert('RGB')
    return not any(min(pixel)<140 for pixel in value.getdata())

def sharing_unchanged(before,after,w):return share_unselected(before,w) and share_unselected(after,w)

def owned_cleanup_windows(value,nav,current):
    if current==value['beforeWindows']:return True
    own=(nav or {}).get('ownPopout')
    if not own or own in (nav or {}).get('beforeWindows',[]) or own not in value['beforeWindows']:return False
    return current==[w for w in value['beforeWindows'] if w['id']!=own['id']]

def contact_rows(d,requested):
    from linux_tool import native
    out={}
    with native('contact/contact.db') as (db,receipt):
        if receipt.get('consistency')!='committed':raise BeforeEffect('native contacts unproved')
        for uid in requested:
            rows=db.execute('SELECT username,nick_name,remark,alias,local_type,flag,delete_flag FROM contact WHERE username=?',(uid,)).fetchall()
            if len(rows)>1:raise BeforeEffect('native person ambiguous')
            if rows:out[uid]=dict(rows[0])
    return out

def names_for(d,contacts):
    out={}
    for uid,row in contacts.items():
        for name in (row.get('remark'),row.get('nick_name')):
            if not name:continue
            try:
                if d.name_peer(name)==uid:out[name]=uid
            except ValueError:pass
    return out

def pending_invites(d,j,contacts,current,since=0,names=None):
    from linux_tool import native,decode
    mapping=names or names_for(d,contacts);out={};table='Msg_'+hashlib.md5(j['peer'].encode()).hexdigest()
    with native('message/message_0.db') as (db,receipt):
        if receipt.get('consistency')!='committed':raise ValueError('native invitation snapshot unproved')
        if db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():
            for row in db.execute('SELECT server_id,message_content FROM '+table+' WHERE (local_type & 4294967295)=10000 AND create_time>=? ORDER BY create_time',(int(since),)):
                for uid in system_pending_targets(decode(row['message_content']) or '',mapping):
                    if uid in j['payload']['members'] and uid not in current:out[uid]=str(row['server_id']&0xffffffffffffffff)
    db=sqlite3.connect((d.root/'queue.sqlite').as_uri()+'?mode=ro',uri=True)
    try:
        for (raw,) in db.execute("SELECT result FROM jobs WHERE client=? AND state='succeeded' AND json_extract(body,'$.peer')=? AND json_extract(body,'$.action')='invite_members'",(j['client'],j['peer'])):
            result=json.loads(raw or '{}')
            for row in result.get('pendingMembers',[]):
                if row['peer'] in j['payload']['members'] and row['peer'] not in current:out.setdefault(row['peer'],row['sourceId'])
    finally:db.close()
    return out

def current_group(d,j):
    value=groups.native_group(d,j['peer'])
    if not value or not value['inGroup'] or d.policy.cfg['account'] not in value['members']:raise BeforeEffect('exact current group and self membership unproved')
    if not value['name'] or d.name_peer(value['name'])!=j['peer']:raise BeforeEffect('native group name not unique')
    return value

def preview(d,j,v,window):
    from .recipes import screen
    im=screen(d).crop((window['x'],window['y'],window['x']+window['width'],window['y']+window['height']))
    p=d.previews/(j['id']+'.png');tmp=p.with_suffix('.tmp');im.save(tmp,format='PNG');tmp.chmod(0o600);tmp.replace(p)
    return {'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'width':im.width,'height':im.height,'context':digest(v),
            'programRecipe':True,'memberInvitationRecipe':True,'summary':{'action':'invite_members','peer':j['peer'],
            'groupName':v['groupName'],'selectedMembers':v['plan']['eligible'],'alreadyMembers':v['plan']['alreadyMembers'],
            'existingPendingInvitations':v['plan']['existingPending'],'deferredMembers':v['plan']['deferred'],
            'sharesChatHistory':False,'createsNewGroup':False}}

GROUP_INFO_LABELS = {'groupname', 'groupqrcode', 'myaliasingroup', 'searchchathistory', 'remark'}
# Dashed square and plus of the observed official 100% scale control.
ADD_ICON_SHA256 = 'aecadecfc3358a08935dc41c564ee07d3f037c0b70f67a213174286eecf392b1'

def invite_add_observation(image, side, scratch):
    """Resolve the Add control from one frame of a verified group-info panel."""
    from .ocr import normalized, observe
    from .selectors import unique_line

    panel = image.crop(tuple(side)).convert('RGB')
    labels, _ = observe(panel, scratch, lang='eng')
    if len({normalized(row['text']) for row in labels} & GROUP_INFO_LABELS) < 2:
        raise ValueError('owned information panel unproved')

    if any(normalized(row['text']) == 'add' for row in labels):
        # Keep the original path and its rejection of multiple exact matches.
        x, y = unique_line(labels, 'Add')
    else:
        def contrast_add(threshold):
            contrast = panel.convert('L').point(lambda value: 0 if value <= threshold else 255)
            enhanced_labels, _ = observe(contrast.convert('RGB'), scratch, lang='eng')
            return unique_line(enhanced_labels, 'Add')

        x, y = contrast_add(210)
        corroborating_x, corroborating_y = contrast_add(220)
        if abs(x - corroborating_x) > 1 or y != corroborating_y:
            raise ValueError('contrast Add observations disagree')
        icon_box = (x - 19, y - 52, x + 19, y - 13)
        if not (0 <= icon_box[0] < icon_box[2] <= panel.width
                and 0 <= icon_box[1] < icon_box[3] <= panel.height):
            raise ValueError('Add icon outside member area')
        if hashlib.sha256(panel.crop(icon_box).tobytes()).hexdigest() != ADD_ICON_SHA256:
            raise ValueError('official Add icon shape unproved')

    point = [side[0] + x, side[1] + y - 34]
    if not side[0] < point[0] < side[2] or not side[1] < point[1] < side[3]:
        raise ValueError('Add icon outside member area')
    return point, hashlib.sha256(panel.tobytes()).hexdigest()

def stable_invite_add(d, c, chat, identity, side):
    from .recipes import screen
    from .windows import window_identity

    previous = None
    for _ in range(6):
        observation = invite_add_observation(screen(d), side, d.previews)
        if observation == previous:
            point, panel_sha = observation
            c.require_focus(chat)
            if window_identity(chat) != identity or hashlib.sha256(
                    screen(d).crop(tuple(side)).convert('RGB').tobytes()).hexdigest() != panel_sha:
                raise ValueError('group information panel changed before Add')
            return point
        previous = observation
        c.wait(120)
    raise ValueError('Add member control or group information panel moving')

def prepare(d,j):
    from .recipes import PreparationError
    try:return prepare_impl(d,j)
    except PreparationError:raise
    except (ValueError,OSError) as error:raise PreparationError('GROUP_INVITE_PREPARATION_FAILED',str(error)[:150]) from None

def prepare_impl(d,j):
    from .recipes import controls,rows,screen,main_window,activate,paste_field,PreparationError
    from .forwarding import single_local_result
    from .windows import window_identity
    from .ocr import normalized
    groups.require_unattempted(d,j);group=current_group(d,j);contacts=contact_rows(d,j['payload']['members'])
    pending=pending_invites(d,j,contacts,group['members']);plan=invite_plan(d.policy.cfg['account'],j['payload']['members'],contacts,group['members'],pending)
    navigation.begin(d,j);d._select(j);chat=main_window(d)
    v=groups.write(d,j,{'phase':'selected','operation':'invite_members','account':d.policy.cfg['account'],
        'groupPeer':j['peer'],'groupName':group['name'],'beforeMembers':group['members'],'plan':plan,
        'chat':chat,'chatIdentity':window_identity(chat),'beforeWindows':d.app_windows(),'sidebarOpened':False,
        'selections':[],'selectedNames':names_for(d,contacts)})
    if not plan['eligible']:
        v.update(phase='no-effect-preview',noEffect=True);groups.write(d,j,v);return preview(d,j,v,chat)
    side=[chat['x']+chat['width']-250,chat['y']+82,chat['x']+chat['width']-8,chat['y']+chat['height']-12]
    known=GROUP_INFO_LABELS
    if len({normalized(r['text']) for r in rows(d,side,lang='eng')}&known)>=2:raise PreparationError('GROUP_INFO_PROTECTED','Preexisting group information preserved.')
    v.update(sidebarBox=side,sidebarBaselineSHA256=hashlib.sha256(screen(d).crop(tuple(side)).tobytes()).hexdigest(),phase='sidebar-open-intent');groups.write(d,j,v)
    c=controls(d)
    try:
        activate(c,chat);c.click(chat['x']+chat['width']-20,chat['y']+55);c.wait(200)
        if len({normalized(r['text']) for r in rows(d,side,lang='eng')}&known)<2:raise ValueError('owned information panel unproved')
        v.update(sidebarOpened=True,phase='sidebar-open');groups.write(d,j,v)
        point=stable_invite_add(d,c,chat,v['chatIdentity'],side)
        before=d.app_windows();v.update(phase='picker-open-intent',addPoint=point);groups.write(d,j,v);c.click(*point);c.wait(200)
        added=[w for w in d.app_windows() if w['id'] not in {r['id'] for r in before}]
        if len(added)!=1:raise ValueError('one owned Add Members window required')
        picker=added[0];identity=window_identity(picker);root=navigation.load(d.root,j)['main'];parent=chat if identity.get('transientFor')==chat['id'] else root
        invite_picker_proof(picker,identity,parent,v['chatIdentity'])
        if not share_unselected(screen(d),picker):raise ValueError('preexisting chat-history share selection preserved')
        v.update(phase='selecting',picker=picker,pickerIdentity=identity,shareBox=list(share_box(picker)),shareHistoryOff=True,historyControlNeverActivated=True);groups.write(d,j,v)
        for uid in plan['eligible']:
            if d.app_windows()!=sorted(before+[picker],key=lambda w:w['id']):raise ValueError('picker windows changed')
            query=groups.person_query(contacts[uid],d.name_peer);activate(c,picker);paste_field(c,[picker['x']+160,picker['y']+35],query)
            labels=rows(d,[picker['x']+20,picker['y']+65,picker['x']+334,picker['y']+510],lang='eng',contrast=True)
            points=single_local_result(screen(d),groups.primary_person_column(picker,labels))
            if len(points)!=1:raise ValueError('one primary native member result required')
            c.click(*points[0]);c.wait(120);im=screen(d).crop((points[0][0]-10,points[0][1]-10,points[0][0]+11,points[0][1]+11)).convert('RGB')
            if sum(g>r+20 and g>b+10 for r,g,b in im.getdata())<15:raise ValueError('selected member not proved')
            v['selections'].append({'peer':uid,'querySHA256':hashlib.sha256(query.encode()).hexdigest(),'nativeUniqueQueryCopiedBack':True});groups.write(d,j,v)
        buttons=groups.picker_buttons(d,picker,commit_label='Add');selected=[picker['x']+345,picker['y']+60,picker['x']+740,picker['y']+470]
        if not share_unselected(screen(d),picker):raise ValueError('chat-history sharing value is not empty')
        v.update(phase='preview',addMembersPoint=buttons['Add'],cancelPoint=buttons['Cancel'],selectedBox=selected,selectedSHA256=hashlib.sha256(screen(d).crop(tuple(selected)).tobytes()).hexdigest());groups.write(d,j,v)
        return preview(d,j,v,picker)
    finally:c.close()

def execute(d,j):
    from .recipes import controls,screen,activate
    from .windows import window_identity
    groups.require_unattempted(d,j);v=groups.read(d,j)
    if not v or j['preview'].get('context')!=digest(v):raise BeforeEffect('invitation preview changed')
    if v.get('noEffect'):return verify(d,j)
    group=current_group(d,j);contacts=contact_rows(d,j['payload']['members']);pending=pending_invites(d,j,contacts,group['members']);fresh=invite_plan(v['account'],j['payload']['members'],contacts,group['members'],pending)
    if any(uid not in fresh['eligible'] for uid in v['plan']['eligible']):raise BeforeEffect('a frozen selected target changed before invitation')
    picker=v['picker']
    if d.app_windows()!=sorted(v['beforeWindows']+[picker],key=lambda w:w['id']) or window_identity(picker)!=v['pickerIdentity']:raise BeforeEffect('owned picker changed')
    if hashlib.sha256(screen(d).crop(tuple(v['selectedBox'])).tobytes()).hexdigest()!=v['selectedSHA256'] or not share_unselected(screen(d),picker):raise BeforeEffect('selected members/history sharing changed')
    c=controls(d)
    try:
        activate(c,picker);d._save_attempt(j,{'action':'invite_members','peer':j['peer'],'startedAt':time.time(),'invitationClickScheduled':True,'selectedMembers':v['plan']['eligible'],'payloadSHA256':digest(j['payload'])})
        v.update(phase='invite-click-intent');groups.write(d,j,v);c.click(*v['addMembersPoint'])
        for pause in (100,200,400,800,1200,1600):
            c.wait(pause);proof=verify(d,j)
            if proof.get('state')=='accepted':return proof
        return {'state':'unknown','reason':'original-invitation-effects-not-yet-complete','automaticReplay':False}
    except Exception as error:
        if (d.root/(j['id']+'-attempt.json')).exists():return {'state':'unknown','reason':'original-invitation-effect-needs-reconciliation','automaticReplay':False,'detail':str(error)[:150]}
        raise
    finally:c.close()

def verify(d,j):
    v=groups.read(d,j)
    if not v:return {'state':'unknown','reason':'no-original-invitation-journal','automaticReplay':False}
    group=current_group(d,j)
    if v.get('noEffect'):
        result=invitation_proof(j['peer'],v['account'],v['beforeMembers'],[],group['members'],{})
        return dict(result,invitationClicks=0,newInvitationPerformed=False,allRequestedMembersPresent=set(j['payload']['members'])<=set(group['members']),deferredMembers=v['plan']['deferred'],existingPendingInvitations=v['plan']['existingPending'])
    path=d.root/(j['id']+'-attempt.json')
    if not path.exists():return {'state':'unknown','reason':'no-original-invitation-attempt','automaticReplay':False}
    attempt=json.loads(path.read_text())
    if attempt.get('action')!='invite_members' or attempt.get('peer')!=j['peer'] or attempt.get('selectedMembers')!=v['plan']['eligible'] or attempt.get('payloadSHA256')!=digest(j['payload']) or not attempt.get('invitationClickScheduled'):
        return {'state':'unknown','reason':'invitation-attempt-mismatch','automaticReplay':False}
    pending=pending_invites(d,j,contact_rows(d,j['payload']['members']),group['members'],since=attempt['startedAt']-1,names=v['selectedNames'])
    try:proof=invitation_proof(j['peer'],v['account'],v['beforeMembers'],v['plan']['eligible'],group['members'],pending)
    except ValueError:return {'state':'unknown','reason':'no-complete-original-invitation-receipts','automaticReplay':False}
    return dict(proof,groupName=group['name'],invitationClicks=1,newInvitationPerformed=True,allRequestedMembersPresent=set(j['payload']['members'])<=set(group['members']),missingRequestedMembers=sorted(set(j['payload']['members'])-set(group['members'])),deferredMembers=v['plan']['deferred'],existingPendingInvitations=v['plan']['existingPending'])

def cleanup(d,j):
    from .recipes import controls,activate,rows,screen
    from .windows import window_identity
    from .ocr import normalized
    v=groups.read(d,j)
    if not v:return navigation.finish(d,j)
    c=controls(d)
    try:
        picker=v.get('picker')
        if picker and picker in d.app_windows():
            if (d.root/(j['id']+'-attempt.json')).exists() or window_identity(picker)!=v['pickerIdentity']:return False
            point=groups.picker_buttons(d,picker,commit_label='Add')['Cancel'];activate(c,picker);c.click(*point);c.wait(150)
            if picker in d.app_windows():return False
        chat=v['chat'];side=v.get('sidebarBox');opened=v.get('sidebarOpened');known={'groupname','groupqrcode','myaliasingroup','searchchathistory','remark'}
        if side and not opened and v.get('phase')=='sidebar-open-intent':
            if hashlib.sha256(screen(d).crop(tuple(side)).tobytes()).hexdigest()!=v['sidebarBaselineSHA256']:
                if len({normalized(r['text']) for r in rows(d,side,lang='eng')}&known)<2:return False
                opened=True
        if opened:
            if len({normalized(r['text']) for r in rows(d,side,lang='eng')}&known)<2:return False
            activate(c,chat);c.click(chat['x']+chat['width']-20,chat['y']+55);c.wait(150);v['sidebarOpened']=False;groups.write(d,j,v)
        if not owned_cleanup_windows(v,navigation.load(d.root,j),d.app_windows()) or not navigation.finish(d,j):return False
        v.update(phase='settled',settledAt=time.time());groups.write(d,j,v);return True
    except Exception:return False
    finally:c.close()

def finish(d,j):
    from .recipes import controls
    for delay in (0,120,250):
        if delay:
            c=controls(d)
            try:c.wait(delay)
            finally:c.close()
        if cleanup(d,j):return True
    return False

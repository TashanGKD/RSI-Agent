"""Existing executor group creation, exact native members and original-job recovery.

The job peer is the existing owner DM used as the authorised operation anchor.
It is never a fabricated new group peer. New group identity comes from native
before/after membership, while pending friendships remain explicitly deferred.
"""
import hashlib, json, os, re, stat, time
from pathlib import Path
from .contract import digest, peer
from .runtime import BeforeEffect


def member_plan(account, requested, contacts, current_members=()):
    if not isinstance(requested, list) or not requested or len(set(v for v in requested if isinstance(v,str))) != len(requested):
        raise ValueError('nonempty unique native member identities required')
    for value in requested:
        peer(value)
        if value == account or value.endswith('@chatroom'):
            raise ValueError('creator is implicit; other targets must be people')
    from .proof import friend
    out={'eligible':[], 'deferred':[], 'alreadyMembers':[]}
    for value in requested:
        if value in current_members:
            out['alreadyMembers'].append(value)
            continue
        row=contacts.get(value)
        if row and row.get('username') != value:
            raise ValueError('contact identity changed')
        if friend(row):
            out['eligible'].append(value)
        else:
            out['deferred'].append({'peer':value,'reason':'friendship-not-established' if row else 'contact-unresolved','requestSent':False})
    return out


def person_query(row, resolve):
    for value in (row.get('remark'),row.get('nick_name'),row.get('alias')):
        if not value:continue
        try:
            if resolve(value)==row['username']:return value
        except ValueError:continue
    raise ValueError('visible native person name is not globally unique')


def primary_person_column(picker, labels):
    from .ocr import normalized
    related=[v['point'][1] for v in labels if normalized(v['text'])=='relatedfriends']
    if len(related)>1:raise ValueError('related-friend result section is ambiguous')
    top=picker['y']+80;bottom=min(picker['y']+510,related[0]-16) if related else picker['y']+510
    if bottom-top<50:raise ValueError('primary native person result section is not proved')
    return [picker['x']+22,top,picker['x']+45,bottom]


def picker_buttons(d,picker,commit_label='Finish'):
    from .recipes import rows
    from .selectors import unique_line
    areas={commit_label:(415,532),'Cancel':(556,673)}
    return {label:unique_line(rows(d,[picker['x']+left,picker['y']+528,picker['x']+right,picker['y']+563],lang='eng',psm=6),label) for label,(left,right) in areas.items()}


def new_group_proof(before, candidates, account, selected):
    wanted=set(selected)|{account}
    found=[v for v in candidates if v.get('peer') not in before and isinstance(v.get('peer'),str) and v['peer'].endswith('@chatroom') and v.get('owner')==account and v.get('inGroup') is True and account in v.get('members',[]) and set(v.get('members',[]))<=wanted]
    if len(found)!=1:
        raise ValueError('one exact newly-created native group not proved')
    v=found[0]
    actual=set(v['members'])
    return {'groupPeer':v['peer'],'actualMembers':sorted(actual),'memberCount':len(actual),'nativeOwner':account,'selfMembershipVerified':True,'membershipSHA256':digest(sorted(actual)),'unconfirmedSelectedMembers':sorted(wanted-actual),'initialMembershipPartial':actual!=wanted}


def picker_proof(window, identity, main, host, expected_title='WeixinStart Group Chat'):
    if window.get('title')!=expected_title or (window.get('width'),window.get('height'))!=(752,586):
        raise ValueError('exact official group picker layout not proved')
    if identity.get('class')!=['wechat','wechat'] or any(identity.get(k)!=host.get(k) for k in ('class','pid','leader')) or identity.get('transientFor')!=main['id'] or '_NET_WM_WINDOW_TYPE_UTILITY' not in identity.get('types',[]):
        raise ValueError('group picker process/parent identity not proved')
    return True


def path(d,j):
    if not re.fullmatch('[a-f0-9]{32}',j.get('id','')):
        raise ValueError('original internal group job required')
    return d.root/(j['id']+'-group-operation.json')


def write(d,j,value):
    p=path(d,j);temporary=p.with_suffix('.tmp')
    if p.is_symlink() or temporary.exists() or temporary.is_symlink():
        raise ValueError('group journal collision')
    v=dict(value,jobId=j['id'],client=j['client'],peer=j['peer'],payloadSHA256=digest(j['payload']))
    data=json.dumps(v,ensure_ascii=False).encode()
    if len(data)>200000:
        raise ValueError('group operation journal too large')
    fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as out:
        out.write(data);out.flush();os.fsync(out.fileno())
    os.replace(temporary,p)
    return v


def read(d,j):
    p=path(d,j)
    if p.is_symlink():
        raise ValueError('group journal symlink')
    if not p.exists():
        return None
    s=p.stat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>200000:
        raise ValueError('private group journal required')
    v=json.loads(p.read_text())
    if any(v.get(k)!=expected for k,expected in [('jobId',j['id']),('client',j['client']),('peer',j['peer']),('payloadSHA256',digest(j['payload']))]):
        raise ValueError('group journal/request mismatch')
    return v


def require_unattempted(d,j):
    if (d.root/(j['id']+'-attempt.json')).exists():
        raise ValueError('original group effect already scheduled; reconcile without replay')


def effect_failure(value,error):
    return {'state':'unknown','reason':'original-group-effect-needs-reconciliation','detail':str(error)[:150],
            'groupCreated':bool(value.get('groupPeer')),'groupPeer':value.get('groupPeer'),'automaticReplay':False}


def directory(d,j):
    from linux_tool import native, ACCOUNT
    if ACCOUNT!=d.policy.cfg['account']:
        raise BeforeEffect('group operation account changed')
    with native('contact/contact.db') as (db,receipt):
        if receipt.get('consistency')!='committed' or receipt.get('integrity')!='ok':
            raise BeforeEffect('native group snapshot unproved')
        requested=j['payload']['members'];contacts={}
        for value in requested:
            rows=db.execute('SELECT username,nick_name,remark,alias,local_type,flag,delete_flag FROM contact WHERE username=?',(value,)).fetchall()
            if len(rows)>1:
                raise BeforeEffect('native person is ambiguous')
            if rows:contacts[value]=dict(rows[0])
        matches=db.execute('SELECT username FROM contact WHERE nick_name=? OR remark=?',(j['payload']['group_name'],j['payload']['group_name'])).fetchall()
        group_ids=[v[0] for v in db.execute('SELECT username FROM chat_room')]
    return {'account':ACCOUNT,'contacts':contacts,'existingNamePeers':[v[0] for v in matches],'beforeGroupIds':group_ids}


def native_group(d, value):
    from linux_tool import native
    with native('contact/contact.db') as (db,receipt):
        if receipt.get('consistency')!='committed' or receipt.get('integrity')!='ok':
            raise ValueError('native membership consistency gap')
        row=db.execute('SELECT c.nick_name,c.is_in_chat_room,g.owner FROM contact c JOIN chat_room g ON c.username=g.username WHERE c.username=?',(value,)).fetchone()
        if not row:return None
        members=[v[0] for v in db.execute('SELECT c.username FROM chat_room g JOIN chatroom_member m ON g.id=m.room_id JOIN contact c ON c.id=m.member_id WHERE g.username=?',(value,))]
        return {'peer':value,'name':row['nick_name'] or '', 'owner':row['owner'],'inGroup':row['is_in_chat_room']==1,'members':members}


def current_new_groups(d,before):
    from linux_tool import native
    with native('contact/contact.db') as (db,receipt):
        if receipt.get('consistency')!='committed':raise ValueError('native consistency gap')
        values=[v[0] for v in db.execute('SELECT username FROM chat_room') if v[0] not in before]
    return [v for v in (native_group(d,value) for value in values) if v]


def prepare(d,j):
    from .recipes import PreparationError
    try:return prepare_impl(d,j)
    except PreparationError:raise
    except (ValueError,OSError) as error:
        raise PreparationError('GROUP_PREPARATION_FAILED',str(error)[:150]) from None


def prepare_impl(d,j):
    from . import navigation
    from .recipes import main_window,controls,activate,rows,screen,PreparationError
    from .selectors import unique_line
    from .forwarding import single_local_result
    from .windows import window_identity
    require_unattempted(d,j)
    info=directory(d,j)
    if info['existingNamePeers']:
        raise PreparationError('GROUP_ALREADY_PRESENT','Existing exact-name group requires original identity review, not duplicate creation.')
    plan=member_plan(info['account'],j['payload']['members'],info['contacts'])
    if len(plan['eligible'])<2:
        raise PreparationError('GROUP_MEMBERS_NOT_READY','At least two currently verified friends required to create an actual group.')
    navigation.begin(d,j);main=main_window(d);before=d.app_windows()
    v=write(d,j,{'phase':'opening','main':main,'mainIdentity':window_identity(main),'beforeWindows':before,'beforeGroupIds':info['beforeGroupIds'],'account':info['account'],'plan':plan,'selections':[]})
    c=controls(d)
    try:
        activate(c,main);c.click(main['x']+285,main['y']+58);c.wait(100)
        point=unique_line(rows(d,[main['x']+190,main['y']+75,main['x']+390,main['y']+200],lang='eng'),'Start Group Chat')
        c.click(*point);c.wait(200)
        added=[w for w in d.app_windows() if w['id'] not in {x['id'] for x in before}]
        if len(added)!=1:raise PreparationError('GROUP_PICKER_NOT_PROVED','One owned group picker required.',clean=False)
        picker=added[0];picker_proof(picker,window_identity(picker),main,v['mainIdentity'])
        v.update(phase='selecting',picker=picker,pickerIdentity=window_identity(picker));write(d,j,v)
        from .recipes import paste_field
        for target in plan['eligible']:
            if d.app_windows()!=sorted(before+[picker],key=lambda w:w['id']):raise ValueError('group picker window set changed')
            row=info['contacts'][target];query=person_query(row,d.name_peer)
            v['selectionTarget']=target;v['selectionQuerySHA256']=hashlib.sha256(query.encode()).hexdigest();write(d,j,v)
            activate(c,picker);paste_field(c,[picker['x']+160,picker['y']+35],query);c.wait(150)
            sections=rows(d,[picker['x']+20,picker['y']+65,picker['x']+334,picker['y']+510],lang='eng',contrast=True)
            primary=primary_person_column(picker,sections)
            points=single_local_result(screen(d),primary)
            v['primaryResultBounds']=primary;write(d,j,v)
            if len(points)!=1:
                diagnostic=screen(d).crop((picker['x'],picker['y'],picker['x']+picker['width'],picker['y']+picker['height']))
                target_file=d.previews/(j['id']+'-group-person-result.png');diagnostic.save(target_file);target_file.chmod(0o600)
                v['selectionFailure']={'target':target,'checkboxCount':len(points),'diagnosticSHA256':hashlib.sha256(target_file.read_bytes()).hexdigest()};write(d,j,v)
                raise ValueError('one native filtered person checkbox required')
            c.click(*points[0]);c.wait(150)
            patch=screen(d).crop((points[0][0]-10,points[0][1]-10,points[0][0]+11,points[0][1]+11)).convert('RGB')
            if sum(g>r+20 and g>b+10 for r,g,b in patch.getdata())<15:raise ValueError('selected person checkbox not proved')
            v['selections'].append({'peer':target,'querySHA256':hashlib.sha256(query.encode()).hexdigest(),'nativeUniqueQueryCopiedBack':True})
            write(d,j,v)
        controls_found=picker_buttons(d,picker)
        selected_box=[picker['x']+345,picker['y']+60,picker['x']+740,picker['y']+500]
        v.update(phase='preview',finishPoint=controls_found['Finish'],cancelPoint=controls_found['Cancel'],selectedBox=selected_box,selectedSHA256=hashlib.sha256(screen(d).crop(tuple(selected_box)).tobytes()).hexdigest())
        write(d,j,v)
        image=screen(d).crop((picker['x'],picker['y'],picker['x']+picker['width'],picker['y']+picker['height']))
        out=d.previews/(j['id']+'.png');temporary=out.with_suffix('.tmp');image.save(temporary,format='PNG');temporary.chmod(0o600);os.replace(temporary,out)
        return {'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'width':image.width,'height':image.height,'context':digest(v),'programRecipe':True,'groupOperationRecipe':True,'summary':{'action':'create_group','anchorPeer':j['peer'],'groupName':j['payload']['group_name'],'selectedMembers':plan['eligible'],'deferredMembers':plan['deferred'],'creatorImplicit':info['account'],'expectedInitialMemberCount':len(plan['eligible'])+1,'allRequestedMembershipClaimed':False}}
    finally:c.close()


def name_value_point(title, sidebar):
    point=[title[0]+30,title[1]+27]
    if not sidebar[0]<point[0]<sidebar[2] or not sidebar[1]<point[1]<sidebar[3]-8:
        raise ValueError('owned inline group-name value is outside its observed property section')
    return point


def name_confirmation_proof(window, identity, main, host):
    if window.get('title')!='wechat' or (window.get('width'),window.get('height'))!=(294,156):
        raise ValueError('exact owned group-name confirmation layout not proved')
    if identity.get('class')!=host.get('class') or any(identity.get(k)!=host.get(k) for k in ('pid','leader')) or identity.get('transientFor')!=main['id'] or '_NET_WM_WINDOW_TYPE_UTILITY' not in identity.get('types',[]):
        raise ValueError('group-name confirmation process/parent mismatch')
    return True


def rename_created(d,j,v,c):
    """Name this exact created group through its inline value and owned Modify."""
    from .recipes import main_window,rows,paste_field,activate
    from .selectors import unique_line
    from .windows import window_identity
    from .ocr import normalized
    current=native_group(d,v['groupPeer']);wanted=set(j['payload']['members'])|{v['account']}
    if not current or current['owner']!=v['account'] or not set(v['creationProof']['actualMembers'])<=set(current['members'])<=wanted:
        raise ValueError('created group identity changed before naming')
    if current['name']==j['payload']['group_name']:
        return v
    if v.get('nameCommitScheduled'):
        raise ValueError('original name commit already scheduled; native reconciliation only')
    main=main_window(d);activate(c,main)
    sidebar=[main['x']+main['width']-250,main['y']+82,main['x']+main['width']-65,main['y']+main['height']-12]
    if not v.get('nameValueCopiedBack'):
        if not v.get('sidebarOpened'):
            v.update(phase='name-sidebar-intent');write(d,j,v)
            c.click(main['x']+main['width']-20,main['y']+55);c.wait(200)
            v['sidebarOpened']=True;write(d,j,v)
        title=unique_line(rows(d,sidebar,lang='eng'),'Group Name')
        point=name_value_point(title,sidebar)
        v.update(phase='name-value-intent',nameValuePoint=point);write(d,j,v)
        paste_field(c,point,j['payload']['group_name'])
        v.update(phase='name-confirmation-opening',nameValueCopiedBack=True,nameValueSHA256=hashlib.sha256(j['payload']['group_name'].encode()).hexdigest());write(d,j,v)
        c.click(main['x']+420,main['y']+55);c.wait(150)
    windows=d.app_windows();before=v['beforeWindows']
    added=[w for w in windows if w['id'] not in {x['id'] for x in before}]
    if len(added)!=1 or any(w not in windows for w in before):
        raise ValueError('one owned name confirmation must follow the copied-back value')
    dialog=added[0];identity=window_identity(dialog);name_confirmation_proof(dialog,identity,main,v['mainIdentity'])
    unique_line(rows(d,[dialog['x']+15,dialog['y']+25,dialog['x']+279,dialog['y']+65],lang='eng',psm=6),'Edit group name?')
    modify=unique_line(rows(d,[dialog['x']+25,dialog['y']+90,dialog['x']+142,dialog['y']+123],lang='eng',psm=6),'Modify')
    unique_line(rows(d,[dialog['x']+155,dialog['y']+90,dialog['x']+272,dialog['y']+123],lang='eng',psm=6),'Cancel')
    v.update(phase='name-save-intent',nameConfirmationDialog=dialog,nameConfirmationIdentity=identity,nameCommitScheduled=True);write(d,j,v)
    activate(c,dialog);c.click(*modify)
    for pause in (100,200,400,800,1200):
        c.wait(pause);current=native_group(d,v['groupPeer'])
        if current and current['name']==j['payload']['group_name']:
            if d.app_windows()!=before:raise ValueError('name committed but owned confirmation has not settled')
            labels={normalized(row['text']) for row in rows(d,sidebar,lang='eng')}
            known=labels&{'groupname','groupqrcode','myaliasingroup','searchchathistory','remark'}
            if len(known)==1:raise ValueError('owned sidebar state is ambiguous after name commit')
            v.update(phase='named',nameCommitted=True,sidebarOpened=bool(known),sidebarAutoClosedAfterOwnedNameEdit=not known,nameEditorKind='inline-value-with-owned-Modify-confirmation');write(d,j,v)
            return v
    raise ValueError('name commit not yet natively verified; never re-create')


def execute(d,j):
    from .recipes import controls,activate,screen
    from .windows import window_identity
    require_unattempted(d,j);v=read(d,j)
    if not v or v['phase']!='preview' or j['preview'].get('context')!=digest(v):raise BeforeEffect('group preview/journal changed')
    picker=v['picker']
    if d.app_windows()!=sorted(v['beforeWindows']+[picker],key=lambda w:w['id']) or window_identity(picker)!=v['pickerIdentity']:raise BeforeEffect('owned picker changed')
    if hashlib.sha256(screen(d).crop(tuple(v['selectedBox'])).tobytes()).hexdigest()!=v['selectedSHA256']:raise BeforeEffect('actual selected members changed')
    info=directory(d,j)
    if info['existingNamePeers']:raise BeforeEffect('exact group appeared; do not create a duplicate')
    plan=member_plan(v['account'],j['payload']['members'],info['contacts'])
    if plan['eligible']!=v['plan']['eligible']:raise BeforeEffect('friendship changed; frozen selected roster preserved')
    c=controls(d)
    try:
        activate(c,picker)
        d._save_attempt(j,{'action':'create_group','anchorPeer':j['peer'],'startedAt':time.time(),'creationClickScheduled':True,'payloadSHA256':digest(j['payload']),'beforeGroupIds':v['beforeGroupIds'],'selectedMembers':plan['eligible']})
        v.update(phase='create-click-intent');write(d,j,v);c.click(*v['finishPoint'])
        proof=None
        for pause in (100,200,400,800,1200,1600):
            c.wait(pause)
            try:proof=new_group_proof(v['beforeGroupIds'],current_new_groups(d,v['beforeGroupIds']),v['account'],plan['eligible']);break
            except ValueError:pass
        if proof is None:return {'state':'unknown','reason':'creation-clicked-native-group-not-yet-unique','automaticReplay':False}
        v.update(phase='created',groupPeer=proof['groupPeer'],creationProof=proof);write(d,j,v)
        v=rename_created(d,j,v,c)
        return verify(d,j)
    except Exception as error:
        if (d.root/(j['id']+'-attempt.json')).exists():
            v['lastEffectFailure']={'type':type(error).__name__,'detail':str(error)[:180],'phase':v.get('phase')};write(d,j,v)
            return effect_failure(v,error)
        raise
    finally:c.close()


def verify(d,j):
    v=read(d,j)
    if not v or not v.get('groupPeer'):return {'state':'unknown','reason':'no-unique-created-group-proof','automaticReplay':False}
    current=native_group(d,v['groupPeer']);wanted=set(j['payload']['members'])|{v['account']}
    if not current or current['owner']!=v['account'] or not current['inGroup'] or not set(v['creationProof']['actualMembers'])<=set(current['members'])<=wanted:
        return {'state':'unknown','reason':'created-group-name-or-membership-not-yet-proved','groupPeer':v['groupPeer'],'groupCreated':True,'automaticReplay':False}
    actual=set(current['members']);named=current['name']==j['payload']['group_name'];pending=not named or v.get('phase')!='settled'
    proof=dict(v['creationProof']);proof.update(actualMembers=sorted(actual),memberCount=len(actual),membershipSHA256=digest(sorted(actual)),unconfirmedSelectedMembers=sorted(set(v['creationProof'].get('unconfirmedSelectedMembers',[]))-actual))
    return dict(proof,state='accepted',peer=v['groupPeer'],groupName=current['name'],requestedGroupName=j['payload']['group_name'],groupNameVerified=named,nameSetupPending=not named,postActionPending=pending,navigationRecoveryPending=pending,groupCreated=True,creationClicks=1,deferredMembers=[row for row in v['plan']['deferred'] if row['peer'] not in actual],deferredPlanScope='creation operation only; consult separate friendship/invitation receipts',missingRequestedMembers=sorted(wanted-actual),allRequestedMembersPresent=actual==wanted,messagesSent=0,ordinaryChatSendClicks=0,automaticReplay=False)


def cleanup(d,j):
    from . import navigation
    from .recipes import controls,activate,rows
    from .selectors import unique_line
    from .windows import window_identity
    v=read(d,j)
    if (d.root/(j['id']+'-attempt.json')).exists() and (not v or not v.get('groupPeer') or not verify(d,j).get('groupNameVerified')):
        return False
    if not v:return navigation.finish(d,j)
    c=controls(d)
    try:
        if v.get('nameDialog') and v['nameDialog'] in d.app_windows():
            if window_identity(v['nameDialog'])!=v['nameDialogIdentity'] or not v.get('nameCommitted'):return False
            return False
        picker=v.get('picker')
        if picker and picker in d.app_windows():
            if (d.root/(j['id']+'-attempt.json')).exists() or window_identity(picker)!=v['pickerIdentity']:return False
            activate(c,picker)
            point=unique_line(rows(d,[picker['x']+340,picker['y']+510,picker['x']+740,picker['y']+580],lang='eng'),'Cancel')
            c.click(*point);c.wait(150)
            if picker in d.app_windows():return False
        if v.get('sidebarOpened'):
            main=v['main'];sidebar=[main['x']+main['width']-250,main['y']+82,main['x']+main['width']-65,main['y']+main['height']-12]
            from .ocr import normalized
            labels={normalized(r['text']) for r in rows(d,sidebar,lang='eng')}
            if len(labels&{'groupname','groupqrcode','myaliasingroup','searchchathistory','remark'})<2:return False
            activate(c,main);c.click(main['x']+main['width']-20,main['y']+55);c.wait(150)
            v['sidebarOpened']=False;write(d,j,v)
        if d.app_windows()!=v['beforeWindows']:return False
        if not navigation.finish(d,j):return False
        v.update(phase='settled',settledAt=time.time());write(d,j,v);return True
    finally:c.close()


def finish(d,j):
    return cleanup(d,j)

import unittest,tempfile,hashlib
from pathlib import Path
import image_client

class ClientImageTests(unittest.TestCase):
    def rejected_viewer(self, changed=False, foreign=False):
        from contextlib import contextmanager
        from unittest.mock import Mock,patch
        from PIL import Image
        viewer={'id':'0x4000d0','title':'Photos and Videos','x':280,'y':31,'width':827,'height':1181}
        identity={'class':['wechat','wechat'],'pid':1234,'leader':'0x400009','transientFor':None,
                  'types':['_NET_WM_WINDOW_TYPE_NORMAL']}
        class Control:
            def __init__(self):self.open=False;self.clicks=[];self.keys=[]
            def one(self,title,optional=False):
                if title=='Photos and Videos':return viewer if self.open else None
                if title=='Weixin':return {'id':'0x400011','title':'Weixin'}
                return None
            def click(self,*point):
                self.clicks.append(point)
                if len(self.clicks)==2:self.open=True
            def focus(self,w):pass
            def require_focus(self,w):pass
            def wait(self,ms):pass
            def close(self):pass
            def key(self,key):
                self.keys.append(key)
                if key==0xff1b:self.open=False
        control=Control();selected=Mock();im=Image.new('RGB',(1387,1244),'white')
        selected.screenshot.return_value=im
        box=[0,0,600,450]
        request={'action':'image','point':[200,250],'context_sha256':hashlib.sha256(im.crop(box).tobytes()).hexdigest()}
        @contextmanager
        def held(_):yield lambda:None
        def window_identity(w):
            # The first lookup freezes the created viewer. A later changed
            # native process must not be closed under the original ownership.
            if w==viewer:
                window_identity.calls+=1
                if foreign:return dict(identity,pid=9999)
                if changed and window_identity.calls>2:return dict(identity,pid=9999)
            return identity
        window_identity.calls=0
        with tempfile.TemporaryDirectory() as td,patch('linux_tool.ROOT',Path(td)), \
                patch('image_client.source',return_value=({'username':'fixture@chatroom'},{})), \
                patch('image_client.locked',held),patch('image_client.Controls',return_value=control), \
                patch('image_client.viewport',return_value=box), \
                patch('operations.windows.window_identity',side_effect=window_identity), \
                patch('operations.lease.birth',return_value='fixture-birth'):
            with self.assertRaisesRegex(ValueError,'official viewer process' if foreign else 'not a calibrated inactive layout') as error:
                image_client.dispatch(Mock(),request,ui=selected)
            self.assertEqual(error.exception.image_export_stage,'save-control')
            if not foreign:
                x,y=viewer['x'],viewer['y']
                prefix=im.crop((x,y,x+640,y+44))
                self.assertEqual(error.exception.image_toolbar_fingerprint,hashlib.sha256(prefix.tobytes()).hexdigest())
        return control

    def test_unknown_save_toolbar_closes_only_original_viewer_without_toolbar_click(self):
        control=self.rejected_viewer()
        self.assertFalse(control.open)
        self.assertEqual(control.keys,[0xff1b])
        self.assertEqual(control.clicks,[(200,250),(200,250)])

    def test_gallery_arrows_and_viewer_edges_do_not_obscure_the_exact_save_control(self):
        from unittest.mock import Mock, patch
        from PIL import Image
        viewer={'id':'0x4000d0','title':'Photos and Videos','x':0,'y':0,'width':827,'height':500}
        main={'id':'0x400011','title':'Weixin'}
        identity={'class':['wechat','wechat'],'pid':1234,'leader':'0x400009','transientFor':None,
                  'types':['_NET_WM_WINDOW_TYPE_NORMAL']}
        known=Image.new('RGB',(827,500),(230,230,232))
        known.paste((45,45,45),(513,15,527,28))
        masked=known.crop((0,0,640,42))
        masked.paste((0,0,0),(73,16,87,28))
        masked.paste((0,0,0),(113,16,127,28))
        masked.paste((0,0,0),(635,19,639,23))
        expected=hashlib.sha256(masked.tobytes()).hexdigest()
        active=known.copy()
        active.paste((70,70,70),(73,16,87,28))
        both=active.copy()
        both.paste((70,70,70),(113,16,127,28))
        both.paste((100,100,100),(0,42,640,44))
        both.paste((120,120,120),(635,19,639,23))
        wrong_save=both.copy()
        wrong_save.putpixel((520,21),(0,0,0))
        control=Mock()
        control.one.side_effect=lambda title,optional=False: {'Photos and Videos':viewer,'Weixin':main}.get(title)
        with patch.object(image_client,'GALLERY_SAVE_TOOLBAR',expected,create=True), \
                patch('operations.windows.window_identity',return_value=identity), \
                patch('operations.lease.birth',return_value='fixture-birth'):
            opened=image_client.viewer_save_proof(viewer,both)
            self.assertEqual(opened['point'],[520,21])
            with self.assertRaisesRegex(ValueError,'not a calibrated inactive layout'):
                image_client.viewer_save_proof(viewer,wrong_save)
            with self.assertRaisesRegex(ValueError,'full current toolbar changed'):
                image_client.prove_viewer_save_input(control,viewer,Mock(side_effect=[active,both]),Mock())
            control.click.assert_not_called()

    def test_changed_viewer_process_is_left_protected(self):
        control=self.rejected_viewer(changed=True)
        self.assertTrue(control.open)
        self.assertEqual(control.keys,[])

    def test_foreign_viewer_process_is_not_cleanup_authority(self):
        control=self.rejected_viewer(foreign=True)
        self.assertTrue(control.open)
        self.assertEqual(control.keys,[])

    def test_converted_official_file_requires_exact_native_filename(self):
        import io
        from PIL import Image
        b=io.BytesIO();Image.new('RGB',(40,30),'red').save(b,format='JPEG');data=b.getvalue()
        native={'time':120,'sourceLocalId':7,'imageMetadata':{'md5':'a'*32}}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'image';p.write_bytes(data)
            with self.assertRaises(ValueError):image_client.verify_export(p,'a'*32,root)
            for name in ['Weixin Image_19700101080200_8_1.jpg','Weixin Image_19700101080201_7_1.jpg','unverified.jpg']:
                with self.assertRaises(ValueError):image_client.verify_visible_export(p,native,root,name)
            actual,proof=image_client.verify_visible_export(p,native,root,'Weixin Image_19700101080200_7_1.jpg')
            self.assertEqual(actual,data);self.assertEqual(proof['representation'],'official-visible-variant')
            self.assertTrue(proof['nativeSourceIdentityVerified'])

    def test_visible_export_accepts_exact_image_without_filename_proof(self):
        import io
        from PIL import Image
        b = io.BytesIO()
        Image.new('RGB', (40, 30), 'red').save(b, format='PNG')
        data = b.getvalue()
        native = {'time': 120, 'sourceLocalId': 7, 'imageMetadata': {'md5': hashlib.md5(data).hexdigest()}}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / 'image.png'
            p.write_bytes(data)
            actual, proof = image_client.verify_visible_export(p, native, root, 'Localized default.png')
        self.assertEqual(actual, data)
        self.assertEqual(proof['representation'], 'original')
        self.assertEqual(proof['sourceIdentityMethod'], 'native-message-md5')
        self.assertNotIn('officialDefaultFilename', proof)

    def test_reparented_viewer_uses_absolute_display_coordinates(self):
        rows=image_client.parse_windows('  0x400075 "Photos and Videos": ("wechat" "wechat") 827x501+0+0 +280+371\n')
        self.assertEqual((rows[0]['x'],rows[0]['y']),(280,371))

    def test_internal_selected_ui_is_used_without_reloading_old_global_binding(self):
        from unittest.mock import Mock,patch
        from contextlib import contextmanager
        from PIL import Image
        target={'username':'group@chatroom','displayName':'Fixture group'}
        selected=Mock();selected.config.return_value={'header_box':[0,0,100,30],'editor':[50,90]}
        selected.screenshot.return_value=Image.new('RGB',(120,120),'white')
        @contextmanager
        def held(_):yield lambda:None
        with patch('image_client.source',return_value=(target,{})),patch('image_client.locked',held), \
                patch('sender.UI',side_effect=ValueError('old global binding must not be loaded')):
            result=image_client.dispatch(Mock(),{'action':'image_prepare'},ui=selected)
        self.assertEqual(result['state'],'image_context_ready');selected.preflight.assert_called_once()
    def test_xml_entity_and_non_image_or_ambiguous_hash_rejected(self):
        for raw,kind in [('<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><msg/>',3),('<msg><img md5="'+'a'*32+'"/></msg>',1),('<msg><img md5="'+'a'*32+'"/><img md5="'+'b'*32+'"/></msg>',3)]:
            with self.assertRaises(ValueError):image_client.source_info(raw,kind)
    def test_click_cannot_target_sidebar_editor_or_send_control(self):
        for point in [[340,300],[1047,751],[695,671],[True,400],[-1,20]]:
            with self.assertRaises(ValueError):image_client.validate_point(point,[495,200,1097,637])
        self.assertEqual(image_client.validate_point([695,420],[495,200,1097,637]),[695,420])
    def test_changed_context_stops_before_gui_action(self):
        with self.assertRaises(ValueError):image_client.check_context(b'new','0'*64)
    def test_mismatched_export_is_not_accepted_as_requested_picture(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td).resolve();(p/'image.png').write_bytes(b'not requested image')
            with self.assertRaises(ValueError):image_client.verify_export(p/'image.png','a'*32,p)
    def test_source_hash_and_size_are_whitelisted_not_aes_keys(self):
        d=image_client.source_info('<msg><img md5="'+'a'*32+'" hdlength="143507" aeskey="do-not-export" cdnmidimgurl="private"/></msg>',3)
        self.assertEqual(d,{'md5':'a'*32,'hdlength':143507})
    def test_window_parser_only_accepts_native_wechat_windows(self):
        s='0x2000f4 "Photos and Videos": ("wechat" "wechat") 1214x521+32+189 +32+189\n0x444 "Save": ("other" "other") 647x432+0+0 +0+0'
        self.assertEqual(image_client.parse_windows(s),[{'id':'0x2000f4','title':'Photos and Videos','x':32,'y':189,'width':1214,'height':521}])
    def test_focus_returns_to_main_only_after_owned_viewer_is_closed(self):
        class C:
            def __init__(self,dialog=None):self.dialog=dialog;self.focused=None
            def one(self,title,optional=False):return self.dialog if title=='Save' else ({'id':'main'} if title=='Weixin' else None)
            def focus(self,w):self.focused=w['id']
        c=C();image_client.restore_main_focus(c);self.assertEqual(c.focused,'main')
        c=C({'id':'save'});image_client.restore_main_focus(c);self.assertIsNone(c.focused)

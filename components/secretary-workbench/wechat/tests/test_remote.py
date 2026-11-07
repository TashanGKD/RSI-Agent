import unittest
from remote import validate_request,decode_text,check_header,canonical_send,require_supported_sources
from remote import handle
class RemoteTests(unittest.TestCase):
    def test_retired_model_listener_cannot_resume_through_old_actions(self):
        for action in ['read','ack','send']:
            self.assertEqual(handle({'action':action})['state'],'legacy_automatic_bridge_retired')
    def test_no_arbitrary_recipient(self):
        with self.assertRaises(ValueError):validate_request({'action':'send','peer':'someone','text':'x','request_id':'a'*64})
    def test_unknown_action_and_invalid_cursor(self):
        for p in [{'action':'shell'},{'action':'read','after':True},{'action':'read','after':-1}]:
            with self.assertRaises(ValueError):validate_request(p)
    def test_request_cannot_be_path_or_shell(self):
        for ident in ['../../file','a\nwhoami','x'*65]:
            with self.assertRaises(ValueError):validate_request({'action':'send','request_id':ident,'text':'x'})
    def test_changed_target_refused(self):
        with self.assertRaises(ValueError):check_header(b'changed','a'*64)
    def test_shell_message_remains_data(self):
        r=validate_request({'action':'send','request_id':'a'*64,'text':'$(id); `echo hello`'})
        self.assertEqual(r['text'],'$(id); `echo hello`')
    def test_text_bounds(self):
        with self.assertRaises(ValueError):decode_text(b'x'*32769)
    def test_native_trailing_newline_normalization(self):
        self.assertEqual(canonical_send('答复\r\n\r\n'),canonical_send('答复'))
    def test_fts_and_resources_are_not_new_message_partitions(self):
        require_supported_sources(['message_0.db','message_fts.db','message_resource.db'])
    def test_new_partition_or_missing_source_is_explicit_gap(self):
        for names in [['message_0.db','message_1.db'],['message_fts.db']]:
            with self.assertRaises(ValueError):require_supported_sources(names)
if __name__=='__main__':unittest.main()

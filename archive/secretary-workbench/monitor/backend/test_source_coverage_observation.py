import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import work_observer as observer


class SourceCoverageObservationTests(unittest.TestCase):
    def observe(self, value):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root/'unified-mention-runtime/runtime/status.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(value))
            sources = {}
            with patch.object(observer, 'METHOD', root):
                result = observer.system_observation(sources, '2026-11-05T07:30:00Z')
            return result, sources

    def test_connected_but_incomplete_coverage_keeps_per_source_gaps(self):
        data = {'sourceReady':True, 'sourceCoverageComplete':False,
                'bindings': {'ready':{'sourceReady':True,'lastSourceAt':100},
                             'missing':{'sourceReady':False,'lastSourceAt':90,
                                        'sourceGapReason':'message_table_missing'}}}
        result, sources = self.observe(data)
        event = result['event']
        self.assertTrue(event['sourceReady'])
        self.assertFalse(event['sourceCoverageComplete'])
        self.assertEqual(event['bindings']['missing']['sourceGapReason'], 'message_table_missing')
        source = sources[result['eventSourceId']]
        self.assertEqual(json.loads(source['text']), event)
        self.assertNotIn('waitingForIdle', event)

    def test_older_status_does_not_infer_all_sources_readable(self):
        result, _ = self.observe({'sourceReady':True,'bindings':{'a':{'sourceReady':True}}})
        self.assertIsNone(result['event']['sourceCoverageComplete'])
        self.assertIsNone(result['event']['bindings']['a']['sourceGapReason'])

    def test_78_bindings_remain_sources_and_metadata_fits_existing_evidence_limit(self):
        data = {'sourceReady':True, 'sourceCoverageComplete':False, 'bindings':{}}
        for i in range(78):
            data['bindings']['secretary-auto-'+str(20818257052+i)] = {
                'sourceReady':i<76, 'lastSourceAt':1793862949.6451926,
                'sourceGapReason':None if i<76 else 'message_table_missing'}
        result, sources = self.observe(data)
        event = result['event']
        self.assertEqual(len(event['bindings']),78)
        self.assertEqual(sum(v['sourceReady'] is True for v in event['bindings'].values()),76)
        self.assertEqual(json.loads(sources[result['eventSourceId']]['text']), event)
        self.assertNotIn('employees',event)

    def test_private_reason_or_wrong_coverage_type_is_not_repeated_as_fact(self):
        result, sources = self.observe({'sourceReady':True,'sourceCoverageComplete':'yes',
                                       'bindings':{'a':{'sourceReady':False,
                                                        'sourceGapReason':'/private/password=secret'}}})
        event = result['event']
        self.assertIsNone(event['sourceCoverageComplete'])
        self.assertIsNone(event['bindings']['a']['sourceGapReason'])
        self.assertNotIn('password',json.dumps(sources))

def setUpModule():
 from unittest.mock import patch
 import contextlib,collect,send_tool_observer,delivery_obligations,employee_profiles,account_contract,model_accounts
 global _portable_patches
 _portable_patches=contextlib.ExitStack()
 clients={'secretary':'secretary','science':'science','organoid_bp':'organoid','forum_employee':'forum','employee_pilot':'employee-pilot','employee_method':'system','aup_support':'aup-support','research_secretary':'research-secretary'}
 ids={'secretary':'00000000-0000-4000-8000-4344f0fd9daa','science':'00000000-0000-4000-8000-37b7cd446cba','organoid':'00000000-0000-4000-8000-f709f264f942'}
 emails=tuple('fixture'+str(i)+'@example.invalid' for i in range(3))
 for mod,key,value in [(send_tool_observer,'CLIENTS',clients),(collect,'IDS',ids),(delivery_obligations,'CLIENTS',clients),(delivery_obligations,'OWNERS',ids),(employee_profiles,'IDS',ids),(account_contract,'EMAILS',emails),(model_accounts,'EMAILS',emails)]:
  _portable_patches.enter_context(patch.object(mod,key,value))
def tearDownModule():
 _portable_patches.close()

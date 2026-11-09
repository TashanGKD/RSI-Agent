import json
from pathlib import Path
import subprocess
import sys
import unittest
WORKER=Path(__file__).resolve().parents[2]/'src/MacWorker/mac_worker.py'
class WorkerProtocol(unittest.TestCase):
    def test_two_invalid_requests_each_have_one_response_and_worker_survives(self):
        result=subprocess.run([sys.executable,str(WORKER),'--serve'],input='{}\n{}\n',text=True,capture_output=True,timeout=10)
        responses=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses),2,'one client request must not end the reusable worker')
        self.assertTrue(all(r['status']=='missing' for r in responses))
        self.assertEqual(result.returncode,0)
    def test_bad_json_array_and_oversized_line_do_not_corrupt_following_request(self):
        payload='{bad}\n[]\n'+'x'*40000+'\n{}\n'
        result=subprocess.run([sys.executable,str(WORKER),'--serve'],input=payload,text=True,capture_output=True,timeout=10)
        responses=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses),4)
        self.assertTrue(all(r['status']=='missing' for r in responses))
        self.assertEqual(result.returncode,0)
    def test_single_command_remains_compatible(self):
        result=subprocess.run([sys.executable,str(WORKER)],input='{}\n',text=True,capture_output=True,timeout=10)
        self.assertEqual(json.loads(result.stdout)['status'],'missing')
if __name__=='__main__':unittest.main()

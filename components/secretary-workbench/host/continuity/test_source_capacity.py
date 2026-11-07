"""Read-only route budget tests; no message read, native import or queue call."""
import copy
import json
import time
import unittest
from pathlib import Path
from native_source import ACCOUNT, validated_routes
ROOT = Path(__file__).resolve().parent

def synthetic(count):
    return [dict(id='scope-' + str(i), account=ACCOUNT, peer=str(90000000 + i) + '@chatroom', since=1) for i in range(count)]

def accepts(rows):
    try:
        return validated_routes(rows) == rows
    except ValueError:
        return False

class Capacity(unittest.TestCase):

    def test_duplicate_peer_and_id_reject_within_large_batch(self):
        for field in ('peer', 'id'):
            rows = synthetic(78)
            rows[-1][field] = rows[0][field]
            self.assertFalse(accepts(rows))

    def test_foreign_account_is_not_new_capacity(self):
        rows = synthetic(78)
        rows[-1]['account'] = 'wxid_fixture_4af1fa1e0d'
        self.assertFalse(accepts(rows))

    def test_peer_injection_rejected_in_large_batch(self):
        rows = synthetic(78)
        rows[-1]['peer'] = '20726381676@chatroom;DROP TABLE x'
        self.assertFalse(accepts(rows))

    def test_route_budget_remains_finite(self):
        self.assertFalse(accepts(synthetic(129)))
        self.assertFalse(accepts([]))

    def test_128_valid_routes_accepted(self):
        self.assertTrue(accepts(synthetic(128)), '128 bounded routes must fit')
if __name__ == '__main__':
    unittest.main()

from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import os
import unittest

spec=spec_from_file_location('local_signing',Path(__file__).resolve().parents[1]/'scripts/local-signing.py')
signing=module_from_spec(spec);spec.loader.exec_module(signing)

class SigningSelection(unittest.TestCase):
    def select(self,teams,missing=False):
        fingerprints=['A'*40,'B'*40]
        name='Apple Development: Fixture'
        def run(arguments,**kwargs):
            if arguments[1]=='find-identity':
                return SimpleNamespace(stdout='\n'.join(f'{i+1}) {value} "{name}"' for i,value in enumerate(fingerprints)))
            if arguments[1]=='find-certificate':
                return SimpleNamespace(stdout=b'-----BEGIN CERTIFICATE-----A-----END CERTIFICATE-----\n-----BEGIN CERTIFICATE-----B-----END CERTIFICATE-----')
            if arguments[1]=='x509':
                index=0 if b'-----A-----' in kwargs['input'] else 1
                fingerprint=fingerprints[index] if not(missing and index==1) else 'C'*40
                return SimpleNamespace(stdout=f'subject=CN=Fixture,OU={teams[index]},O=Fixture\nSHA1 Fingerprint={fingerprint}\n'.encode())
            raise AssertionError('Selection attempted an unexpected or signing command')
        with patch.dict(os.environ,{'WECHAT_COLLECTOR_SIGN_IDENTITY':''}),patch.object(signing.subprocess,'run',side_effect=run):
            return signing.local_signing_identity()
    def test_same_team_uses_existing_certificate(self):
        self.assertEqual(self.select(['TEAM000001','TEAM000001']),'A'*40)
    def test_same_name_different_teams_must_not_guess(self):
        self.assertEqual(self.select(['TEAM000001','TEAM000002']),'-')
    def test_missing_exact_fingerprint_must_not_guess(self):
        self.assertEqual(self.select(['TEAM000001','TEAM000001'],missing=True),'-')
    def test_explicit_invalid_identity_rejected_without_keychain(self):
        with patch.dict(os.environ,{'WECHAT_COLLECTOR_SIGN_IDENTITY':'fixture; command'}),patch.object(signing.subprocess,'run') as run:
            with self.assertRaises(ValueError):signing.local_signing_identity()
            run.assert_not_called()

if __name__=='__main__':unittest.main()

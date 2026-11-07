"""Select an existing, unambiguous local development team; never create/export keys."""
import os
import re
import subprocess

def local_signing_identity():
    configured = os.environ.get('WECHAT_COLLECTOR_SIGN_IDENTITY')
    if configured:
        if configured != '-' and not re.fullmatch(r'[A-Fa-f0-9]{40}', configured):
            raise ValueError('Signing identity must be a certificate SHA-1 or - for ad-hoc.')
        return configured
    result = subprocess.run(['/usr/bin/security','find-identity','-v','-p','codesigning'],capture_output=True,text=True,timeout=10,check=True)
    identities = re.findall(r'^\s*\d+\)\s+([0-9A-F]{40})\s+"(Apple Development:[^"\r\n]+)"\s*$',result.stdout,re.M)
    rows=[]
    for fingerprint,name in identities:
        certificates=subprocess.run(['/usr/bin/security','find-certificate','-a','-c',name,'-p'],capture_output=True,timeout=10,check=True)
        if len(certificates.stdout)>1_048_576:raise ValueError('Certificate metadata exceeded the local selection limit.')
        for certificate in re.findall(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',certificates.stdout,re.S):
            metadata=subprocess.run(['/usr/bin/openssl','x509','-noout','-subject','-fingerprint','-sha1','-nameopt','RFC2253'],input=certificate,capture_output=True,timeout=10,check=True).stdout.decode('utf8')
            digest=re.search(r'Fingerprint=([A-Fa-f0-9:]+)',metadata)
            if not digest or digest.group(1).replace(':','').upper()!=fingerprint:continue
            team=re.search(r'(?:,| )OU=([A-Z0-9]{10})(?:,|$)',metadata,re.M)
            if team:rows.append((fingerprint,team.group(1)))
            break
    # Multiple certificates belonging to one team share a stable Apple-anchored
    # designated requirement. Never guess between unrelated developer teams.
    if rows and len(rows)==len(identities) and len({team for _,team in rows})==1:
        print('Using existing Apple Development signing for a stable application identity.')
        return rows[0][0]
    print('No unambiguous development signing team; using local ad-hoc signing.')
    return '-'

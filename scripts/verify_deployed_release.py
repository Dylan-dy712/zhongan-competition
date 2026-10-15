"""Check exact release markers, unified redirect and API routes after Nginx reload."""
import argparse
import time
from urllib.parse import urlparse

import requests


def check(base, revision):
    session=requests.Session();session.trust_env=False
    def get(path):
        response=session.get(base+path,timeout=10,allow_redirects=False)
        if response.status_code!=200:raise RuntimeError(f'{path}: HTTP {response.status_code}')
        return response
    if get('/health').json().get('status')!='ok':raise RuntimeError('API health failed')
    for path in ('/CI_REVISION',f'/.mobile-demo-releases/{revision}/CI_REVISION'):
        if get(path).text.strip()!=revision:raise RuntimeError(f'{path}: release revision mismatch')
    for path in ('/mobile-demo','/mobile-demo/'):
        response=session.get(base+path,timeout=10,allow_redirects=False)
        target=urlparse(response.headers.get('Location',''))
        if response.status_code!=302 or target.path!='/' or target.fragment!='/claim':
            raise RuntimeError(f'{path}: expected unified redirect, received HTTP {response.status_code}, path={target.path!r}, fragment={target.fragment!r}')
    paths=get('/openapi.json').json()['paths']
    if not all(path in paths for path in ('/v1/auth/register','/v1/auth/login','/v1/auth/logout','/v1/me/consents',
        '/v1/me/members/{subject_id}/memory-settings','/v1/conversations/{conversation_id}/memory-settings',
        '/v1/cases/{case_id}/reports/{version}/memory-sources')):
        raise RuntimeError('Account or memory API routes missing')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--revision',required=True);parser.add_argument('--base',default='http://127.0.0.1');parser.add_argument('--attempts',type=int,default=10)
    args=parser.parse_args();error=None
    for attempt in range(args.attempts):
        try:
            check(args.base.rstrip('/'),args.revision)
            print('RELEASE_CHECKS_PASSED revision='+args.revision);return
        except (requests.RequestException,ValueError,KeyError,RuntimeError) as exc:
            error=exc
            if attempt+1<args.attempts:time.sleep(1)
    raise SystemExit('RELEASE_CHECKS_FAILED: '+str(error))


if __name__=='__main__':main()

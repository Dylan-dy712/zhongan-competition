"""A release must match its markers, redirect and account routes before success."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from scripts import verify_deployed_release as verification


class ReleaseVerificationTests(unittest.TestCase):
    def responses(self, *, redirect_status=302, marker='a'*40, routes=True):
        def get(url, **kwargs):
            if url.endswith('/mobile-demo') or url.endswith('/mobile-demo/'):
                return SimpleNamespace(status_code=redirect_status,headers={'Location':'/#/claim'})
            if url.endswith('/health'):return SimpleNamespace(status_code=200,json=lambda:{'status':'ok'})
            if url.endswith('/openapi.json'):
                paths={p:{} for p in ('/v1/auth/register','/v1/auth/login','/v1/auth/logout','/v1/me/consents')} if routes else {}
                return SimpleNamespace(status_code=200,json=lambda:{'paths':paths})
            return SimpleNamespace(status_code=200,text=marker+'\n')
        return get

    def test_valid_release_and_relative_redirect(self):
        with patch.object(verification.requests,'Session') as session:
            session.return_value.get.side_effect=self.responses()
            verification.check('http://localhost','a'*40)

    def test_old_entry_wrong_revision_and_missing_account_routes_fail(self):
        for changes in ({'redirect_status':200},{'marker':'b'*40},{'routes':False}):
            with self.subTest(changes=changes),patch.object(verification.requests,'Session') as session:
                session.return_value.get.side_effect=self.responses(**changes)
                with self.assertRaises(RuntimeError):verification.check('http://localhost','a'*40)

    def test_reload_is_retried_but_not_falsely_reported_successful(self):
        with patch('sys.argv',['verify','--revision','a'*40,'--attempts','3']),patch.object(verification,'check',side_effect=[RuntimeError('old route'),RuntimeError('old route'),None]) as check,patch.object(verification.time,'sleep') as sleep:
            verification.main();self.assertEqual(check.call_count,3);self.assertEqual(sleep.call_count,2)
        with patch('sys.argv',['verify','--revision','a'*40,'--attempts','1']),patch.object(verification,'check',side_effect=RuntimeError('missing route')):
            with self.assertRaises(SystemExit):verification.main()


if __name__=='__main__':unittest.main()

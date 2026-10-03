import json
import unittest
from unittest.mock import patch
from scripts.deploy_remote import verified_ci_run


class DeployGateTests(unittest.TestCase):
    def test_only_successful_exact_main_push_is_deployable(self):
        sha='a'*40
        passed={'databaseId':123,'headSha':sha,'headBranch':'main','event':'push',
                'status':'completed','conclusion':'success'}
        with patch('scripts.deploy_remote.subprocess.check_output',side_effect=[sha+' refs/heads/main',json.dumps([passed])]):
            self.assertEqual(verified_ci_run(sha),123)
        for changes in ({'headSha':'b'*40},{'headBranch':'feature'},{'event':'pull_request'},
                        {'status':'in_progress'},{'conclusion':'failure'},{'conclusion':'cancelled'}):
            with self.subTest(changes=changes), patch('scripts.deploy_remote.subprocess.check_output',
                side_effect=[sha+' refs/heads/main',json.dumps([{**passed,**changes}])]):
                with self.assertRaises(SystemExit):
                    verified_ci_run(sha)
        with patch('scripts.deploy_remote.subprocess.check_output',return_value='b'*40+' refs/heads/main'):
            with self.assertRaises(SystemExit):
                verified_ci_run(sha)
        with patch('scripts.deploy_remote.subprocess.check_output',side_effect=[sha+' refs/heads/main','[]']):
            with self.assertRaises(SystemExit):
                verified_ci_run(sha)

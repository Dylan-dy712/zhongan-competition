"""Exercise the real deployment script in a temporary host with fake services."""
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Linux deployment harness')
class FrontendDeploymentTests(unittest.TestCase):
    def run_release(self, *, backend_change=False, catalog_change=False, ranker_change=False, fail_nginx=False, fail_backup=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); home=root/'home/ubuntu'
            app=home/'zhongan-app'; release=home/'zhongan-releases/release-fixture'; web=root/'web'; tools=root/'bin'
            def write(path, text):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
            def executable(path,text):
                write(path,'#!/usr/bin/env bash\nset -e\n'+text+'\n');path.chmod(0o755)
            for base in (app,release):
                for relative in ('services','contracts/knowledge','contracts/medical-services','docs/medical/knowledge','scripts'):
                    (base/relative).mkdir(parents=True)
                write(base/'services/api/sql/011_conversations.sql','same schema')
                write(base/'services/api/app/main.py','old' if base==app else 'new' if backend_change else 'old')
                write(base/'scripts/placeholder','same')
                write(base/'contracts/medical-services/catalog.json','new' if base==release and catalog_change else 'same')
                write(base/'REVISION',('a' if base==app else 'b')*40)
                executable(base/'output_dir/memory-ranker/semantix-ranker',
                    "printf '%s\\n' '{\"protocol\":\"zhongan-memory-rank-v1\",\"request_id\":\"deploy-probe\",\"hits\":[]}'"+
                    ('\n# changed ranker' if base==release and ranker_change else ''))
            for unit in ('zhongan-api','zhongan-worker'):
                write(release/f'deploy/{unit}.service','same unit')
                write(root/f'etc/systemd/system/{unit}.service','same unit')
            write(release/'deploy/nginx-zhongan-api.conf','nginx config')
            write(root/'etc/nginx/sites-available/zhongan-api','old nginx config')
            write(web/'index.html','old frontend')
            old_mobile=web/'.mobile-demo-releases'/('a'*40);write(old_mobile/'index.html','old demo')
            (web/'mobile-demo').symlink_to('.mobile-demo-releases/'+'a'*40)
            for relative in ('apps/web/dist','output_dir/mobile-demo/dist'):
                write(release/relative/'index.html','new frontend');write(release/relative/'CI_REVISION','b'*40)
            write(home/'.config/zhongan/database.env','ZHONGAN_DATABASE_URL=synthetic\n')
            tools.mkdir(); log=root/'commands'
            executable(tools/'sudo','if [[ "$1" == chown ]]; then exit 0; fi\nif [[ "$1" == -u ]]; then shift 2; fi\nexec "$@"')
            executable(tools/'systemctl','printf "systemctl %s\\n" "$*" >> "$TEST_LOG"\nif [[ "$1" == is-active ]]; then echo active; fi')
            executable(tools/'nginx','printf "nginx %s\\n" "$*" >> "$TEST_LOG"\nif [[ -f "$FAIL_NGINX" ]]; then rm "$FAIL_NGINX"; exit 1; fi')
            executable(tools/'curl','echo healthy')
            executable(tools/'pg_dump','if [[ "$FAIL_BACKUP" == 1 ]]; then exit 1; fi\necho synthetic-backup')
            executable(tools/'pg_restore','echo synthetic-manifest')
            executable(app/'.venv/bin/python','printf "python %s\\n" "$*" >> "$TEST_LOG"\nif [[ "$1" == -c ]]; then echo synthetic_database; fi')
            failure=root/'fail-nginx'
            if fail_nginx:failure.touch()
            source=(Path(__file__).resolve().parents[1]/'scripts/deploy_update_ubuntu.sh').read_text()
            source=source.replace('/home/ubuntu',str(home)).replace('/var/www/zhongan-web',str(web))
            source=source.replace('/etc/systemd/system',str(root/'etc/systemd/system'))
            source=source.replace('/etc/nginx/sites-available',str(root/'etc/nginx/sites-available'))
            source=source.replace('-C /','-C '+shlex.quote(str(root)))
            write(release/'deploy-test.sh',source)
            env={**os.environ,'PATH':str(tools)+':'+os.environ['PATH'],'TEST_LOG':str(log),
                 'FAIL_NGINX':str(failure),'FAIL_BACKUP':'1' if fail_backup else '0'}
            result=subprocess.run(['bash','deploy-test.sh'],cwd=release,env=env,capture_output=True,text=True,timeout=20)
            return result,log.read_text() if log.exists() else '',(web/'index.html').read_text(),(app/'services/api/app/main.py').read_text()

    def test_ui_release_keeps_running_api_and_skips_database_work(self):
        result,log,html,_=self.run_release()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('BACKEND_CHANGED=0',result.stdout)
        self.assertNotIn('systemctl stop',log);self.assertNotIn('systemctl restart',log)
        self.assertNotIn('migrate_database',log);self.assertEqual(html,'new frontend')

    def test_runtime_change_still_backs_up_migrates_and_restarts(self):
        result,log,_,code=self.run_release(backend_change=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('BACKEND_CHANGED=1',result.stdout)
        self.assertIn('systemctl stop zhongan-api zhongan-worker',log)
        self.assertIn('migrate_database',log);self.assertIn('systemctl restart',log);self.assertEqual(code,'new')

    def test_catalog_change_is_a_runtime_release(self):
        result,log,_,_=self.run_release(catalog_change=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('BACKEND_CHANGED=1',result.stdout)
        self.assertIn('systemctl restart zhongan-api zhongan-worker',log)

    def test_ranker_change_is_a_runtime_release(self):
        result,log,_,_=self.run_release(ranker_change=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('BACKEND_CHANGED=1',result.stdout)
        self.assertIn('systemctl restart zhongan-api zhongan-worker',log)

    def test_ui_failure_rolls_back_without_api_restart(self):
        result,log,html,_=self.run_release(fail_nginx=True)
        self.assertNotEqual(result.returncode,0);self.assertEqual(html,'old frontend')
        self.assertNotIn('systemctl restart',log);self.assertIn('DEPLOY_FAILED',result.stderr)

    def test_failed_database_backup_restores_stopped_services(self):
        result,log,html,code=self.run_release(backend_change=True,fail_backup=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('systemctl restart',log)
        self.assertEqual(html,'old frontend');self.assertEqual(code,'old')

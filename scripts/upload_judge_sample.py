"""Stage a reviewed sample privately for selection; never imports cases or starts analysis."""
import argparse
import hashlib
import json
import re
import shlex
from pathlib import Path, PurePosixPath
from uuid import uuid4

import paramiko


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',required=True)
    parser.add_argument('--key',required=True)
    parser.add_argument('--sample-dir',required=True)
    args=parser.parse_args()
    root=Path(args.sample_dir).resolve()
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    for key in ('sample_id','version'):
        if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}',manifest[key]):raise RuntimeError('Invalid sample identity')
    names=['manifest.json']
    for item in manifest['documents']:
        if not re.fullmatch(r'[a-z0-9-]{1,64}\.pdf',item['file']):raise RuntimeError('Invalid asset path')
        path=root/item['file']
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise RuntimeError('Linked sample asset')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise RuntimeError('Sample hash mismatch')
        if not 0<path.stat().st_size<10*1024*1024:raise RuntimeError('Sample size invalid')
        names.append(item['file'])
    target=PurePosixPath('/home/ubuntu/.config/zhongan/judge-samples')/(manifest['sample_id']+'-'+manifest['version'])
    staging=target.with_name(target.name+'.stage-'+uuid4().hex)
    client=paramiko.SSHClient();client.load_system_host_keys();client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(args.host,username='ubuntu',key_filename=args.key,timeout=15,allow_agent=False,look_for_keys=False)
    try:
        _,out,err=client.exec_command('install -d -m 700 /home/ubuntu/.config/zhongan/judge-samples')
        if out.channel.recv_exit_status():raise RuntimeError('Could not prepare private sample directory')
        with client.open_sftp() as sftp:
            try:
                with sftp.open(str(target/'manifest.json')) as handle:existing=json.loads(handle.read().decode())
                if existing!=manifest:raise RuntimeError('Refuse modifying an existing immutable sample version')
            except FileNotFoundError:
                sftp.mkdir(str(staging),mode=0o700)
                for name in names:
                    sftp.put(str(root/name),str(staging/name));sftp.chmod(str(staging/name),0o600)
                sftp.rename(str(staging),str(target))
            config='/home/ubuntu/.config/zhongan/judge-demo.env'
            with sftp.open(config) as handle:lines=handle.read().decode().splitlines()
            lines=[line for line in lines if not line.startswith('ZHONGAN_JUDGE_SAMPLE_ROOT=')]
            lines.append('ZHONGAN_JUDGE_SAMPLE_ROOT='+str(target))
            with sftp.open(config+'.next','w') as handle:handle.write('\n'.join(lines)+'\n')
            sftp.chmod(config+'.next',0o600)
            sftp.posix_rename(config+'.next',config)
            # The API reads the same reviewed library without loading invitation secrets.
            active='/home/ubuntu/.config/zhongan/judge-sample'
            try:
                import stat
                if not stat.S_ISLNK(sftp.lstat(active).st_mode):raise RuntimeError('Refuse replacing a non-link sample directory')
            except FileNotFoundError:pass
            sftp.symlink(str(target),active+'.next')
            sftp.posix_rename(active+'.next',active)
        code=('import hashlib,json; from pathlib import Path; p=Path('+repr(str(target))+'); '
              'm=json.loads((p/"manifest.json").read_text()); '
              'assert all(hashlib.sha256((p/i["file"]).read_bytes()).hexdigest()==i["sha256"] for i in m["documents"]); '
              'print(json.dumps({"verified_files":len(m["documents"]),"pages":m["page_count"],"private":True,"processing_started":False}))')
        _,out,err=client.exec_command('/home/ubuntu/zhongan-app/.venv/bin/python -c '+shlex.quote(code),timeout=30)
        output=out.read().decode()
        if out.channel.recv_exit_status():raise RuntimeError('Remote sample verification failed')
        receipt=json.loads(output)
        path=Path(__file__).resolve().parents[1]/'output_dir/judge-sample/upload.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        print(output.strip())
    finally:client.close()


if __name__=='__main__':main()

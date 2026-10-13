"""Package committed source and an optional fresh web build, without private inputs."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile


SOURCE_ROOTS = ('apps/web/', 'services/', 'scripts/', 'contracts/', 'docs/', 'deploy/', 'README.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--web-build', action='store_true', help='build from the clean checkout and include static results')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    destination = Path(args.output).resolve()
    if destination.is_relative_to(repo):
        parser.error('submission ZIP must remain outside the repository')
    if destination.exists():
        parser.error('use a new ZIP path to preserve previous submission artifacts')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo).strip():
        parser.error('commit intended changes before freezing the submission source')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    archive = subprocess.check_output(['git', 'archive', '--format=tar', 'HEAD', *SOURCE_ROOTS], cwd=repo)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for member in source:
            if member.isfile():
                path = Path(member.name)
                if path.is_absolute() or '..' in path.parts or \
                   (path.name.startswith('.env') and path.name != '.env.example') or path.suffix in {'.pem', '.key'}:
                    raise ValueError('disallowed source path')
                files['source/' + member.name] = source.extractfile(member).read()
            elif not member.isdir():
                raise ValueError('source package may not contain links')
    if args.web_build:
        npm = 'npm.cmd' if __import__('os').name == 'nt' else 'npm'
        subprocess.check_call([npm, 'run', 'build', '--prefix', 'apps/web'], cwd=repo)
        for path in sorted((repo / 'apps/web/dist').rglob('*')):
            if path.is_symlink():
                raise ValueError('static build may not contain links')
            if path.is_file():
                files['static-demo/' + path.relative_to(repo / 'apps/web/dist').as_posix()] = path.read_bytes()
    files['START_HERE.md'] = ('''# 暖愈智护初赛复现包

代码版本：''' + revision + '''

先读 source/docs/evaluation/preliminary-20261013.md，了解每项结果的实际边界。
保存结果模式：若本包有 static-demo，执行 python -m http.server 4173 --bind 127.0.0.1 --directory static-demo，
浏览器打开 http://127.0.0.1:4173/#/quality-demo。
该页面不需要API、数据库或模型；关怀为保存的模型输出，品质画像为虚构数据方案。
源码重建：cd source，npm ci --prefix apps/web，npm run build --prefix apps/web。
后台与现场模型模式按源码README和初赛复现说明启动，模型密钥由运行者自行配置。

不包含医疗原图、专家参考答案、预测中的个人信息、数据库、访问令牌或私钥。
这些材料只能经主办方授权的独立渠道交付，不能从本包复算真实材料KR1。
本包不是全部KR达标证明；全量实测成绩与待核实项见证据说明。
SHA256清单在 manifest.json，清单本身不包含在自身哈希中。
''').encode('utf-8')
    manifest = {'version': 'preliminary-source-and-synthetic-demo-v1', 'code_revision': revision,
                'includes_real_medical_inputs': False, 'includes_secrets': False,
                'care_view_mode': 'saved_model_outputs_on_synthetic_inputs',
                'quality_view_mode': 'deterministic_synthetic_design',
                'official_kr_verified': False,
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    files['manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in sorted(files.items()):
            bundle.writestr(name, data)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.sha256').write_text(digest + '  ' + destination.name + '\n', encoding='utf-8')
    print(json.dumps({'revision': revision, 'files': len(files), 'bytes': destination.stat().st_size,
                      'sha256': digest, 'official_kr_verified': False}))


if __name__ == '__main__':
    main()

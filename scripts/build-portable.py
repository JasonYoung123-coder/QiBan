"""Build a clean Windows x64 portable folder using Python 3.12 and installed dependencies."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import sysconfig
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON_VERSION = '3.12.10'
PYTHON_SHA256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
PYTHON_URL = f'https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip'


def ignored(directory, names):
    return [name for name in names if name in ('__pycache__', '.pytest_cache', '.ruff_cache', '_virtualenv.py')
            or name.endswith(('.pyc', '.pth'))]


def copy_tree(source, target):
    shutil.copytree(source, target, ignore=ignored)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'release/QiBan-Windows-x64')
    parser.add_argument('--python-archive', type=Path)
    args = parser.parse_args()
    target = args.output.resolve()
    if sys.version_info[:2] != (3, 12) or platform.system() != 'Windows' or platform.machine() != 'AMD64':
        parser.error('Build with Windows x64 Python 3.12 so native wheels match the bundled runtime.')
    if target.exists():
        parser.error('Output already exists. Use a new output folder to preserve data and prevent stale files.')
    for required in ('dist/index.html', 'public/models/Hiyori/Hiyori.model3.json', 'public/models/Natori/Natori.model3.json',
                     'public/vendor/live2dcubismcore.min.js', 'node_modules/electron/dist/electron.exe'):
        if not (ROOT / required).exists():
            parser.error(f'Missing {required}; run setup and build first.')
    archive = args.python_archive or ROOT / '.cache' / f'python-{PYTHON_VERSION}-embed-amd64.zip'
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(PYTHON_URL, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != PYTHON_SHA256:
        parser.error('Python archive checksum mismatch.')
    envelope = target
    target = envelope / 'app'
    target.mkdir(parents=True)
    shutil.copy2(ROOT / '启动桌面.cmd', envelope / '启动桌面.cmd')
    for name in ('backend', 'desktop', 'dist', 'public'):
        copy_tree(ROOT / name, target / name)
    for name in ('README.md', 'LICENSE'):
        shutil.copy2(ROOT / name, target / name)
    (target / 'docs').mkdir()
    for name in ('ASSETS.md', 'VOICE.md', 'PORTABLE.md', 'CONNECTIONS.md', 'PRESETS.md'):
        shutil.copy2(ROOT / 'docs' / name, target / 'docs' / name)
    (target / 'scripts').mkdir()
    for name in ('windows-speech.ps1', 'start-voice.cmd'):
        shutil.copy2(ROOT / 'scripts' / name, target / 'scripts' / name)
    shutil.copy2(ROOT / '.env.example', target / '.env')
    python = target / 'runtime/python'
    python.mkdir(parents=True)
    with zipfile.ZipFile(archive) as package:
        package.extractall(python)
    (python / 'python312._pth').write_text('python312.zip\n.\nLib\\site-packages\n..\\..\nimport site\n', encoding='utf8')
    packages = Path(sysconfig.get_path('purelib'))
    copy_tree(packages, python / 'Lib/site-packages')
    # Retain complete wheel metadata/licenses; exclude development venv .pth files.
    copy_tree(ROOT / 'node_modules/electron/dist', target / 'runtime/electron')
    licenses = target / 'licenses/frontend'
    licenses.mkdir(parents=True)
    shutil.copy2(ROOT / 'src/vendor/airi/LICENSE', target / 'licenses/AIRI-LICENSE')
    frontend_names = []
    for folder in (ROOT / 'node_modules').iterdir():
        candidates = list(folder.iterdir()) if folder.name.startswith('@') and folder.is_dir() else [folder]
        for candidate in candidates:
            metadata = candidate / 'package.json'
            if not metadata.is_file():
                continue
            info = json.loads(metadata.read_text(encoding='utf8'))
            files = [file for file in candidate.iterdir() if file.is_file()
                     and file.name.lower().startswith(('license', 'licence', 'copying', 'notice'))]
            if not files:
                continue
            destination = licenses / info['name'].replace('/', '__')
            destination.mkdir()
            for file in files:
                shutil.copy2(file, destination / file.name)
            frontend_names.append({'name':info['name'], 'version':info['version'], 'license':info.get('license')})
    manifest = {'version':'0.3.2', 'platform':'Windows-x64', 'python':PYTHON_VERSION,
                'python_sha256':PYTHON_SHA256, 'electron':'41.0.3',
                'python_packages': sorted([{'name':d.metadata['Name'],'version':d.version}
                    for d in importlib.metadata.distributions(path=[str(packages)])], key=lambda row:row['name']),
                'frontend_packages':frontend_names}
    (target / 'runtime-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    (target / 'licenses/README.txt').write_text(
        'Python: runtime/python/LICENSE.txt\nElectron/Chromium: runtime/electron/LICENSE*\n'
        'Python packages: runtime/python/Lib/site-packages/*.dist-info/licenses or LICENSE*\n'
        'Frontend packages: licenses/frontend\nLive2D terms: docs/ASSETS.md and public/\n',encoding='utf8')
    subprocess.run([str(python / 'python.exe'), '-c',
                    'import fastapi, uvicorn, sqlalchemy, httpx; from backend.api import create_app; '
                    'from backend.voice_llm import CompanionLLM; from livekit.plugins import silero; '
                    'silero.VAD.load(); print("BUNDLED_IMPORTS_OK")'], cwd=target, check=True)
    total = sum(file.stat().st_size for file in target.rglob('*') if file.is_file())
    print(json.dumps({'output':str(envelope),'bytes':total,'size_mib':round(total/1024**2,1)},ensure_ascii=False))


if __name__ == '__main__':
    main()

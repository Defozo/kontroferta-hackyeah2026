"""Record installed dependency versions and their declared license metadata."""
from importlib.metadata import distributions
from pathlib import Path
import json
ROOT = Path(__file__).resolve().parents[1]
records = []
for dist in distributions():
    meta = dist.metadata
    license = meta.get('License-Expression') or meta.get('License') or next((x for x in meta.get_all('Classifier', []) if x.startswith('License ::')), 'See installed license file')
    records.append({'ecosystem': 'Python', 'name': meta.get('Name'), 'version': dist.version,
                    'declaredLicense': license.splitlines()[0][:200],
                    'licenseFiles': meta.get_all('License-File', [])})
for app, folder in (('web', ROOT / 'apps/web'), ('auth', ROOT / 'apps/auth'), ('verification', ROOT / 'scripts')):
    lock = json.loads((folder / 'package-lock.json').read_text(encoding='utf-8'))
    for key, value in lock.get('packages', {}).items():
        if not key:
            continue
        records.append({'ecosystem': 'npm/' + app, 'name': key.removeprefix('node_modules/'),
                        'version': value.get('version'), 'declaredLicense': value.get('license', 'See package license file')})
records.sort(key=lambda x: (x['ecosystem'], x['name'].lower()))
(ROOT / 'docs' / 'dependencies.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
rows=['# Third-party resources', '', 'DEFOZO SOFTWARE HOUSE | Michał Kiełtyka', '',
      'No application starter was imported. Earlier plans, task PDFs and service catalog references are retained with their original provenance. Documents under fixtures/demo and eval/datasets are fictional, authored with AI assistance. AI model/API use is described in AI_USAGE.md.', '',
      'This inventory records installed package metadata, not a legal license opinion. Original notices remain in installed package distributions and container layers. The software of each dependency remains the work of its respective authors. Versions are locked by uv.lock and package-lock.json.', '',
      'External executables: Python (PSF license), Node.js (MIT plus bundled notices), Tesseract (Apache-2.0), SQLite (public domain), Chromium (BSD-style with bundled third-party notices), Caddy (Apache-2.0). Debian packages retain the notices under /usr/share/doc in the image. The private Windows SQLite runtime is hash-checked by scripts/bootstrap.py.', '',
      'Editable presentation tooling: OpenAI Artifact Tool supplied by the authoring environment; not a runtime dependency of the application. PDF slides and screenshots are exports of the authored presentation and running application.', '',
      '| Ecosystem | Package | Version | Declared license |', '| --- | --- | --- | --- |']
for r in records:
    rows.append('| ' + ' | '.join(str(r[k]).replace('|', '/') for k in ('ecosystem','name','version','declaredLicense')) + ' |')
(ROOT / 'THIRD_PARTY.md').write_text('\n'.join(rows)+'\n', encoding='utf-8')
print(json.dumps({'packages': len(records), 'metadataMissing': sum(r['declaredLicense'].startswith('See ') for r in records)}))

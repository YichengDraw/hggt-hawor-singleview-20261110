#!/usr/bin/env python3
"""Package the verified static comparison and numerical outputs for Pages."""
import argparse
import json
import shutil
import tarfile
from pathlib import Path

import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    args = p.parse_args()
    root = args.root.resolve()
    manifest = json.loads((root / 'site/manifest.json').read_text())
    metrics = json.loads((root / 'reports/metrics.json').read_text())
    assert len(manifest['samples']) == 4 and not metrics['baseline_only']
    public = root / 'delivery/public'
    public.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root / 'site', public / 'docs', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('*.ffmpeg.log'))
    (public / 'docs/.nojekyll').write_text('')
    scripts = public / 'scripts'
    scripts.mkdir(exist_ok=True)
    for name in ['run_hggt.py', 'hggt_geometry.py', 'render_showcase.py',
                 'build_showcase_manifest.py', 'package_delivery.py']:
        shutil.copy2(root / 'scripts' / name, scripts / name)
    shutil.copytree(root / 'scripts/data_eval', scripts / 'data_eval',
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ['README.md', 'PROTOCOL.md']:
        shutil.copy2(root / name, public / name)
    (public / '.gitignore').write_text('__pycache__/\n*.pyc\nweights/\ncache/\ntmp/\nupstream/\n*.tar.gz\n')
    downloads = public / 'docs/downloads'
    predictions = downloads / 'predictions'
    predictions.mkdir(parents=True, exist_ok=True)
    for name in ['metrics.json', 'per_frame_metrics.csv', 'checkpoint_provenance.json', 'geometry_check.json']:
        shutil.copy2(root / 'reports' / name, downloads / name)
    shutil.copy2(root / 'PROTOCOL.md', downloads / 'PROTOCOL.md')
    runtimes = {'hggt': [], 'hawor': []}
    for sample in manifest['samples']:
        sid = sample['id']
        for method in ['hggt', 'hawor']:
            original = root / 'outputs' / method / sid / 'predictions.npz'
            source = np.load(original, allow_pickle=False)
            arrays = {k: source[k] for k in source.files if k != 'source_image_paths'}
            np.savez_compressed(predictions / f'{sid}_{method}.npz', **arrays)
            completion = original.parent / 'complete.json'
            if completion.exists():
                receipt = json.loads(completion.read_text())
                receipt.pop('prediction_file', None)
                runtimes[method].append(receipt)
        render_path = public / 'docs/media' / sid / 'render_provenance.json'
        if render_path.exists():
            render = json.loads(render_path.read_text())
            render['input_source'] = f'{sid}: shared RGB images with original frame IDs'
            render['hggt_source'] = f'../../downloads/predictions/{sid}_hggt.npz'
            render['hawor_source'] = f'../../downloads/predictions/{sid}_hawor.npz'
            render_path.write_text(json.dumps(render, ensure_ascii=False, indent=2) + '\n')
    runtime_source = json.loads((root / 'outputs/hggt/provenance.json').read_text())
    runtime_source.pop('manifest', None)
    runtimes['hggt_configuration'] = runtime_source
    (downloads / 'runtime.json').write_text(json.dumps(runtimes, ensure_ascii=False, indent=2) + '\n')
    # Confirm the real static media/download URLs, excluding navigational anchors.
    missing = []
    def check(url):
        if not url or url.startswith(('http:', 'https:', '#', 'mailto:')):
            return
        if not (public / 'docs' / url.split('#')[0]).is_file(): missing.append(url)
    for entry in manifest.get('downloads', []): check(entry.get('href'))
    for sample in manifest['samples']:
        for media in sample.get('media', {}).values():
            if isinstance(media, str): check(media)
            else:
                check(media.get('src')); check(media.get('poster'))
        for k in sample.get('keyframes', []): check(k.get('src'))
        for item in sample.get('links', []): check(item.get('href'))
    assert not missing, f'Missing public assets: {missing}'
    files = [p for p in public.rglob('*') if p.is_file()]
    assert max(p.stat().st_size for p in files) < 95_000_000
    archive = root / 'delivery/hggt_hawor_results.tar.gz'
    with tarfile.open(archive, 'w:gz', compresslevel=3) as tar:
        for f in sorted(files): tar.add(f, arcname=str(f.relative_to(public)))
    receipt = {'archive': str(archive), 'archive_bytes': archive.stat().st_size,
               'public_files': len(files), 'samples': len(manifest['samples']),
               'images': sum(x['frame_count'] for x in manifest['samples']),
               'metrics_hand_frames': metrics['aggregate'][0]['n'],
               'missing_assets': missing,
               'prediction_sizes': {p.name: p.stat().st_size for p in predictions.glob('*.npz')}}
    (root / 'delivery/receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()

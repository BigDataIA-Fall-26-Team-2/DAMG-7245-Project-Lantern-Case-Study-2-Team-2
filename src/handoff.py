"""Download, restore and validate the shared CS2 development handoff."""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from unittest.mock import patch

import yaml

from src.schema_cs2 import BlockV2, FinancialFact

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'data/handoff/public-and-practice.tar.gz'


def source_paths():
    config = yaml.safe_load((ROOT / 'params.yaml').read_text())
    run_id = config['ingest']['public']['run_id']
    if Path(run_id).name != run_id or run_id in {'.', '..'}:
        raise ValueError('run_id must be a single directory name')
    return [f'data/edgar_comps/{run_id}', f'data/earnings/{run_id}',
            'data/llm_cache/kestrel', 'data/embed_cache/kestrel']


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pack():
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    temporary = ARCHIVE.with_suffix('.tmp')
    try:
        with tarfile.open(temporary, 'w:gz') as archive:
            for source in source_paths():
                directory = ROOT / source
                if not directory.is_dir():
                    raise FileNotFoundError(directory)
                for path in sorted(directory.rglob('*')):
                    if path.is_symlink():
                        raise ValueError(f'Symlinks are not packaged: {path}')
                    if path.is_file():
                        archive.add(path, arcname=path.relative_to(ROOT), recursive=False)
        if temporary.stat().st_size >= 1_000_000_000:
            raise ValueError('Handoff archive exceeds 1 GB; reduce the selected snapshot')
        temporary.replace(ARCHIVE)
    finally:
        temporary.unlink(missing_ok=True)
    print(f'Packaged {ARCHIVE.stat().st_size / 1_000_000:.1f} MB', flush=True)


def restore():
    prefixes = tuple(path + '/' for path in source_paths())
    count = 0
    with tarfile.open(ARCHIVE, 'r:gz') as archive:
        for member in archive:
            if not member.isfile() or not member.name.startswith(prefixes):
                raise ValueError(f'Unexpected handoff member: {member.name}')
            destination = (ROOT / member.name).resolve()
            if not any(destination.is_relative_to(ROOT / source) for source in source_paths()):
                raise ValueError('Archive path escapes the repository')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
                temporary = Path(output.name)
                try:
                    with archive.extractfile(member) as source:
                        shutil.copyfileobj(source, output)
                    output.close()
                    if destination.exists():
                        if digest(destination) != digest(temporary):
                            raise ValueError(f'Local file differs: {member.name}. Move your modified run aside before restoring.')
                    else:
                        temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
            count += 1
    print(f'Restored/verified {count} source and cache files', flush=True)


def validate(samples_only=False):
    for name, model in [('records', BlockV2), ('facts', FinancialFact)]:
        count = 0
        for line in (ROOT / f'examples/cs2/{name}.jsonl').read_text().splitlines():
            model.model_validate_json(line)
            count += 1
        print(f'{count} valid sample {name}', flush=True)
    if samples_only:
        print("JSONL samples ready; no AWS or API key required.")
        return
    from examples.synthetic.run_profile import main as replay
    with patch.dict(os.environ, {'LANTERN_LLM_MODE': 'replay'}), patch(
        'src.llm.client.Client._openai', side_effect=AssertionError('Provider access forbidden in replay')
    ):
        replay()
    print('Handoff ready: source documents restored, JSONL valid, model/embedding replay passed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local', action='store_true', help='Use the downloaded archive without contacting S3')
    parser.add_argument('--pack', action='store_true', help='Maintainer: package the configured recorded inputs')
    parser.add_argument('--samples-only', action='store_true', help='Validate the Git-shared record/fact examples without AWS')
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.samples_only:
        validate(samples_only=True)
        return
    if args.pack:
        pack()
        return
    if not args.local:
        subprocess.run(['dvc', 'pull', 'data/handoff.dvc'], check=True)
    restore()
    validate()


if __name__ == '__main__':
    main()

"""Use clean interpreters: conftest imports the API and can mask missing models."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "entrypoint", ["app.common.db.session", "scripts.seed", "app.common.db.models"]
)
def test_entrypoint_registers_complete_shared_metadata(entrypoint):
    result = subprocess.run(
        [sys.executable, "-c", f"""
import importlib
from pathlib import Path
from sqlalchemy import inspect

importlib.import_module({entrypoint!r})
from app.common.db.base import Base

# Capture registration BEFORE independently discovering modules. Discovery
# must not repair an incomplete registry and give this test a false pass.
registered = set(Base.registry.mappers)
tables = dict(Base.metadata.tables)
assert 'tree_analysis_candidates' in tables
assert 'tree_analyses' in tables
assert 'trees' in tables
for path in Path('app').rglob('*.py'):
    if path.name != 'models.py' and path.as_posix() != 'app/common/db/outbox.py':
        continue
    module = importlib.import_module('.'.join(path.with_suffix('').parts))
    for value in vars(module).values():
        if not isinstance(value, type):
            continue
        mapper = inspect(value, raiseerr=False)
        if mapper is None or not hasattr(mapper, 'local_table'):
            continue
        assert issubclass(value, Base), value
        assert mapper.registry is Base.registry, value
        assert mapper.local_table.metadata is Base.metadata, value
        assert mapper in registered, f'Model missing from registry: {{value}}'
        assert tables[mapper.local_table.key] is mapper.local_table

Base.registry.configure()
for table in tables.values():
    for fk in table.foreign_keys:
        assert fk.column.table is tables[fk.column.table.key]
"""],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

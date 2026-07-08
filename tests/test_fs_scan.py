"""fs_scan — varredura compartilhada por indexação e exploração de contexto."""

from __future__ import annotations

from pathlib import Path

from core.fs_scan import iter_project_files
from core.settings import IndexingSettings


def _rels(root: Path, cfg: IndexingSettings, include_all: bool = False) -> set[str]:
    return {p.relative_to(root).as_posix() for p in iter_project_files(root, cfg, include_all)}


def test_include_all_bypasses_extension_filter(tmp_path: Path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "README").write_text("sem extensão")  # não bate em cfg.include
    cfg = IndexingSettings(include=["*.py"])
    assert _rels(tmp_path, cfg, include_all=False) == {"a.py"}
    assert _rels(tmp_path, cfg, include_all=True) == {"a.py", "README"}


def test_gitignore_is_respected_with_include_all(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("segredo.txt\n")
    (tmp_path / "segredo.txt").write_text("não deve aparecer")
    (tmp_path / "publico.txt").write_text("ok")
    cfg = IndexingSettings()
    assert "segredo.txt" not in _rels(tmp_path, cfg, include_all=True)
    assert "publico.txt" in _rels(tmp_path, cfg, include_all=True)


def test_extra_ignores_directory_is_skipped(tmp_path: Path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lixo.py").write_text("x")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x")
    cfg = IndexingSettings()
    rels = _rels(tmp_path, cfg, include_all=True)
    assert "src/app.py" in rels
    assert not any(r.startswith("node_modules/") for r in rels)

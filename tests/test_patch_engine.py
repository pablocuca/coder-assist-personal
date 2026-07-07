import pytest

from core.errors import PatchError
from core.patch_engine import (
    apply_search_replace,
    atomic_write,
    check_replace_file_allowed,
)


def test_single_match_applies():
    content = "def foo():\n    return 1\n"
    result = apply_search_replace(content, "return 1", "return 2")
    assert result == "def foo():\n    return 2\n"


def test_zero_matches_raises():
    with pytest.raises(PatchError, match="não encontrado"):
        apply_search_replace("abc", "xyz", "123")


def test_multiple_matches_raises():
    with pytest.raises(PatchError, match="ambíguo"):
        apply_search_replace("x = 1\nx = 1\n", "x = 1", "x = 2")


def test_replaces_only_once():
    # match único exigido, mas replace usa count=1 por segurança
    result = apply_search_replace("aba", "b", "c")
    assert result == "aca"


def test_replace_file_allowed_for_new_file():
    check_replace_file_allowed("", is_new_file=True)  # não levanta


def test_replace_file_allowed_for_small_file():
    check_replace_file_allowed("linha\n" * 50, is_new_file=False)  # não levanta


def test_replace_file_rejected_for_big_file():
    with pytest.raises(PatchError, match="replace_file"):
        check_replace_file_allowed("linha\n" * 200, is_new_file=False)


def test_atomic_write_creates_file(tmp_path):
    target = tmp_path / "novo.txt"
    atomic_write(target, "conteúdo")
    assert target.read_text(encoding="utf-8") == "conteúdo"


def test_atomic_write_overwrites(tmp_path):
    target = tmp_path / "arquivo.txt"
    target.write_text("antigo")
    atomic_write(target, "novo")
    assert target.read_text() == "novo"


def test_atomic_write_interrupted_keeps_original(tmp_path, monkeypatch):
    """Simula interrupção durante o os.replace: original intacto, sem lixo .tmp."""
    target = tmp_path / "arquivo.txt"
    target.write_text("original intacto")

    def boom(src, dst):
        raise OSError("interrompido no meio da gravação")

    monkeypatch.setattr("core.patch_engine.os.replace", boom)
    with pytest.raises(OSError):
        atomic_write(target, "conteúdo novo")

    assert target.read_text() == "original intacto"
    assert list(tmp_path.glob("*.tmp")) == []

"""Aplicação de propostas multi-arquivo (V2) — função pura, sem disco nem UI."""

from pathlib import Path

from core.agent import TargetFile, apply_proposal, _sha256
from models.schemas import EditProposal


def _target(rel: str, original: str, is_new: bool = False) -> TargetFile:
    return TargetFile(
        rel=rel,
        path=Path("/fake") / rel,
        original=original,
        original_hash=_sha256(original),
        is_new=is_new,
    )


def _proposal(edits: list[dict]) -> EditProposal:
    return EditProposal(confidence=0.8, explanation="multi", edits=edits)


def test_edits_grouped_and_applied_per_file():
    targets = {
        "a.py": _target("a.py", "x = 1\ny = 2\n"),
        "b.py": _target("b.py", "z = 3\n"),
    }
    proposal = _proposal(
        [
            {"file": "a.py", "search": "x = 1", "replace": "x = 10"},
            {"file": "b.py", "search": "z = 3", "replace": "z = 30"},
            {"file": "a.py", "search": "y = 2", "replace": "y = 20"},
        ]
    )
    changed, failed = apply_proposal(targets, proposal)
    assert set(changed) == {"a.py", "b.py"}
    assert failed == []
    assert targets["a.py"].updated == "x = 10\ny = 20\n"  # edits sequenciais no mesmo arquivo
    assert targets["b.py"].updated == "z = 30\n"


def test_new_file_via_replace_file():
    targets = {
        "app.py": _target("app.py", "def soma(a, b):\n    return a - b\n"),
        "test_app.py": _target("test_app.py", "", is_new=True),
    }
    proposal = _proposal(
        [
            {"file": "app.py", "search": "a - b", "replace": "a + b"},
            {"file": "test_app.py", "replace_file": "def test_soma():\n    assert True\n"},
        ]
    )
    changed, failed = apply_proposal(targets, proposal)
    assert set(changed) == {"app.py", "test_app.py"}
    assert failed == []
    assert "assert True" in targets["test_app.py"].updated


def test_failure_in_one_file_does_not_block_others():
    targets = {
        "bom.py": _target("bom.py", "ok = 1\n"),
        "ruim.py": _target("ruim.py", "conteudo real\n"),
    }
    proposal = _proposal(
        [
            {"file": "bom.py", "search": "ok = 1", "replace": "ok = 2"},
            {"file": "ruim.py", "search": "nao existe", "replace": "x"},
        ]
    )
    changed, failed = apply_proposal(targets, proposal)
    assert changed == ["bom.py"]
    assert len(failed) == 1
    assert failed[0][0] == "ruim.py"
    assert targets["ruim.py"].updated is None


def test_failed_file_skips_subsequent_edits():
    targets = {"a.py": _target("a.py", "um\ndois\n")}
    proposal = _proposal(
        [
            {"file": "a.py", "search": "inexistente", "replace": "x"},
            {"file": "a.py", "search": "um", "replace": "1"},  # não deve aplicar
        ]
    )
    changed, failed = apply_proposal(targets, proposal)
    assert changed == []
    assert len(failed) == 1


def test_path_normalization_matches():
    targets = {"src/app.py": _target("src/app.py", "v = 1\n")}
    proposal = _proposal([{"file": "./src/app.py", "search": "v = 1", "replace": "v = 2"}])
    changed, failed = apply_proposal(targets, proposal)
    assert changed == ["src/app.py"]
    assert failed == []

import pytest

from core.errors import PathGuardError
from security.path_guard import validate_path


@pytest.fixture
def root(tmp_path):
    project = tmp_path / "projeto"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("x = 1\n")
    return project


def test_valid_relative_path(root):
    resolved = validate_path(root, "src/app.py")
    assert resolved == (root / "src" / "app.py").resolve()


def test_valid_new_file_path(root):
    resolved = validate_path(root, "src/novo.py")
    assert resolved.parent == (root / "src").resolve()


def test_traversal_rejected(root):
    with pytest.raises(PathGuardError):
        validate_path(root, "../fora.txt")


def test_deep_traversal_rejected(root):
    with pytest.raises(PathGuardError):
        validate_path(root, "src/../../..//etc/passwd")


def test_absolute_external_rejected(root):
    with pytest.raises(PathGuardError):
        validate_path(root, "/etc/passwd")


def test_root_itself_rejected(root):
    with pytest.raises(PathGuardError):
        validate_path(root, ".")


def test_symlink_to_outside_rejected(root, tmp_path):
    outside = tmp_path / "fora.txt"
    outside.write_text("segredo")
    link = root / "link.txt"
    link.symlink_to(outside)
    with pytest.raises(PathGuardError):
        validate_path(root, "link.txt")


def test_symlinked_dir_to_outside_rejected(root, tmp_path):
    outside_dir = tmp_path / "fora_dir"
    outside_dir.mkdir()
    (outside_dir / "alvo.txt").write_text("x")
    link = root / "dirlink"
    link.symlink_to(outside_dir)
    with pytest.raises(PathGuardError):
        validate_path(root, "dirlink/alvo.txt")

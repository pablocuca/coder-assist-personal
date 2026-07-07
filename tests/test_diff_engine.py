from core.diff_engine import unified_diff


def test_addition():
    diff = unified_diff("linha1\n", "linha1\nlinha2\n", "arquivo.py")
    assert "+linha2" in diff
    assert "-linha1" not in diff


def test_removal():
    diff = unified_diff("linha1\nlinha2\n", "linha1\n", "arquivo.py")
    assert "-linha2" in diff
    assert "+linha2" not in diff


def test_new_file():
    diff = unified_diff("", "conteudo novo\n", "novo.py")
    assert "+conteudo novo" in diff
    assert "--- a/novo.py" in diff
    assert "+++ b/novo.py" in diff


def test_empty_to_empty():
    assert unified_diff("", "", "vazio.py") == ""


def test_no_changes():
    assert unified_diff("igual\n", "igual\n", "x.py") == ""


def test_emptying_file():
    diff = unified_diff("tudo\n", "", "x.py")
    assert "-tudo" in diff

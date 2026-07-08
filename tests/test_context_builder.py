"""build_edit_prompt — inclusão do arquivo alvo e, com --explore, de referências."""

from __future__ import annotations

from core.context_builder import build_edit_prompt


def test_new_file_has_no_content_section():
    prompt = build_edit_prompt("novo.py", "", "cria a função soma", is_new=True)
    assert "ainda não existe" in prompt
    assert "cria a função soma" in prompt


def test_existing_file_includes_content():
    prompt = build_edit_prompt("app.py", "x = 1\n", "muda x para 2", is_new=False)
    assert "alvo principal — edite este" in prompt
    assert "x = 1" in prompt


def test_related_files_are_labeled_as_reference_only():
    prompt = build_edit_prompt(
        "controller.py",
        "class Controller: ...\n",
        "adiciona endpoint de pagamento",
        is_new=False,
        related={"services/payment.py": "class PaymentService: ...\n"},
    )
    assert "Arquivos relacionados encontrados na exploração" in prompt
    assert "services/payment.py" in prompt
    assert "PaymentService" in prompt
    assert "o alvo principal é `controller.py`" in prompt


def test_no_related_section_when_related_is_empty():
    prompt = build_edit_prompt("app.py", "x = 1\n", "muda x", is_new=False, related=None)
    assert "Arquivos relacionados" not in prompt

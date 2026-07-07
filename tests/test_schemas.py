import json

import pytest
from pydantic import ValidationError

from core.errors import ParseError
from models.schemas import EditProposal, SearchReplaceEdit, parse_edit_proposal

VALID = {
    "confidence": 0.82,
    "explanation": "Troca X por Y",
    "edits": [{"file": "app.py", "search": "x = 1", "replace": "x = 2"}],
}


def test_parse_raw_json():
    proposal = parse_edit_proposal(json.dumps(VALID))
    assert proposal.confidence == 0.82
    assert proposal.edits[0].search == "x = 1"


def test_parse_json_in_fence():
    text = f"Claro! Aqui está a edição:\n```json\n{json.dumps(VALID)}\n```\nEspero que ajude."
    proposal = parse_edit_proposal(text)
    assert proposal.explanation == "Troca X por Y"


def test_parse_json_in_plain_fence():
    text = f"```\n{json.dumps(VALID)}\n```"
    assert parse_edit_proposal(text).confidence == 0.82


def test_parse_json_embedded_in_prose():
    text = f"resposta: {json.dumps(VALID)} fim."
    assert parse_edit_proposal(text).confidence == 0.82


def test_invalid_text_raises_parse_error():
    with pytest.raises(ParseError):
        parse_edit_proposal("desculpe, não consigo ajudar com isso")


def test_valid_json_wrong_schema_raises():
    with pytest.raises(ParseError):
        parse_edit_proposal('{"foo": "bar"}')


def test_confidence_out_of_range_rejected():
    bad = dict(VALID, confidence=1.5)
    with pytest.raises(ParseError):
        parse_edit_proposal(json.dumps(bad))


def test_empty_edits_rejected():
    bad = dict(VALID, edits=[])
    with pytest.raises(ParseError):
        parse_edit_proposal(json.dumps(bad))


def test_replace_file_mode():
    edit = SearchReplaceEdit(file="novo.py", replace_file="print('oi')\n")
    assert edit.replace_file is not None


def test_edit_needs_search_and_replace_or_replace_file():
    with pytest.raises(ValidationError):
        SearchReplaceEdit(file="a.py", search="x")  # falta replace
    with pytest.raises(ValidationError):
        SearchReplaceEdit(file="a.py")  # falta tudo


def test_edit_cannot_mix_modes():
    with pytest.raises(ValidationError):
        SearchReplaceEdit(file="a.py", search="x", replace="y", replace_file="z")


def test_empty_search_rejected():
    with pytest.raises(ValidationError):
        SearchReplaceEdit(file="a.py", search="", replace="y")

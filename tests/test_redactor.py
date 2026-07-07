from security.redactor import redact

SECRETS = [
    'api_key = "placeholder-value"',
    "password: placeholder-value",
    "access_token = placeholder-value",
]


def test_known_keys_never_appear():
    for secret in SECRETS:
        output = redact(f"contexto com {secret} no meio")
        assert secret not in output, f"segredo vazou: {secret}"
        assert "[REDACTED:" in output


def test_credential_assignment():
    output = redact('api_key = "supersegredo12345"')
    assert "supersegredo12345" not in output


def test_password_assignment():
    output = redact("password: minhasenhasecreta")
    assert "minhasenhasecreta" not in output


def test_aws_secret_env():
    output = redact("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    assert "wJalrXUtnFEMI" not in output


def test_bearer_token():
    output = redact("Authorization: Bearer abcdef1234567890abcdef")
    assert "abcdef1234567890abcdef" not in output


def test_jwt():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.abc123def456"
    assert jwt not in redact(f"token: {jwt}")


def test_normal_text_untouched():
    text = "def calcular_total(itens):\n    return sum(itens)\n"
    assert redact(text) == text


def test_none_and_empty():
    assert redact(None) is None
    assert redact("") == ""

"""Ponto de entrada do Coder Assist Personal.

`[project.scripts] coder-dev = "main:app"` registra o comando `coder-dev`
apontando para o objeto Typer abaixo.
"""

from cli.commands import app

if __name__ == "__main__":
    app()

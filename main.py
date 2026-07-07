"""Ponto de entrada do Aider Pessoal.

`[project.scripts] aider = "main:app"` registra o comando `aider` apontando
para o objeto Typer abaixo.
"""

from cli.commands import app

if __name__ == "__main__":
    app()

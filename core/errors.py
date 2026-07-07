"""Hierarquia de exceções do domínio.

Toda falha interna deve derivar de CoderAssistError para que a CLI possa
exibi-la de forma amigável e registrá-la no histórico — nunca um
traceback cru para o usuário (princípio 5: falhar com segurança).
"""


class CoderAssistError(Exception):
    """Erro base do Coder Assist Personal."""


class ConfigError(CoderAssistError):
    """Configuração ausente ou inválida (settings.yaml)."""


class PathGuardError(CoderAssistError):
    """Path fora da raiz do projeto ou traversal detectado."""


class ParseError(CoderAssistError):
    """Resposta do modelo não pôde ser interpretada como EditProposal."""


class PatchError(CoderAssistError):
    """Bloco search não encontrado, ambíguo, ou aplicação inválida."""


class ProviderError(CoderAssistError):
    """Falha de comunicação com um provider (Ollama/Claude)."""


class FileChangedError(CoderAssistError):
    """Arquivo alvo mudou entre a leitura e a gravação."""


class VectorStoreError(CoderAssistError):
    """ChromaDB indisponível ou corrompido — a edição degrada sem memória (seção 19)."""


class GitError(CoderAssistError):
    """Operação Git falhou ou repositório ausente onde era necessário."""

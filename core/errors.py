"""Hierarquia de exceções do domínio.

Toda falha interna deve derivar de AiderError para que a CLI possa
exibi-la de forma amigável e registrá-la no histórico — nunca um
traceback cru para o usuário (princípio 5: falhar com segurança).
"""


class AiderError(Exception):
    """Erro base do Aider Pessoal."""


class ConfigError(AiderError):
    """Configuração ausente ou inválida (settings.yaml)."""


class PathGuardError(AiderError):
    """Path fora da raiz do projeto ou traversal detectado."""


class ParseError(AiderError):
    """Resposta do modelo não pôde ser interpretada como EditProposal."""


class PatchError(AiderError):
    """Bloco search não encontrado, ambíguo, ou aplicação inválida."""


class ProviderError(AiderError):
    """Falha de comunicação com um provider (Ollama/Claude)."""


class FileChangedError(AiderError):
    """Arquivo alvo mudou entre a leitura e a gravação."""


class VectorStoreError(AiderError):
    """ChromaDB indisponível ou corrompido — a edição degrada sem memória (seção 19)."""


class GitError(AiderError):
    """Operação Git falhou ou repositório ausente onde era necessário."""

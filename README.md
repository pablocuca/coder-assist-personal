# Aider Pessoal

CLI de edição de código assistida por IA — local-first, com aprovação obrigatória
antes de qualquer gravação e trilha de auditoria completa em SQLite.

**Status: V2 concluída** (roadmap da especificação: MVP → V1 → V2 ✓).

## Princípios

1. A IA nunca grava diretamente: proposta → diff → aprovação → backup → gravação atômica.
2. Toda chamada a modelos passa pelo Router, que registra 100% das interações.
3. Nenhuma escrita fora da raiz do projeto (path guard com resolução de symlinks).
4. Segredos são redigidos antes de qualquer persistência (log ou banco).
5. Falhar com segurança: erro em qualquer etapa aborta sem tocar nos arquivos.
6. Offline-first: funciona 100% sem internet com Ollama.

## Instalação

Pré-requisitos: Python 3.12+, [Ollama](https://ollama.com) rodando localmente
com o modelo configurado (`ollama pull gpt-oss:20b`).

```bash
cd ~/dev/personal-aider        # ou onde estiver o repo
pipx install -e .              # recomendado (isola dependências)
# alternativa: python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

O estado em runtime (banco, backups, logs) fica em `~/.personal-aider/`,
separado do código-fonte. Overrides locais de configuração:
`~/.personal-aider/config/settings.yaml` (ou `coder-dev config --set chave=valor`).

## Uso

```bash
cd ~/dev/meu-projeto
coder-dev index .         # indexa o projeto no banco vetorial (incremental; --full re-indexa)
coder-dev edit lib/home_page.dart -m "converte para ConsumerWidget"
coder-dev edit lib/service.dart -m "refatora" --plan          # plano em passos antes de editar
coder-dev edit lib/complexo.dart -m "..." --provider claude   # escala direto (confirma custo)
coder-dev ask "por que essa tela usa Provider?"
coder-dev recall "bug de login google" -k 5      # busca híbrida (vetorial+FTS5) com fontes
coder-dev recall "por que migramos?" --synthesize
coder-dev recall --tag auth
coder-dev decision "Adotamos Riverpod em vez de Provider" --tag architecture
coder-dev stats --since 30d
coder-dev commit          # mensagem sugerida pela IA, editável — nunca automática
coder-dev history -n 20
coder-dev undo            # restaura o backup da última edição (com diff + confirmação)
coder-dev undo --list
coder-dev tag 42 auth
coder-dev config --show
```

Escalada para Claude: o Router recomenda quando a confiança fica abaixo do
limiar, o contexto excede a janela do modelo local ou há duas falhas de parse
seguidas — sempre exibindo estimativa de custo e pedindo confirmação (teto
rígido via `--max-budget-usd`). Autenticação é do próprio Claude Code
(`claude login`); a ferramenta nunca manipula API keys.

## Testes

```bash
pytest
```

## Roadmap

- **MVP (feito)**: edit/ask/history/undo/config, Ollama + Router com registro
  completo, SQLite (schema seção 11), search/replace com validação e
  re-tentativa de parse, diff + aprovação + backup + escrita atômica,
  path guard, redactor, testes.
- **V1 (feito)**: ChromaDB + embeddings (`nomic-embed-text`, fallback opcional
  sentence-transformers), chunking com fronteiras de função e invalidação por
  hash, `coder-dev index .` incremental respeitando `.gitignore` real (pathspec),
  FTS5 sincronizado por triggers (degradação do recall), `recall` vetorial com
  proveniência obrigatória, `recall --tag`, `stats`, `coder-dev commit` assistido
  com registro na tabela `commits`, interações indexadas em best-effort.
- **V2 (feito)**: provider Claude via Claude Code CLI (`claude -p` headless,
  prompt via stdin, cwd neutro, sem ferramentas, `--max-turns 1`,
  `--max-budget-usd`, custo real do `total_cost_usd`, flags validadas contra
  `--help`), política de roteamento completa (confiança, janela de contexto,
  falhas de parse, task complexo) com estimativa e confirmação de custo,
  busca híbrida RRF + `recall --synthesize` com fontes citadas, edição
  multi-arquivo com aprovação individual ou em lote, documentos de decisão
  (`coder-dev decision`), planejamento (`coder-dev edit --plan`), provider Claude
  testado com binário mockado.

Melhorias opcionais não implementadas (listadas como tal na spec):
tree-sitter para chunking, Knowledge Graph, streaming.

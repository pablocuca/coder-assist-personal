# Aider Pessoal

CLI de edição de código assistida por IA — local-first, com aprovação obrigatória
antes de qualquer gravação e trilha de auditoria completa em SQLite.

**Status: V1 concluída** (roadmap da especificação: MVP → V1 → V2).

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
`~/.personal-aider/config/settings.yaml` (ou `aider config --set chave=valor`).

## Uso

```bash
cd ~/dev/meu-projeto
aider index .         # indexa o projeto no banco vetorial (incremental; --full re-indexa)
aider edit lib/home_page.dart -m "converte para ConsumerWidget"
aider ask "por que essa tela usa Provider?"
aider recall "bug de login google" -k 5      # busca semântica com fontes
aider recall --tag auth
aider stats --since 30d
aider commit          # mensagem sugerida pela IA, editável — nunca automática
aider history -n 20
aider undo            # restaura o backup da última edição (com diff + confirmação)
aider undo --list
aider tag 42 auth
aider config --show
```

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
  hash, `aider index .` incremental respeitando `.gitignore` real (pathspec),
  FTS5 sincronizado por triggers (degradação do recall), `recall` vetorial com
  proveniência obrigatória, `recall --tag`, `stats`, `aider commit` assistido
  com registro na tabela `commits`, interações indexadas em best-effort.
- **V2**: provider Claude via Claude Code CLI (`claude -p` headless, cwd neutro,
  sem ferramentas, `--max-budget-usd`), política de roteamento completa com
  confirmação de custo, busca híbrida (RRF), `recall --synthesize`, edição
  multi-arquivo, planejamento de tarefas.

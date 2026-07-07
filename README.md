# Coder Assist Personal

🇧🇷 Português | 🇺🇸 [English](README.en.md)

CLI de edição de código assistida por IA — local-first, com aprovação obrigatória
antes de qualquer gravação e trilha de auditoria completa em SQLite.

O comando instalado chama-se **`coder-dev`** e funciona de dentro de qualquer
projeto: ele detecta a raiz do projeto automaticamente (pelo `.git` ou pasta
atual) e mantém histórico, memória e backups separados por projeto.

**Status: V2 concluída** (roadmap da especificação: MVP → V1 → V2 ✓).

## Princípios

1. A IA nunca grava diretamente: proposta → diff → aprovação → backup → gravação atômica.
2. Toda chamada a modelos passa pelo Router, que registra 100% das interações.
3. Nenhuma escrita fora da raiz do projeto (path guard com resolução de symlinks).
4. Segredos são redigidos antes de qualquer persistência (log ou banco).
5. Falhar com segurança: erro em qualquer etapa aborta sem tocar nos arquivos.
6. Offline-first: funciona 100% sem internet com Ollama.

## Instalação

Pré-requisitos:

- **Python 3.12+**
- **[Ollama](https://ollama.com)** rodando localmente com o modelo configurado:
  `ollama pull gpt-oss:20b` (e `ollama pull nomic-embed-text` para a memória vetorial)
- Opcional: **Claude Code CLI** autenticado (`claude login`) para escalar tarefas
  complexas — veja a seção [Usando o Claude](#usando-o-claude)

```bash
cd ~/dev/coder-assist-personal  # ou onde estiver o repo
pipx install --editable .       # recomendado (isola dependências)
# alternativa: python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

O `--editable` faz com que alterações no código-fonte valham imediatamente,
sem reinstalar. Se o comando `coder-dev` não for encontrado após a instalação,
garanta que `~/.local/bin` está no PATH:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

Verifique a instalação:

```bash
coder-dev --help
```

### Onde ficam os dados

O estado em runtime fica em **`~/.coder-assist-personal/`**, separado do
código-fonte e compartilhado entre todos os projetos:

| Pasta                | Conteúdo                                                        |
| -------------------- | --------------------------------------------------------------- |
| `db/`                | Banco SQLite (histórico, decisões, tags, commits) e índice vetorial |
| `backups/<projeto>/` | Backups usados pelo `undo`, um por edição gravada               |
| `logs/`              | Logs em JSON com segredos redigidos (`coder-assist.log`)        |
| `config/`            | `settings.yaml` com seus overrides locais (não versionado)     |

## Guia de comandos

Todos os comandos são executados de dentro da pasta do projeto em que você
está trabalhando (`cd ~/dev/meu-projeto`).

### `coder-dev index` — indexar o projeto na memória vetorial

Varre os arquivos do projeto, divide em chunks respeitando fronteiras de
função e grava embeddings no banco vetorial (ChromaDB). É o que alimenta o
`recall` e o contexto das edições. Respeita o `.gitignore` real do projeto e
pula binários.

```bash
coder-dev index .          # incremental: só re-indexa arquivos que mudaram (hash)
coder-dev index . --full   # força re-indexação completa (ex.: após trocar o modelo de embeddings)
```

**Quando usar:** na primeira vez em cada projeto e depois de mudanças grandes.
O modo incremental é barato — pode rodar com frequência.

### `coder-dev edit` — editar um arquivo com IA

O coração da ferramenta. A IA propõe a mudança, você vê o **diff por arquivo**
e aprova (ou rejeita) antes de qualquer gravação. Toda edição aprovada gera
backup automático antes de gravar (escrita atômica).

```bash
coder-dev edit lib/home_page.dart -m "converte para ConsumerWidget"
coder-dev edit lib/service.dart -m "refatora" --plan        # mostra plano em passos antes de editar
coder-dev edit lib/complexo.dart -m "..." --provider claude # escala direto para o Claude (confirma custo)
```

| Opção            | Efeito                                                          |
| ---------------- | --------------------------------------------------------------- |
| `-m, --message`  | Instrução de edição (sem ela, a CLI pergunta interativamente)   |
| `--plan`         | A IA apresenta um plano em passos para aprovação antes de propor o diff |
| `--provider`     | Força `ollama` (local, padrão) ou `claude` (pago, pede confirmação de custo) |

**Quando usar:** qualquer mudança de código. Edições que tocam múltiplos
arquivos mostram um diff por arquivo, com aprovação individual ou em lote.

### `coder-dev ask` — perguntar sem editar nada

Chat livre com contexto do projeto. **Nunca grava em arquivos** — é seguro
para explorar. Tudo fica registrado no histórico e vira memória consultável
pelo `recall`.

```bash
coder-dev ask "por que essa tela usa Provider?"
coder-dev ask "qual o fluxo de autenticação?" --provider claude
```

**Quando usar:** entender código, discutir abordagens, tirar dúvidas de
arquitetura antes de editar.

### `coder-dev recall` — buscar no conhecimento acumulado

Busca híbrida (vetorial + palavra-chave FTS5, fusão RRF) sobre tudo que a
ferramenta já viu: código indexado, interações passadas e decisões
registradas. Sempre mostra as **fontes** de cada resultado. Se o banco
vetorial estiver indisponível, degrada automaticamente para busca por
palavra-chave.

```bash
coder-dev recall "bug de login google" -k 5    # top 5 resultados com fontes
coder-dev recall "por que migramos?" --synthesize  # resposta consolidada pela IA, citando fontes
coder-dev recall --tag auth                    # lista interações marcadas com a tag
```

| Opção           | Efeito                                                    |
| --------------- | ---------------------------------------------------------- |
| `-k`            | Quantidade de resultados (padrão: 5)                       |
| `--synthesize`  | A IA consolida os resultados numa resposta única, com fontes |
| `--tag`         | Em vez de buscar, lista as interações com a tag informada  |

**Quando usar:** "onde mexemos nisso?", "por que decidimos assim?", retomar
contexto depois de semanas longe do projeto.

### `coder-dev decision` — registrar uma decisão de arquitetura

Grava um documento de decisão na memória (uma decisão por documento),
recuperável depois via `recall`. É o "diário de bordo" do projeto.

```bash
coder-dev decision "Adotamos Riverpod em vez de Provider" --tag architecture
coder-dev decision "API de pagamentos será síncrona no MVP" --tag payments --tag mvp
```

A opção `--tag` é repetível. **Quando usar:** sempre que fechar uma decisão
que o "você do futuro" vai querer entender.

### `coder-dev history` — ver o histórico de interações

Lista as interações registradas pelo Router (edits, asks, commits…), com ID,
data, provider e resumo.

```bash
coder-dev history            # últimas 20
coder-dev history -n 50      # últimas 50
coder-dev history --tag auth # filtradas por tag
coder-dev history --project meu-projeto
```

### `coder-dev tag` — marcar uma interação

Aplica uma tag livre (criada sob demanda) a uma interação do histórico, para
filtrar depois em `history --tag` e `recall --tag`.

```bash
coder-dev history          # descubra o ID da interação
coder-dev tag 42 auth      # marca a interação #42 com a tag "auth"
```

### `coder-dev undo` — desfazer a última edição

Restaura o backup da última edição gravada, mostrando o diff do que será
restaurado e pedindo confirmação. Os backups formam uma pilha por projeto
(retenção configurável, padrão 20).

```bash
coder-dev undo          # restaura o backup mais recente (com diff + confirmação)
coder-dev undo --list   # mostra a pilha de backups disponíveis
```

**Quando usar:** aprovou uma edição e se arrependeu. Como todo `edit` gera
backup antes de gravar, o undo sempre tem para onde voltar.

### `coder-dev stats` — observabilidade de uso

Totais de interações, uso por provider (quanto ficou no Ollama vs. escalou
para o Claude), taxas de rejeição/escalada e arquivos mais editados.

```bash
coder-dev stats                  # tudo, desde o início
coder-dev stats --since 30d     # últimos 30 dias (aceita d, w, h — ex.: 2w, 12h)
coder-dev stats --project meu-projeto
```

### `coder-dev commit` — commit assistido

Gera uma **sugestão** de mensagem de commit a partir do diff em stage — você
edita e confirma; nunca é automático e **nunca faz push**. Se não houver nada
em stage, oferece `git add -A` (com confirmação). O commit é registrado no
histórico da ferramenta.

```bash
git add -p          # opcional: escolha o que commitar
coder-dev commit    # sugere a mensagem, você edita e confirma
```

### `coder-dev config` — ver e ajustar a configuração

Exibe a configuração efetiva (defaults do repo + seus overrides) ou grava um
override local em `~/.coder-assist-personal/config/settings.yaml`.

```bash
coder-dev config --show
coder-dev config --set providers.ollama.model=llama3
coder-dev config --set providers.claude.max_budget_usd=1.00
coder-dev config --set router.confidence_threshold=0.70
```

A chave usa notação pontuada (`secao.subsecao.chave=valor`) e o valor é
interpretado como YAML (números, booleanos e strings funcionam naturalmente).
A configuração é revalidada na hora — um valor inválido é rejeitado com erro
claro.

## Usando o Claude

Por padrão tudo roda no **Ollama** (local e gratuito). O Claude é o provider
"de reforço" para tarefas que o modelo local não dá conta — e seu uso é
sempre **pago, explícito e confirmado**.

### Configuração inicial (uma vez)

1. Instale o [Claude Code CLI](https://claude.com/claude-code):

   ```bash
   npm install -g @anthropic-ai/claude-code
   ```

2. Autentique com sua conta:

   ```bash
   claude login
   ```

3. Verifique:

   ```bash
   claude --version
   ```

A autenticação é do próprio Claude Code — a ferramenta **nunca manipula API
keys**; ela apenas invoca o binário `claude` já autenticado.

### As duas formas de usar

**1. Forçar o Claude em um comando** — quando você já sabe que a tarefa é
complexa:

```bash
coder-dev edit lib/complexo.dart -m "refatora o fluxo de pagamento" --provider claude
coder-dev ask "explique a arquitetura de sincronização offline" --provider claude
```

**2. Escalada recomendada pelo Router** — no fluxo normal (sem `--provider`),
o Router monitora a resposta do modelo local e **recomenda** escalar quando:

- a confiança da resposta fica abaixo do limiar (`router.confidence_threshold`, padrão 0.60);
- o contexto excede a janela do modelo local (`providers.ollama.context_window_tokens`);
- há duas falhas seguidas de interpretação da resposta (parse).

Nos dois casos o comportamento é o mesmo: antes de chamar o Claude, a
ferramenta exibe a **estimativa de custo em USD e pede sua confirmação**.
Nada é cobrado sem você aprovar. O custo real da chamada (informado pelo
próprio Claude Code) fica registrado no histórico — veja o acumulado com
`coder-dev stats`.

### Controle de custo e configuração

| Chave                                  | Padrão              | Efeito                                              |
| -------------------------------------- | ------------------- | --------------------------------------------------- |
| `providers.claude.max_budget_usd`      | `0.50`              | Teto rígido por chamada — o Claude Code aborta se exceder |
| `providers.claude.model`               | `claude-sonnet-4-6` | Modelo usado nas escaladas                          |
| `providers.claude.timeout_seconds`     | `300`               | Timeout da chamada                                  |
| `router.confidence_threshold`          | `0.60`              | Abaixo disso, o Router recomenda escalar            |
| `router.confirm_cost_before_claude`    | `true`              | Pede confirmação de custo antes de cada chamada     |

```bash
coder-dev config --set providers.claude.max_budget_usd=1.00
coder-dev config --set providers.claude.model=claude-sonnet-4-6
```

### Segurança

A chamada é headless e isolada: prompt via stdin, **sem ferramentas**, uma
única rodada (`--max-turns 1`) e diretório de trabalho neutro — o Claude
**não lê nem edita seu projeto diretamente**; ele só vê o contexto que a
ferramenta coloca no prompt, e toda edição proposta passa pelo mesmo fluxo
de diff + aprovação + backup de sempre.

## Backup e migração para outra máquina

Todo o estado (histórico, decisões, memória vetorial, backups de undo e
configuração) vive em um único diretório: `~/.coder-assist-personal/`. Para
levar tudo para outra máquina:

**Na máquina de origem:**

```bash
tar czf coder-assist-backup.tar.gz -C ~ .coder-assist-personal
# copie o arquivo por scp, pendrive, nuvem…
```

**Na máquina de destino:**

```bash
# 1. Instale a ferramenta (seção Instalação)
# 2. Restaure o estado ANTES do primeiro uso:
tar xzf coder-assist-backup.tar.gz -C ~
```

Observações:

- Os caminhos dos projetos ficam registrados no banco; se na máquina nova os
  projetos estiverem em caminhos diferentes, o histórico e as decisões
  continuam acessíveis, mas rode `coder-dev index .` em cada projeto para
  reconstruir o vínculo com a nova localização.
- O índice vetorial depende do modelo de embeddings: garanta o mesmo modelo
  no destino (`ollama pull nomic-embed-text`) ou re-indexe com
  `coder-dev index . --full`.
- Para apenas um backup periódico de segurança, o mesmo `tar` serve —
  o diretório pode ser restaurado por cima (substitui o estado atual).

## Remoção (uninstall)

A remoção tem duas partes independentes — o programa e os dados:

**1. Remover o programa:**

```bash
pipx uninstall coder-assist-personal
# ou, se instalou com pip: pip uninstall coder-assist-personal
```

**2. Remover os dados (opcional e irreversível):**

```bash
rm -rf ~/.coder-assist-personal
```

> **Atenção:** isso apaga o histórico de interações, as decisões registradas,
> a memória vetorial e os backups do `undo` de **todos os projetos**. Se
> houver qualquer chance de querer os dados depois, faça o `tar` da seção de
> backup antes. Seus projetos e repositórios **não são tocados** — a
> ferramenta nunca grava fora de `~/.coder-assist-personal/` e da raiz do
> projeto durante edições aprovadas.

Desinstalar só o programa (passo 1) e manter os dados é seguro: ao
reinstalar, tudo volta a funcionar de onde parou.

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

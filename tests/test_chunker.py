from memory.chunker import CONVERSATION_CHUNK_CHARS, chunk_code, chunk_conversation


def test_small_file_single_chunk():
    content = "def foo():\n    return 1\n"
    chunks = chunk_code(content, max_lines=80, overlap=10)
    assert len(chunks) == 1
    assert chunks[0].start_line == 1


def test_empty_file_no_chunks():
    assert chunk_code("", max_lines=80, overlap=10) == []


def test_large_file_windows_with_overlap():
    lines = [f"linha_{i} = {i}" for i in range(300)]
    chunks = chunk_code("\n".join(lines), max_lines=80, overlap=10)
    assert len(chunks) > 1
    # cobre o arquivo inteiro
    assert chunks[0].start_line == 1
    assert chunks[-1].end_line == 300
    # janelas consecutivas se sobrepõem
    for previous, current in zip(chunks, chunks[1:]):
        assert current.start_line <= previous.end_line
    # nenhuma janela excede o máximo
    for chunk in chunks:
        assert chunk.end_line - chunk.start_line + 1 <= 80


def test_prefers_function_boundary():
    # 60 linhas de corpo, depois uma def na linha 61 — janela de 80 deve cortar
    # imediatamente antes da def em vez de no meio do corpo dela
    lines = [f"    x_{i} = {i}" for i in range(60)]
    lines.append("def segunda_funcao():")
    lines += [f"    y_{i} = {i}" for i in range(60)]
    chunks = chunk_code("\n".join(lines), max_lines=80, overlap=10)
    assert chunks[0].end_line == 60  # corte na fronteira (def está na linha 61)
    assert "def segunda_funcao" in chunks[1].text


def test_conversation_single_document():
    docs = chunk_conversation("pergunta curta", "resposta curta")
    assert len(docs) == 1
    assert "pergunta curta" in docs[0]
    assert "resposta curta" in docs[0]


def test_conversation_split_when_too_long():
    docs = chunk_conversation("p" * CONVERSATION_CHUNK_CHARS, "r" * CONVERSATION_CHUNK_CHARS)
    assert len(docs) >= 2
    assert sum(len(d) for d in docs) >= 2 * CONVERSATION_CHUNK_CHARS

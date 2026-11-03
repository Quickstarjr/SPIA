# SPIA — Registro de Testes da Fase 1

**Data do marco:** 2026-11-02
**Commit de referência:** `2a630df`

## Resultado geral

Comando executado:

~~~bash
./.venv/bin/python -m unittest discover -s tests -v
~~~

Resultado registrado:

~~~text
Ran 100 tests in 0.377s

OK
~~~

**Resultado: 100 testes aprovados, sem falhas.**

A suíte automatizada cobre principalmente o motor de backups e sua integração
com as rotas do servidor e os fluxos do editor.

A segurança do terminal foi submetida a validação manual própria. Ela não deve
ser apresentada como integralmente coberta por estes 100 testes.

## Arquivos de teste registrados

| Arquivo | Escopo principal |
|---|---|
| `tests/test_backup_engine.py` | Ciclo de vida e criação de versões do motor de backups |
| `tests/test_backup_engine_auto_origin.py` | Inferência de origem automática e comportamento em reaberturas |
| `tests/test_backup_engine_bytes.py` | Criação de snapshots a partir de conteúdo em bytes |
| `tests/test_backup_engine_hardening.py` | Proteções de caminhos, links simbólicos, identidade de diretórios e publicação segura |
| `tests/test_backup_engine_manifest.py` | Estrutura, integridade e validação do manifesto |
| `tests/test_backup_engine_read_source.py` | Leitura segura da origem dos arquivos |
| `tests/test_backup_engine_replace.py` | Substituição atômica, conflitos e comportamento diante de falhas de sincronização |
| `tests/test_server_backup_paths.py` | Regras de acesso e proteção da pasta reservada de backups |
| `tests/test_server_file_open_backups.py` | Integração entre abertura de arquivos e criação de backups |
| `tests/test_server_file_save_backups.py` | Integração entre salvamento, backups, conflitos e preservação de versões |

## Áreas verificadas pela suíte

- Criação e deduplicação de versões.
- Concorrência e detecção de versões órfãs.
- Integridade e validação do manifesto.
- Isolamento entre projetos.
- Proteção contra links simbólicos e caminhos inseguros.
- Verificação de identidade de arquivos e diretórios.
- Publicação e substituição atômicas.
- Tratamento de falhas de sincronização.
- Leitura segura da origem.
- Abertura e salvamento integrados ao servidor.
- Detecção de conflitos e preservação de versões concorrentes.
- Restrições de escrita na pasta reservada de backups.

## Observações

Durante a execução foi emitido um aviso de depreciação do Starlette:

~~~text
StarletteDeprecationWarning:
Using httpx with starlette.testclient is deprecated;
install httpx2 instead.
~~~

O aviso não interrompeu a execução nem alterou o resultado: os 100 testes
foram aprovados.

Este registro preserva o resultado observado na execução da Fase 1.
Não representa uma afirmação de que todos os cenários possíveis do SPIA
foram testados ou de que todos os componentes possuem cobertura automatizada.

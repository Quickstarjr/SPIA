# Histórico Técnico do SPIA

Este documento registra marcos técnicos relevantes, decisões de arquitetura,
implementações e validações do SPIA.

## 2026-11-02 — Conclusão da Fase 1

**Commit de referência:** `2a630df`

**Mensagem:** `Complete Phase 1: terminal security, editor integration and backups`

A Fase 1 foi concluída e registrada em um único commit porque seus três blocos
de implementação são tecnicamente relacionados e compartilham arquivos e
fluxos funcionais.

### Sequência de implementação

#### 1. Segurança do terminal

Primeiro bloco, validado por testes manuais.

A validação deste bloco foi realizada manualmente. Os 100 testes automatizados
da Fase 1 não representam cobertura automatizada integral da segurança
do terminal.

#### 2. Integração de abertura e salvamento do editor

Segundo bloco.

Foram tratados os fluxos de abertura e gravação de arquivos, contratos
estruturados de resposta e erros, detecção de conflitos e preservação das
versões envolvidas em situações de concorrência.

#### 3. Sistema de backups

Terceiro bloco.

Foi implementado o motor de backups integrado aos fluxos do servidor e do
editor, incluindo versionamento, manifesto, integridade, isolamento por
projeto e mecanismos de proteção contra operações inseguras.

A pasta `backups/` dentro de cada projeto é reservada ao sistema:

- Os arquivos de backup podem ser consultados em modo somente leitura.
- A gravação nessa área é bloqueada pelo servidor.
- A criação de arquivos ou diretórios dentro da área reservada é bloqueada.
- O conteúdo de backups não é servido pelos fluxos de preview e imagem.
- Uma pasta chamada `backups` em outro nível, fora da área reservada do
  projeto, continua sendo uma pasta comum.

### Validação

Comando executado:

~~~bash
./.venv/bin/python -m unittest discover -s tests -v
~~~

**Resultado:** 100 testes executados, todos aprovados (`OK`).

A validação manual do terminal e a validação automatizada são evidências
distintas. A relação dos arquivos de teste e seus escopos está em
[FASE_1_TESTES.md](FASE_1_TESTES.md).

### Limitações e itens posteriores

- A interface ainda pode manter o botão de salvar habilitado ao abrir um
  arquivo de backup. A proteção efetiva contra gravação está no backend.
- O gerenciamento de backups pelo Silicon Puppy, incluindo análise de
  relevância e remoção, não faz parte desta entrega.
- Restauração e outras operações futuras de gerenciamento devem ser
  especificadas e validadas em etapa própria.
- Foi observado um aviso de depreciação do Starlette relacionado ao uso de
  `httpx` com `TestClient`. Não impediu a aprovação da suíte.

### Estado do marco

A Fase 1 está concluída e versionada no commit `2a630df`, na branch `main`.

O commit reuniu 14 arquivos, com 5.582 inserções e 280 remoções.

Os arquivos auxiliares e snapshots de recuperação que permaneceram
desversionados após o commit foram preservados. Eles não fazem parte da
entrega versionada da Fase 1.

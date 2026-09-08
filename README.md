project-01-sales-pipeline/
│
├── data/
│   ├──curated
│   │    └── analytics.db
│   ├── source/
│   │    └── source.db
│   ├── raw/
│   │   └── orders/
│   └── state/
│        └──orders_state.json
├── src/
│   ├── check_source.py
│   ├── ingest.py
│   ├── seed_db.py
│   ├── update_source.py
│   ├──
│   ├──
│   └──
└── README.md


FONTE
PostgreSQL transacional
└── read replica disponível

VOLUME
~10–15 mil pedidos/dia
~30–50 mil itens/dia
centenas de MB/dia
picos de 3–5x

MUDANÇAS
pedidos podem mudar posteriormente
cancelamentos/reembolsos existem
updated_at disponível nas principais tabelas

DESTINO
ambiente de dados utilizado por Analytics

FREQUÊNCIA
diária

EXPECTATIVA
dados disponíveis no começo da manhã (~09h)

HISTÓRICO
necessário
'>= 2 anos



QUALIDADE
precisamos detectar falhas técnicas
+
anomalias nos próprios dados

REGRAS DE NEGÓCIO
existem, mas ainda precisam ser formalizadas

RESTRIÇÃO
não sobrecarregar banco transacional

CDC
não existe atualmente

Etapa 1 — Criar o source.db

Etapa 2 — consultar nossa própria origem

Próxima etapa: começa a ingestão

SISTEMA DA APLICAÇÃO                 NOSSO SISTEMA DE DADOS

source.db
   │
   │ SELECT
   ▼
ingest.py
   │
   ▼
data/raw/orders/

Etapa — Watermark + ingestão incremental

                   ┌────────────────────┐
                   │ state.json existe? │
                   └─────────┬──────────┘
                        não  │  sim
                    ┌────────┴─────────┐
                    ▼                  ▼
              SELECT tudo        ler watermark
                                      │
                                      ▼
                             SELECT updated_at > ?
                    │                  │
                    └────────┬─────────┘
                             ▼
                         fetchall()
                             │
                     existem linhas?
                      │             │
                     não           sim
                      │             │
                   encerrar      salvar RAW
                                    │
                                    ▼
                           encontrar MAX(updated_at)
                                    │
                                    ▼
                              salvar state.json



state não existe
    ↓
FULL LOAD
    ↓
grava RAW
    ↓
calcula MAX(updated_at)
    ↓
cria watermark

state existe
    ↓
lê watermark
    ↓
SELECT updated_at > watermark
    ↓
há dados?
 ┌───────┴───────┐
não             sim
 ↓                ↓
encerra        grava RAW
                 ↓
           avança watermark

1ª execução → full load + cria watermark
2ª execução → nenhuma mudança → nada é extraído
alteração na origem → somente registro alterado → watermark avança


                    ┌─ válido ───────→ CURATED
RAW → QUALITY CHECK ┤
                    └─ inválido ─────→ QUARANTINE
                                           ↓
                                     investigar/corrigir


README.md

# Nome do projeto

## Problema de negócio

## Objetivo

## Arquitetura

## Fontes de dados

## Fluxo de dados

## Estratégia de ingestão

    ## Processamento idempotente

            * Idempotencia de um codigo
        FULL REFRESH
            vs.
        INCREMENTAL UPDATE

        o dado serializado precisa ser desserializado e interpretado de acordo com um schema.

        processamento curado idempotente e resistente à chegada fora de ordem de versões antigas
    ## watermark → incremental load → overlap → duplicação → idempotência → upsert.

    Assuntos : data quality, invariantes, observabilidade, reconciliação, freshness, schema validation e incident response.

    distinção importante! 
        Regra de transformação decide como o dado deve ser representado;
        Quality check verifica se propriedades esperadas do dado continuam verdadeiras.

    histórico de detecções na quarentena

    QUARANTINE
    "Quais problemas ainda/efetivamente encontramos nos dados?"
    → investigação e remediação

    QUALITY EVENTS / AUDIT LOG
    "Quantas vezes, quando e em quais execuções detectamos problemas?"
    → observabilidade do pipeline
    Laboratório 1 — Incremental de verdade

    INCIDENTE 01 — Pipeline verde, dado desaparecido
    INCIDENTE 02 — O pipeline recebe um dado ruim
    INCIDENTE 03 — dado que nem conseguimos interpretar

    refatoração: separar parsing, validação e roteamento em funções.
            RAW
             │
             ▼
            Parsing / conversão
             │
             ├── não consegue interpretar
             │      └──→ QUARANTINE
             │
             ▼
            Validação de negócio
             │
             ├── viola regra
             │      └──→ QUARANTINE
             │
             ▼
            UPSERT
             │
             ▼
            CURATED

    INCIDENTE 04 — order_id = "XYZ"

    parsed_order() - Erro tecnico
    validate_order() - Erro de negocio

    
    build_curated.py - Hoje faz :
    │
    ├── define caminhos/configuração
    │
    ├── cria estrutura da quarentena
    │
    ├── parse_order_row()
    │     └── transforma dado bruto em dado tipado
    │
    ├── validate_order()
    │     └── verifica regras de negócio
    │
    └── build_analytics_db()
          ├── recria analytics.db
          ├── cria orders_current
          ├── procura arquivos RAW
          ├── abre os CSVs
          ├── percorre linhas
          ├── chama parser
          ├── chama validator
          ├── decide curated/quarantine
          ├── acumula registros
          ├── faz UPSERT
          ├── grava quarentena
          └── controla commits/conexões


SELECT COUNT(*) + fetchone()
→ espero UMA linha contendo uma contagem

SELECT várias linhas + fetchall()
→ espero uma coleção de registros

injeção de dependência



                  PRIMEIRA EXECUÇÃO

RAW
201 válido
202 inválido
203 válido

          ┌──────────────────┐
          │                  │
          ↓                  ↓

ANALYTICS                  QUARANTINE

201                        202 INVALID_AMOUNT
203

2 linhas                   1 linha



                  SEGUNDA EXECUÇÃO

MESMO RAW
201 válido
202 inválido
203 válido

          ┌──────────────────┐
          │                  │
          ↓                  ↓

ANALYTICS                  QUARANTINE

APAGA banco anterior       NÃO APAGA
↓                          ↓
reconstrói                 tenta inserir 202 novamente
↓                          ↓
201                        UNIQUE detecta repetição
203                        ↓
                           DO NOTHING

2 linhas                   1 linha
## Transformações

## Data Quality

## Como executar

## Decisões de engenharia

## Limitações atuais

## Melhorias futuras

## Referências

atomicidade: tratar um conjunto de alterações como uma unidade que será confirmada integralmente ou desfeita



| No código                 | Na planilha                            |
| ------------------------- | -------------------------------------- |
| `BEGIN`                   | Começar um conjunto de edições         |
| `DELETE` e `INSERT`       | Apagar linhas antigas e colocar novas  |
| `commit()`                | Salvar as edições                      |
| `rollback()`              | Descartar as edições ainda não salvas  |
| `analytics_path.unlink()` | Excluir o arquivo inteiro pelo Windows |


1. construir Analytics temporário completamente
2. se o processamento falhar:
      descartar temporário
      manter Analytics oficial

3. só depois persistir a quarentena
4. se tudo necessário tiver funcionado:
      promover Analytics temporário

5. qualquer falha:
      deve ser visível/registrada
# Plano técnico priorizado

Roadmap incremental para evoluir o produto sem trocar a base funcional. Uma etapa só muda para concluída quando tiver testes e documentação correspondentes. Esta lista é planejamento, não promessa de que os itens futuros já existam.

## P0 — integridade de dados e segurança da execução

- [x] Preservar transcrição completa sem enviar tudo ao prompt; comprimir blocos antigos e manter contexto recente limitado.
- [x] Criar tabela de arquivo de forma aditiva para bancos existentes e cobrir migração/recuperação em testes.
- [x] Impedir envio de chave por HTTP remoto e validar URL sem credenciais/query no endpoint.
- [x] Backup atômico e permissões privadas para `.env`; rejeitar `.env` como symlink.
- [x] Limitar concorrência HTTP, aplicar timeout de leitura e rate limiting por cliente.
- [ ] Padronizar erros e validar rigorosamente todas as respostas/argumentos do provedor.
- [x] Ler `.env` como dados com parser compartilhado por início manual e Termux:Boot; sem sourcing, expansão ou execução.
- [x] Backup/restore do SQLite via API `sqlite3`, com integrity check, arquivos privados, destino sem sobrescrita, confirmação e salvaguarda antes de restaurar.

## P1 — contexto, provedores, ferramentas e observabilidade

- [ ] Separar interfaces de provider, contexto, sessão, memória e política sem quebrar o endpoint e o banco atuais.
- [ ] Gerenciar vários provedores/modelos por configuração; retry/backoff seletivo, fallback e limites de custo/tempo.
- [ ] Implementar streaming/cancelamento e normalização de tool calling entre formatos, com testes sem chamadas pagas.
- [ ] Evoluir memória com FTS5 detectado em runtime e fallback SQLite, busca por relevância, metadados, resumo e deduplicação.
- [ ] Adicionar trilha de auditoria estruturada e logs rotativos sem conteúdo sensível ou segredos.
- [ ] Substituir dispatch fixo por registry tipado de ferramentas, schemas, orçamento, política de risco e confirmação verificável.
- [ ] Testar API por integração, concorrência, entradas malformadas, limites e regressões; adicionar checagem de shell na CI.

## P2 — extensibilidade controlada

- [ ] Skills: manifesto/metadados, descoberta progressiva, carregamento sob demanda e conteúdo explicitamente não confiável.
- [ ] Plugins: manifesto declarativo, allowlist explícita, permissões, integridade e diagnóstico sem importar/executar código desconhecido.
- [ ] MCP opt-in, servidor desabilitado por padrão, validação de schemas, timeout, limites e gestão de credenciais.
- [ ] Scheduler SQLite com leases/locks, recorrência, retry, histórico, pausa e recuperação sem duplicidade.
- [ ] Subagentes com sessões isoladas, teto de profundidade, passos, custo, tempo e cancelamento.
- [ ] Adaptadores Termux:API/Android com permissões explícitas, simulação em testes e confirmação para efeitos externos.

## P3 — operações e experiência diária

- [ ] Interface: lista e renomeação de sessões, estados reais de saúde, streaming, cancelamento, apresentação segura de tools e acessibilidade.
- [ ] Comandos `status`, `doctor`, `stop`, `restart`, `update` e `uninstall` idempotentes (backup/restore SQLite existem em `scripts/db_maintenance.py`; os demais ainda faltam).
- [ ] Atualizador com detecção de mudanças locais, backup, arquivos gerenciados, validação e rollback; nunca tocar em `.env`, memória ou workspace sem consentimento.
- [ ] Supervisor Termux com parada explícita, prevenção de duplicatas e limites de reinício (log privado com rotação básica já foi implementado).
- [ ] CI com lint, análise estática, detecção de segredos, verificação de shell e cobertura sem API paga.
- [ ] Escolher e documentar uma licença pública com o proprietário antes de aceitar reutilização/contribuições externas.

## Observações de escopo

- A camada de processo no Termux não é uma sandbox. Executar shell/plugins arbitrários no mesmo processo não vira seguro apenas com allowlist no prompt.
- Arquivo comprimido ainda consome armazenamento conforme a conversa cresce. Uma cota rígida exige política transparente de expiração/backup; não descartar história silenciosamente.
- Operações por câmera, microfone, telefone, SMS e outros efeitos Android devem ser opt-in, testadas no aparelho e acompanhadas de confirmação/política.
- Compatibilidade de provedor depende de suporte real a Chat Completions e chamadas de ferramentas; um nome de modelo ou URL não garante esse contrato.

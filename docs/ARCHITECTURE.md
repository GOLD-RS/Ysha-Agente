# Arquitetura atual e limites

Este documento descreve o código que existe agora; não trata itens planejados como funcionalidades prontas.

## Estrutura atual

- `src/termux_agent/__main__.py`: valida os perfis configurados e compõe `ProviderManager`, memória SQLite, agente e servidor.
- `config.py`: interpreta `.env` sem executar conteúdo, lê variáveis de ambiente e valida perfis de provider/endpoint; mantém `AGENT_API_KEY`, `AGENT_BASE_URL` e `AGENT_MODEL` como modo legado.
- Perfis múltiplos usam `AGENT_PROVIDER_IDS`, provider selecionado, lista explícita de fallbacks e um bloco `AGENT_PROVIDER_<ID>_*` por modelo; as credenciais permanecem apenas no `.env` local.
- `agent.py`: orquestra um turno e o ciclo limitado de tool calling por interfaces; delega contexto, lock de sessão e execução de ferramentas e abre o escopo de orçamento do provider para a resposta inteira.
- `provider.py`: protocolo `Provider` e adapter Chat Completions compatível com o modo legado; classifica falhas transitórias/permanentes e valida envelope, mensagens, tools, IDs e JSON.
- `provider_manager.py`: cria adapters por tipo, seleciona provider/modelo por perfil, aplica retries/backoff limitados, deadline e teto de tentativas compartilhados por toda a resposta (inclusive tool cycles), e fallback explícito só após falhas transitórias.
- `context.py`: monta instruções, histórico recente e mensagem nova; valida as entradas do backend de memória.
- `sessions.py`: serializa turnos da mesma sessão, mantendo sessões diferentes independentes.
- `memory.py`: contrato mínimo de memória (`get_recent`, `add_exchange`, `delete`).
- `history.py`: implementação SQLite desse contrato, transcript e arquivamento comprimido de blocos antigos.
- `policy.py`: allowlist/esquemas das ferramentas atuais; rejeita nomes e argumentos fora da política.
- `tools.py`: implementação fixa de hora local e calculadora AST segura.
- `db_maintenance.py`: API SQLite de snapshot/verificação/restauração, bloqueio entre processos e salvaguarda antes de restore.
- `server.py`: `ThreadingHTTPServer`, autenticação Bearer injetada pela composição, JSON local, UI e erros genéricos com códigos estáveis.
- `web/index.html`: interface estática, sem bibliotecas frontend/CDN, servida pelo próprio processo.
- `scripts/`, `setup-termux.sh`, `start-agent.sh`, `termux-boot/`: configuração, início e supervisor de boot.
- `tests/`: testes unitários de agente, banco, setup, configuração e existência da interface; GitHub Actions compila e executa a suíte.

## Caminho de uma mensagem

1. O navegador envia mensagem e identificador de sessão para `POST /chat`.
2. `server.py` valida método, caminho, token, tamanho e JSON sem depender do provider.
3. `Agent.respond` valida sessão/mensagem, usa `SessionCoordinator` e abre um orçamento provider-scoped para o turno todo.
4. `ContextBuilder` combina instrução, mensagens recentes da interface `ConversationMemory` e a nova mensagem.
5. `ProviderManager` escolhe o perfil selecionado; `ChatProvider` envia o pedido e valida Chat Completions.
6. Em timeout/rede ou HTTP recuperável, o manager aplica retries limitados e, se configurado, tenta os fallbacks pela ordem definida. Falhas permanentes não avançam para outro perfil.
7. `ToolPolicy` confere nome/schema e só então despacha para as implementações seguras em `tools.py`.
8. O agente devolve texto final e persiste o par usuário/assistente pelo contrato de memória.

## Fronteiras de segurança reais

- O servidor escuta em loopback por padrão. O token Bearer é uma camada adicional, não substitui HTTPS para acesso remoto.
- O transporte para endpoint remoto exige HTTPS; HTTP só é permitido em loopback local. A URL de provedor vem da configuração local, não de instruções do modelo.
- As ferramentas existentes não executam shell, não leem arquivos e não fazem ações externas. A calculadora aceita uma AST aritmética restrita.
- O processo Python e as ferramentas compartilham o mesmo usuário e filesystem do Termux. **Não existe sandbox de processos** nem isolamento de plugin/MCP.
- O conteúdo da conversa é enviado ao provedor escolhido; as transcrições locais ficam no arquivo SQLite. A interface não envia credenciais do provedor ao navegador.
- `.env` é tratado apenas como dados pelo parser Python: aceita somente atribuições `AGENT_*`, comentários em linhas próprias e valores citados com a gramática compatível com o setup atual. `shlex` separa tokens, sem expansão de `$`, substituição `$(...)`, execução de comandos ou importação de variáveis arbitrárias. Valores do arquivo substituem variáveis `AGENT_*` herdadas pelo processo. Setup, início manual e Termux:Boot usam o mesmo parser.

## Limites ainda presentes

O manager suporta vários perfis/modelos pelo adapter Chat Completions, com seleção, lista de fallback explícita, classificação de falhas, até dois retries por perfil, backoff limitado e deadline total; ainda não há descoberta automática nem adapters para contratos nativos diferentes. Contexto apenas recente e sem recuperação semântica. Arquivos arquivados são preservados em SQLite comprimido, mas não há cota rígida, busca FTS, expiração ou consolidação de fatos. O utilitário de backup/restore usa snapshot SQLite, integrity check, arquivo privado, recusa sobrescrita de backup e cria salvaguarda automática antes de restaurar; restore exige o agente parado e confirmação explícita. API agora limita a taxa de chat por IP, o número de workers e o tempo de leitura do corpo; erros seguem `{error, message}` sem detalhes internos e ainda não há cancelamento de chamadas ao provider iniciadas. A interface ainda não tem lista/renomeação de sessões, streaming, cancelamento nem visualização de tools. Não existem plugins, skills, MCP, scheduler, subagentes, shell, Android API adapters ou trilha de auditoria estruturada.

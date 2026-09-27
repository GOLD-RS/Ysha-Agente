# Arquitetura atual e limites

Este documento descreve o código que existe agora; não trata itens planejados como funcionalidades prontas.

## Estrutura atual

- `src/termux_agent/__main__.py`: valida configuração e inicializa servidor, provedor, histórico e agente.
- `config.py`: interpreta `.env` sem executar conteúdo, lê variáveis de ambiente e valida configuração/endpoints.
- `agent.py`: orquestra um turno e o ciclo limitado de tool calling por interfaces, sem montar contexto, adquirir lock de sessão nem executar ferramentas diretamente.
- `provider.py`: contrato `Provider` e cliente síncrono Chat Completions, com validação estrita de envelope, mensagens, chamadas, IDs e argumentos JSON.
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
3. `Agent.respond` valida sessão/mensagem e usa `SessionCoordinator` para serializar a mesma sessão.
4. `ContextBuilder` combina instrução, mensagens recentes da interface `ConversationMemory` e a nova mensagem.
5. `Provider.complete` recebe o pedido; o adapter atual valida Chat Completions e pode devolver chamadas de ferramentas.
6. `ToolPolicy` confere nome/schema e só então despacha para as implementações seguras em `tools.py`.
7. O agente devolve texto final e persiste o par usuário/assistente pelo contrato de memória.

## Fronteiras de segurança reais

- O servidor escuta em loopback por padrão. O token Bearer é uma camada adicional, não substitui HTTPS para acesso remoto.
- O transporte para endpoint remoto exige HTTPS; HTTP só é permitido em loopback local. A URL de provedor vem da configuração local, não de instruções do modelo.
- As ferramentas existentes não executam shell, não leem arquivos e não fazem ações externas. A calculadora aceita uma AST aritmética restrita.
- O processo Python e as ferramentas compartilham o mesmo usuário e filesystem do Termux. **Não existe sandbox de processos** nem isolamento de plugin/MCP.
- O conteúdo da conversa é enviado ao provedor escolhido; as transcrições locais ficam no arquivo SQLite. A interface não envia credenciais do provedor ao navegador.
- `.env` é tratado apenas como dados pelo parser Python: aceita somente atribuições `AGENT_*`, comentários em linhas próprias e valores citados com a gramática compatível com o setup atual. `shlex` separa tokens, sem expansão de `$`, substituição `$(...)`, execução de comandos ou importação de variáveis arbitrárias. Valores do arquivo substituem variáveis `AGENT_*` herdadas pelo processo. Setup, início manual e Termux:Boot usam o mesmo parser.

## Limites ainda presentes

Provedor único por processo; sem descoberta/fallback/retry/streaming. Contexto apenas recente e sem recuperação semântica. Arquivos arquivados são preservados em SQLite comprimido, mas não há cota rígida, busca FTS, expiração ou consolidação de fatos. O utilitário de backup/restore usa snapshot SQLite, integrity check, arquivo privado, recusa sobrescrita de backup e cria salvaguarda automática antes de restaurar; restore exige o agente parado e confirmação explícita. API agora limita a taxa de chat por IP, o número de workers e o tempo de leitura do corpo; erros seguem `{error, message}` sem detalhes internos e ainda não há cancelamento de chamadas ao provedor iniciadas. A interface ainda não tem lista/renomeação de sessões, streaming, cancelamento nem visualização de tools. Não existem plugins, skills, MCP, scheduler, subagentes, shell, Android API adapters ou trilha de auditoria estruturada.

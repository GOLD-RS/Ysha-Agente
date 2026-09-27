# Ysha Agente

Assistente pessoal de IA para Android/Termux. O repositório é público e pode ser clonado sem conta GitHub. O projeto não usa números de versão ou releases numeradas: a referência de instalação é o conteúdo atual da branch `main`.

## Estado atual

O Ysha funciona como um servidor local de conversa conectado a qualquer provedor que ofereça endpoint compatível com OpenAI Chat Completions e chamadas de ferramentas. Não há provedor obrigatório nem padrão associado a uma empresa; cada pessoa configura seu próprio endpoint, modelo e chave no arquivo local `.env`.

- Servidor local em `127.0.0.1:8765`, com chat web responsivo integrado e sem dependências externas.
- API com limite por cliente, até 8 workers concorrentes, leitura de corpo com timeout e respostas 429/503 quando ocupada.
- Histórico completo em SQLite por sessão; blocos antigos são compactados, enquanto o prompt usa apenas o contexto recente configurado.
- Mensagens da mesma sessão processadas em ordem; sessões distintas continuam independentes.
- Ferramentas locais limitadas à hora e à calculadora segura; não executa comandos nem lê arquivos.
- Configuração de instalação guiada, inicialização simplificada e opção para Termux:Boot.
- Chaves e banco de dados ficam fora do Git.
- Ainda não integra Telegram/WhatsApp e não garante execução 24/7 se o Android encerrar o processo ou faltar bateria/rede.

`AGENT_HISTORY_LIMIT` controla somente quantas mensagens recentes entram no prompt; não apaga a transcrição. Após ultrapassar 500 mensagens ativas por sessão, blocos antigos são comprimidos no mesmo SQLite, preservando o histórico completo e mantendo a parte ativa menor. Isso reduz uso de linhas e espaço repetido, mas ainda não define uma cota rígida para arquivos de arquivo — limites e expiração configuráveis ficam para uma etapa posterior. Já existe um utilitário de backup/restore seguro, descrito abaixo.

## Requisitos

- Android com Termux instalado por uma fonte confiável.
- Python 3.10 ou mais recente; o setup instala Python pelo `pkg` se necessário.
- Chave de API do provedor escolhido, compatível com Chat Completions e chamadas de ferramentas.

## Instalação guiada no Termux

Instale Termux de uma fonte confiável, como F-Droid ou o GitHub oficial. No Termux, execute:

```sh
pkg update -y
pkg install -y git python
mkdir -p ~/projetos
cd ~/projetos
git clone https://github.com/GOLD-RS/Ysha-Agente.git
cd Ysha-Agente
chmod +x setup-termux.sh start-agent.sh
./setup-termux.sh
```

O setup cria ou atualiza `.env`, pede a chave API sem exibi-la, oferece configuração genérica de endpoint compatível com OpenAI por padrão e permite escolher uma configuração opcional da Agnes AI. Valida URL/modelo, grava o arquivo atomicamente com permissão privada, faz backup do `.env` anterior como `.env.backup` e roda os testes. Se já houver provedor e chave configurados, eles são mantidos a menos que você escolha alterá-los. A configuração de Termux:Boot é opcional e só ocorre com sua confirmação. O arquivo `.env` é interpretado pelo Python como dados; nenhum script o executa como shell.

A chave precisa ser criada na conta do provedor de IA. Não a envie no chat, não a publique e não a coloque em um commit. O setup não instala bibliotecas Python externas: o agente usa a biblioteca padrão.

### Iniciar e testar

Inicie o servidor em primeiro plano:

```sh
./start-agent.sh
```

Com o servidor ativo, abra o navegador do próprio Android em **http://127.0.0.1:8765/**. Essa é a interface de chat: envie mensagens, comece conversas novas e retome o histórico salvo. Se você configurou `AGENT_ACCESS_TOKEN`, informe-o no botão de configurações do chat; ele fica apenas na aba do navegador.

Deixe a sessão do servidor aberta. Se quiser testar pela API em outra sessão do Termux:

```sh
curl http://127.0.0.1:8765/health
curl -X POST http://127.0.0.1:8765/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Quanto é (8+4)*3?","session_id":"teste"}'
```

Use o mesmo `session_id` para continuar a conversa. A resposta inclui `reply` e `session_id`. O health check informa apenas o estado e o backend de memória.

## Configuração da API

No setup, escolha a opção genérica e informe o endpoint-base, o nome exato do modelo e uma chave emitida pelo provedor que você usa. O adapter atual fala OpenAI Chat Completions com chamadas de ferramentas; vários perfis podem apontar para serviços/modelos diferentes que implementem esse contrato. A Agnes AI aparece apenas como atalho opcional. Endpoints remotos exigem HTTPS; HTTP só é aceito para loopback local. Nunca coloque chaves no repositório, documentação, testes ou logs. Depois de editar `.env`, encerre o processo com Ctrl+C e rode `./start-agent.sh` novamente.

Para a configuração legada de um único perfil, preencha `AGENT_API_KEY`, `AGENT_BASE_URL` e `AGENT_MODEL`. Ela continua funcionando e usa o adapter Chat Completions.

Para vários perfis, defina `AGENT_PROVIDER_IDS=primary,backup`, escolha `AGENT_PROVIDER_SELECTED=primary` e liste a ordem explícita em `AGENT_PROVIDER_FALLBACKS=backup`. Os IDs devem ser únicos, minúsculos e começar por uma letra; depois podem conter letras, números e `_`. Para cada ID, configure `AGENT_PROVIDER_<ID>_TYPE=chat_completions`, `AGENT_PROVIDER_<ID>_API_KEY`, `AGENT_PROVIDER_<ID>_BASE_URL`, `AGENT_PROVIDER_<ID>_MODEL`, `AGENT_PROVIDER_<ID>_TIMEOUT_SECONDS` e `AGENT_PROVIDER_<ID>_MAX_RETRIES` — use o ID em maiúsculas no nome das variáveis. Defina as chaves apenas no `.env` local. Com `AGENT_PROVIDER_IDS`, os três campos legados são ignorados; o setup guiado continua voltado ao modo legado, então edite os perfis múltiplos diretamente no `.env`.

Cada perfil aceita de 0 a 2 retries; o atraso crescente é limitado a 1 segundo. `AGENT_PROVIDER_TOTAL_TIMEOUT_SECONDS` limita o tempo de uma resposta inteira, incluindo ciclos de ferramentas (padrão 90 s, máximo 180 s); `AGENT_PROVIDER_MAX_ATTEMPTS_PER_RESPONSE` limita tentativas combinadas entre providers e chamadas de tools (padrão 8, máximo 24). Cada perfil nomeado tem timeout próprio (padrão 30 s, máximo 90 s); o perfil legado conserva 90 s por padrão. O fallback só avança após falhas transitórias classificadas — timeout/rede e HTTP 408, 425, 429, 500, 502, 503 ou 504, depois dos retries daquele perfil. Erros de autenticação/configuração, outros 4xx, contrato/resposta inválida e erros do agente são permanentes e não disparam fallback. A API usa códigos estáveis para falha do provider (`provider_failure`, 502), indisponibilidade total (`providers_unavailable`, 503), limite de tentativas (`provider_attempt_limit`, 503) e deadline (`provider_timeout`, 504). Logs registram apenas ID do perfil, tentativa e classe da falha, inclusive início/sucesso do fallback; não registram chaves, URLs, modelos, corpo da resposta ou exceções brutas. Cada retry ou fallback é uma nova chamada ao serviço e pode gerar cobrança.

O arquivo aceita linhas `AGENT_NOME=valor`, linhas de comentário iniciadas por `#` e valores citados com sintaxe compatível com a configuração atual do setup. Aspas preservam espaços e caracteres como `$`, `;`, `#`, barra invertida e aspas. Não há expansão de variáveis, substituição `$(...)` nem execução de comandos: esses caracteres são apenas texto. O arquivo pode ser editado pelo setup, que faz a citação apropriada para os valores inseridos.

Variáveis adicionais incluem `AGENT_HOST`, `AGENT_PORT`, `AGENT_ACCESS_TOKEN`, `AGENT_DB_PATH` e `AGENT_HISTORY_LIMIT`. Por segurança, mantenha `AGENT_HOST=127.0.0.1`. Um token é opcional no loopback; se configurar `AGENT_ACCESS_TOKEN`, inclua `Authorization: Bearer <token>` nas chamadas protegidas.

## Início automático com o Android

Instale Termux:Boot da mesma fonte do Termux e abra o aplicativo uma vez. Rode `./setup-termux.sh` e confirme a opção de início automático. Para solicitar wakelock, instale também o aplicativo Termux:API e o pacote `termux-api`:

```sh
pkg install -y termux-api
```

O supervisor grava logs privados em `~/ysha-agente.log`, mantém no máximo o log atual e um arquivo rotacionado de cerca de 1 MiB cada, e tenta reiniciar o servidor após falhas. Desative a otimização de bateria para Termux e Termux:Boot. Ainda assim, nenhum script garante 24/7 em todos os aparelhos e condições.

## Atualizar

Pare o servidor com Ctrl+C antes de atualizar:

```sh
cd ~/projetos/Ysha-Agente
git pull --ff-only
./setup-termux.sh
```

O setup preserva sua chave, valida o projeto e executa os testes.

## Backup e restauração do histórico

Use o utilitário Python do repositório, que lê `.env` como dados e usa a API de backup do SQLite:

```sh
python3 scripts/db_maintenance.py backup
python3 scripts/db_maintenance.py restore "/caminho/para/o-backup.sqlite3"
```

O backup cria um nome novo ao lado do banco, recusa sobrescrever qualquer arquivo existente, valida `PRAGMA integrity_check` e o esquema esperado e grava a cópia com permissão `0600`. Pode ser executado enquanto o agente está ativo; SQLite captura um snapshot consistente, inclusive com WAL.

A restauração valida e prepara a cópia antes de tocar no banco. Se já houver memória, cria primeiro um backup automático `before-restore` e imprime o caminho. Exige digitar `RESTAURAR`; `--yes` é aceito apenas como confirmação explícita para automação. O processo obtém bloqueio exclusivo e recusa restaurar enquanto o agente estiver aberto. Se a validação falhar, tenta retornar ao snapshot anterior; a cópia anterior permanece guardada para recuperação manual.

## Rotas locais

- `GET /` — interface web local para conversar com o agente.
- `GET /health` — estado do serviço.
- `GET /sessions/{session_id}` — histórico da sessão atual.
- `POST /chat` — recebe `{"message":"..."}` e, opcionalmente, `session_id`.
- `DELETE /sessions/{session_id}` — apaga o histórico daquela sessão.

Erros da API usam JSON com `error` (código estável) e `message` (texto seguro); falhas internas não retornam exceções, stack traces, conteúdo do provedor ou credenciais. O servidor aceita apenas conexões locais por padrão. Não o exponha diretamente à internet; para acesso remoto seriam necessárias proteções adicionais e HTTPS.

## Arquitetura e evolução

- [Arquitetura atual, fluxo e limites de segurança](docs/ARCHITECTURE.md)
- [Roadmap técnico priorizado](docs/ROADMAP.md)

Os documentos distinguem o que já existe do que ainda está planejado.

## Desenvolvimento e validação

```sh
PYTHONPATH=src python -m compileall -q src tests scripts
PYTHONPATH=src python -m unittest discover -s tests -v
```

O GitHub Actions também compila e executa os testes em cada push e pull request.

# Ysha Agente

Assistente pessoal de IA para Android/Termux. O repositório é público e pode ser clonado sem conta GitHub. O projeto não usa números de versão ou releases numeradas: a referência de instalação é o conteúdo atual da branch `main`.

## Estado atual

O Ysha funciona como um servidor local de conversa conectado a qualquer provedor que ofereça endpoint compatível com OpenAI Chat Completions e chamadas de ferramentas. Não há provedor obrigatório nem padrão associado a uma empresa; cada pessoa configura seu próprio endpoint, modelo e chave no arquivo local `.env`.

- Servidor local em `127.0.0.1:8765`, com chat web responsivo integrado e sem dependências externas.
- Histórico SQLite persistente por sessão, limitado às últimas 20 mensagens por padrão.
- Mensagens da mesma sessão processadas em ordem; sessões distintas continuam independentes.
- Ferramentas locais limitadas à hora e à calculadora segura; não executa comandos nem lê arquivos.
- Configuração de instalação guiada, inicialização simplificada e opção para Termux:Boot.
- Chaves e banco de dados ficam fora do Git.
- Ainda não integra Telegram/WhatsApp e não garante execução 24/7 se o Android encerrar o processo ou faltar bateria/rede.

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

O setup cria ou atualiza `.env`, pede a chave API sem exibi-la, oferece configuração genérica de endpoint compatível com OpenAI por padrão e permite escolher uma configuração opcional da Agnes AI. Valida a URL/modelo, protege `.env` com permissão privada e roda os testes. Se já houver provedor e chave configurados, eles são mantidos a menos que você escolha alterá-los. A configuração de Termux:Boot é opcional e só ocorre com sua confirmação.

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

No setup, escolha a opção genérica e informe o endpoint-base, o nome exato do modelo e uma chave emitida pelo provedor que você usa. O endpoint precisa seguir o formato OpenAI Chat Completions e aceitar chamadas de ferramentas; isso permite configurar diferentes serviços sem prender o projeto a um deles. A Agnes AI aparece apenas como atalho opcional. Depois de editar `.env`, encerre o processo com Ctrl+C e rode `./start-agent.sh` novamente. Confirme na documentação do provedor o endpoint e o identificador do modelo.

Preencha `AGENT_API_KEY`, `AGENT_BASE_URL` e `AGENT_MODEL` em `.env`; use os valores e o formato informados pelo provedor escolhido.

Variáveis adicionais incluem `AGENT_HOST`, `AGENT_PORT`, `AGENT_ACCESS_TOKEN`, `AGENT_DB_PATH` e `AGENT_HISTORY_LIMIT`. Por segurança, mantenha `AGENT_HOST=127.0.0.1`. Um token é opcional no loopback; se configurar `AGENT_ACCESS_TOKEN`, inclua `Authorization: Bearer <token>` nas chamadas protegidas.

## Início automático com o Android

Instale Termux:Boot da mesma fonte do Termux e abra o aplicativo uma vez. Rode `./setup-termux.sh` e confirme a opção de início automático. Para solicitar wakelock, instale também o aplicativo Termux:API e o pacote `termux-api`:

```sh
pkg install -y termux-api
```

O supervisor grava logs em `~/ysha-agente.log` e tenta reiniciar o servidor após uma falha. Desative a otimização de bateria para Termux e Termux:Boot. Ainda assim, nenhum script garante 24/7 em todos os aparelhos e condições.

## Atualizar

Pare o servidor com Ctrl+C antes de atualizar:

```sh
cd ~/projetos/Ysha-Agente
git pull --ff-only
./setup-termux.sh
```

O setup preserva sua chave, valida o projeto e executa os testes.

## Rotas locais

- `GET /` — interface web local para conversar com o agente.
- `GET /health` — estado do serviço.
- `GET /sessions/{session_id}` — histórico da sessão atual.
- `POST /chat` — recebe `{"message":"..."}` e, opcionalmente, `session_id`.
- `DELETE /sessions/{session_id}` — apaga o histórico daquela sessão.

O servidor aceita apenas conexões locais por padrão. Não o exponha diretamente à internet; para acesso remoto seriam necessárias proteções adicionais e HTTPS.

## Desenvolvimento e validação

```sh
PYTHONPATH=src python -m compileall -q src tests scripts
PYTHONPATH=src python -m unittest discover -s tests -v
```

O GitHub Actions também compila e executa os testes em cada push e pull request.

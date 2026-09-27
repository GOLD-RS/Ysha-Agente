# Ysha Agente

Um agente pessoal de IA pensado para rodar continuamente em Android com Termux. O projeto busca combinar a ideia de um agente extensível com ferramentas e automações, inspirado nas capacidades de projetos como OpenClaw e Hermes, mas com implementação própria.

> **Estado:** protótipo em evolução. Esta versão oferece uma API local de conversa conectada a um provedor compatível com Chat Completions. Inclui histórico local SQLite por sessão e ferramentas locais limitadas (hora e calculadora); ainda não executa comandos no Android nem integra canais externos.

## O que já funciona

- Servidor HTTP persistente em `127.0.0.1:8765`.
- `GET /health` para verificar se está ativo.
- `POST /chat` para conversar com um modelo configurado, com contexto persistido por sessão.
- Ferramentas limitadas: consulta de hora local e calculadora protegida por análise sintática (sem execução de código).
- `DELETE /sessions/{session_id}` para apagar o histórico daquela sessão.
- Supervisor do Termux:Boot: tenta reiniciar o processo após falhas, aguardando 10 segundos.
- Configuração por variáveis de ambiente; segredo de API fora do Git.
- Script inicial para Termux:Boot e solicitação de wakelock.
- Testes unitários sem depender de uma chave real.

## Requisitos

- Android com [Termux](https://termux.dev/) instalado (prefira instalar pelo F-Droid ou GitHub oficial).
- Python 3.10 ou mais recente.
- Uma chave de API de um provedor compatível com o endpoint Chat Completions.
- Para iniciar junto com o aparelho: aplicativos Termux:Boot e (opcionalmente, para wakelock) Termux:API.

## Instalação no Termux

```sh
pkg update -y && pkg install -y git python
# Opcional: instale também o app Termux:API e seu pacote para usar wakelock
pkg install -y termux-api
mkdir -p ~/projetos && cd ~/projetos
git clone https://github.com/GOLD-RS/Ysha-Agente.git
cd Ysha-Agente
cp .env.example .env
nano .env
```

Edite `AGENT_API_KEY` e, se necessário, `AGENT_BASE_URL` e `AGENT_MODEL`. Não publique nem envie seu arquivo `.env`.

Inicie manualmente:

```sh
PYTHONPATH=src python -m termux_agent
```

Em outra sessão do Termux, teste:

```sh
curl http://127.0.0.1:8765/health
curl -X POST http://127.0.0.1:8765/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Oi!"}'
```

## Execução contínua e início no boot

Instale o aplicativo Termux:Boot da mesma fonte do Termux e abra-o uma vez. Depois copie o script de inicialização para a pasta de boot:

```sh
mkdir -p ~/.termux/boot
cp termux-boot/start-agent ~/.termux/boot/start-agent
chmod +x ~/.termux/boot/start-agent
```

O script supervisiona o processo, tenta reiniciá-lo após falhas, grava saída em `~/ysha-agente.log` e solicita `termux-wake-lock` quando o comando estiver disponível. No Android, desative a otimização de bateria para Termux e Termux:Boot. **Nenhum app consegue garantir disponibilidade 24/7** se o sistema encerrar o processo, faltar bateria ou internet.

## API local

- `GET /health` → estado do processo.
- `POST /chat` com JSON `{"message":"..."}` → resposta e `session_id`; envie esse `session_id` nas mensagens seguintes para manter o contexto.
- `DELETE /sessions/{session_id}` remove o histórico local da sessão.
- O servidor escuta apenas em `127.0.0.1`; não o exponha diretamente à internet.

## Memória e segurança

O histórico é salvo localmente em `data/ysha-agent.sqlite3` (ou `AGENT_DB_PATH`) e limitado às últimas 20 mensagens por sessão (`AGENT_HISTORY_LIMIT`). Envie `session_id` no JSON para retomar uma sessão; omita para iniciar uma nova. Apague uma sessão com `DELETE /sessions/{session_id}`. O banco pode conter informações pessoais: proteja o aparelho e faça backup somente se desejar.

A API local não tem autenticação e fica vinculada a `127.0.0.1` por padrão. Não a exponha diretamente à internet. As ferramentas desta versão não executam comandos, não acessam arquivos e não fazem ações externas. O projeto ainda precisa de autenticação, controle de acesso e confirmações antes de adicionar integrações mais poderosas. Android pode encerrar processos em segundo plano; 24/7 não é garantido apenas pelo app.

## Desenvolvimento

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Integração contínua

O GitHub Actions executa compilação e testes unitários em cada push e pull request.

## Licença

Ainda não definida.

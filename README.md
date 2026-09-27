# Agente Geral para Termux

Um agente pessoal de IA pensado para rodar continuamente em Android com Termux. O projeto busca combinar a ideia de um agente extensível com ferramentas e automações, inspirado nas capacidades de projetos como OpenClaw e Hermes, mas com implementação própria.

> **Estado:** protótipo inicial. Esta versão oferece uma API local de conversa conectada a um provedor compatível com a API da OpenAI. Ainda não executa ações no Android nem integra canais externos.

## O que já funciona

- Servidor HTTP persistente em `127.0.0.1:8765`.
- `GET /health` para verificar se está ativo.
- `POST /chat` para conversar com um modelo configurado.
- Configuração por variáveis de ambiente; segredo de API fora do Git.
- Script inicial para Termux:Boot e solicitação de wakelock.
- Testes unitários sem depender de uma chave real.

## Requisitos

- Android com [Termux](https://termux.dev/) instalado (prefira instalar pelo F-Droid ou GitHub oficial).
- Python 3.10 ou mais recente.
- Uma chave de API de um provedor compatível com o endpoint Chat Completions.
- Para iniciar junto com o aparelho: aplicativo Termux:Boot.

## Instalação no Termux

```sh
pkg update -y && pkg install -y git python
mkdir -p ~/projetos && cd ~/projetos
git clone https://github.com/GOLD-RS/agente-geral-termux.git
cd agente-geral-termux
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

O script mantém o processo ativo com `nohup`, grava saída em `~/agente-geral-termux.log` e solicita `termux-wake-lock` quando o comando estiver disponível. No Android, desative a otimização de bateria para Termux e Termux:Boot. **Nenhum app consegue garantir disponibilidade 24/7** se o sistema encerrar o processo, faltar bateria ou internet.

## API local

- `GET /health` → estado do processo.
- `POST /chat` com JSON `{"message":"..."}` → resposta do modelo.
- O servidor escuta apenas em `127.0.0.1`; não o exponha diretamente à internet.

## Segurança e próximos passos

A API local não tem autenticação; por isso, fica vinculada ao loopback. Não adicione ferramentas que executem comandos, leiam arquivos ou enviem mensagens sem permissões explícitas, limites e confirmação para ações externas. Próximas etapas: memória persistente opt-in, catálogo de ferramentas seguras, integrações de mensageria escolhidas pelo usuário, supervisão/reinício e painel de estado.

## Desenvolvimento

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Licença

Ainda não definida.

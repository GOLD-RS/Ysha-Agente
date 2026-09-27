#!/usr/bin/env python3
"""Assistente de configuração do Ysha Agente; mantém segredos fora do Git."""

from getpass import getpass
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"
ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
PROVIDERS = {
    "1": ("Outro provedor compatível com OpenAI Chat Completions", "", ""),
    "2": ("Agnes AI (opcional)", "https://apihub.agnes-ai.com/v1", "agnes-3.0-flash"),
}


def read_values(lines: list[str]) -> dict[str, str]:
    values = {}
    for line in lines:
        match = ASSIGNMENT.match(line)
        if not match:
            continue
        try:
            parts = shlex.split(match.group(2), comments=False, posix=True)
        except ValueError:
            continue
        values[match.group(1)] = parts[0] if parts else ""
    return values


def update_values(lines: list[str], updates: dict[str, str]) -> list[str]:
    output = []
    written = set()
    for line in lines:
        match = ASSIGNMENT.match(line)
        if match and match.group(1) in updates:
            name = match.group(1)
            output.append(f"{name}={shlex.quote(updates[name])}")
            written.add(name)
        else:
            output.append(line)
    for name, value in updates.items():
        if name not in written:
            output.append(f"{name}={shlex.quote(value)}")
    return output


def ask_default(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def yes_no(prompt: str, default: bool = False) -> bool:
    marker = "Y/n" if default else "y/N"
    answer = input(f"{prompt} [{marker}]: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes", "s", "sim")


def choose_provider(current: dict[str, str]) -> tuple[str, str]:
    current_url = current.get("AGENT_BASE_URL", "")
    current_model = current.get("AGENT_MODEL", "")
    if current_url and current_model and yes_no("Manter o provedor e modelo já configurados?", default=True):
        return current_url, current_model

    print("\nEscolha uma configuração de provedor:")
    for code, (label, _, _) in PROVIDERS.items():
        print(f"  {code}. {label}")
    choice = input("Opção [1]: ").strip() or "1"
    while choice not in PROVIDERS:
        choice = input("Escolha 1 ou 2: ").strip()
    label, preset_url, preset_model = PROVIDERS[choice]
    if choice == "1":
        print("Informe os dados publicados pelo seu provedor OpenAI-compatível.")
    else:
        print(f"Configuração pronta para {label}; você ainda pode editar os valores.")
    base_url = ask_default("URL-base da API", preset_url).rstrip("/")
    model = ask_default("Identificador exato do modelo", preset_model)
    return base_url, model


def install_boot_launcher() -> None:
    boot_dir = Path.home() / ".termux" / "boot"
    boot_dir.mkdir(parents=True, exist_ok=True)
    launcher = boot_dir / "start-agent"
    script = ROOT / "termux-boot" / "start-agent"
    script.chmod(0o700)
    launcher.write_text(
        "#!/data/data/com.termux/files/usr/bin/sh\n"
        f"YSHA_PROJECT_DIR={shlex.quote(str(ROOT))}\n"
        "export YSHA_PROJECT_DIR\n"
        f"exec {shlex.quote(str(script))}\n",
        encoding="utf-8",
    )
    launcher.chmod(0o700)
    print(f"Inicialização configurada em {launcher}.")
    print("O aplicativo Termux:Boot também precisa estar instalado e aberto uma vez.")


def main() -> int:
    if not EXAMPLE_FILE.is_file():
        print("Não encontrei .env.example; execute o script na pasta do projeto.", file=sys.stderr)
        return 1
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    else:
        lines = EXAMPLE_FILE.read_text(encoding="utf-8").splitlines()
        print("Criando .env local a partir de .env.example.")

    current = read_values(lines)
    old_key = current.get("AGENT_API_KEY", "")
    api_key = old_key
    if old_key:
        if yes_no("Já há uma chave de API salva. Quer substituí-la?"):
            api_key = getpass("Nova chave API (entrada oculta): ").strip()
            if not api_key:
                print("A chave não foi alterada.")
                api_key = old_key
        else:
            print("Chave existente mantida; ela não será exibida.")
    else:
        api_key = getpass("Chave API do provedor (entrada oculta; Enter para configurar depois): ").strip()

    base_url, model = choose_provider(current)
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        print("URL inválida: informe a URL-base documentada pelo provedor, começando com https:// ou http://.", file=sys.stderr)
        return 1
    if not model:
        print("O identificador exato do modelo não pode ficar vazio.", file=sys.stderr)
        return 1

    updates = {
        "AGENT_API_KEY": api_key,
        "AGENT_BASE_URL": base_url,
        "AGENT_MODEL": model,
    }
    ENV_FILE.write_text("\n".join(update_values(lines, updates)) + "\n", encoding="utf-8")
    ENV_FILE.chmod(0o600)
    (ROOT / "data").mkdir(exist_ok=True)

    test_env = os.environ.copy()
    test_env["PYTHONPATH"] = str(ROOT / "src")
    subprocess.run([sys.executable, "-m", "compileall", "-q", "src", "tests"], cwd=ROOT, check=True)
    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        env=test_env,
        check=True,
    )

    print("\nConfiguração salva com permissão privada; chave ocultada.")
    print(f"Provedor: {base_url}\nModelo: {model}")
    if not api_key:
        print("Atenção: nenhuma chave foi configurada; as chamadas de chat não funcionarão ainda.")
    print("Inicie com: ./start-agent.sh")
    if yes_no("Configurar início automático com Termux:Boot?"):
        install_boot_launcher()
    else:
        print("Boot não foi alterado. Você pode configurar depois executando este setup novamente.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Configuração/testes não concluídos: {exc}", file=sys.stderr)
        raise SystemExit(1)

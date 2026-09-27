#!/usr/bin/env python3
"""Assistente de configuração do Ysha Agente; mantém segredos fora do Git."""

from getpass import getpass
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"
ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
sys.path.insert(0, str(ROOT / "src"))
from termux_agent.config import parse_env_text, validate_base_url  # noqa: E402

PROVIDERS = {
    "1": ("Qualquer provedor OpenAI-compatível", "", ""),
    "2": ("Agnes AI (opcional)", "https://apihub.agnes-ai.com/v1", "agnes-3.0-flash"),
}


def paint(text: str, code: str) -> str:
    if not sys.stdout.isatty() or os.getenv("NO_COLOR"):
        return text
    return f"\033[{code}m{text}\033[0m"


def banner() -> None:
    print(paint("╭──────────────────────────────────────────────╮", "38;5;141"))
    print(paint("│       Y S H A   A G E N T E  ·  SETUP       │", "1;97"))
    print(paint("│       Configuração simples, provedor seu     │", "38;5;110"))
    print(paint("╰──────────────────────────────────────────────╯", "38;5;141"))


def step(number: int, title: str, note: str) -> None:
    print(f"\n{paint(f'{number:02d}  {title}', '1;38;5;141')}\n    {paint(note, '38;5;110')}")


def read_values(lines: list[str]) -> dict[str, str]:
    return parse_env_text("\n".join(lines))


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


def atomic_private_write(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f"{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink()


def save_env(lines: list[str]) -> None:
    if ENV_FILE.is_symlink():
        raise ValueError("Por segurança, .env não pode ser um link simbólico.")
    if ENV_FILE.exists():
        if not ENV_FILE.is_file():
            raise ValueError(".env não é um arquivo regular.")
        atomic_private_write(ENV_FILE.with_name(".env.backup"), ENV_FILE.read_bytes())
    content = ("\n".join(lines) + "\n").encode("utf-8")
    atomic_private_write(ENV_FILE, content)


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
    banner()
    print("Este assistente guarda a configuração apenas neste aparelho.")
    if not EXAMPLE_FILE.is_file():
        print("Não encontrei .env.example; execute o script na pasta do projeto.", file=sys.stderr)
        return 1
    if ENV_FILE.is_symlink():
        print("Por segurança, .env não pode ser um link simbólico.", file=sys.stderr)
        return 1
    if ENV_FILE.exists():
        if not ENV_FILE.is_file():
            print(".env não é um arquivo regular.", file=sys.stderr)
            return 1
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    else:
        lines = EXAMPLE_FILE.read_text(encoding="utf-8").splitlines()
        print("Criando .env local a partir de .env.example.")

    current = read_values(lines)
    step(1, "Chave da API", "Ela fica oculta durante a digitação e é salva apenas em .env.")
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

    step(2, "Escolha do provedor", "Use qualquer serviço com Chat Completions e chamadas de ferramentas.")
    base_url, model = choose_provider(current)
    try:
        validate_base_url(base_url)
    except ValueError as exc:
        print(f"URL inválida: {exc}", file=sys.stderr)
        return 1
    if not model:
        print("O identificador exato do modelo não pode ficar vazio.", file=sys.stderr)
        return 1

    updates = {
        "AGENT_API_KEY": api_key,
        "AGENT_BASE_URL": base_url,
        "AGENT_MODEL": model,
    }
    had_env = ENV_FILE.exists()
    save_env(update_values(lines, updates))
    if had_env:
        print("Configuração anterior preservada em .env.backup.")
    (ROOT / "data").mkdir(exist_ok=True)

    step(3, "Conferindo a instalação", "Compilação e testes rápidos; nenhum segredo será impresso.")
    test_env = os.environ.copy()
    test_env["PYTHONPATH"] = str(ROOT / "src")
    subprocess.run([sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"], cwd=ROOT, check=True)
    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        env=test_env,
        check=True,
    )

    print("\n" + paint("✓ Setup concluído. .env está protegido e a chave foi ocultada.", "1;38;5;114"))
    print(f"Provedor: {base_url}\nModelo: {model}")
    if not api_key:
        print(paint("A chave ainda não foi informada; configure-a antes de iniciar o chat.", "38;5;203"))
    print(paint("\nPara iniciar o chat, execute: ./start-agent.sh", "1;97"))
    if api_key:
        step(4, "Início automático (opcional)", "Requer o aplicativo Termux:Boot instalado e aberto uma vez.")
        if yes_no("Configurar início automático com Termux:Boot?"):
            install_boot_launcher()
        else:
            print("Nenhuma configuração de boot foi alterada.")
    else:
        print("O início automático ficará disponível depois que a chave for configurada.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Configuração/testes não concluídos: {exc}", file=sys.stderr)
        raise SystemExit(1)

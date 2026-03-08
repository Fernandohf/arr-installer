import os
import time
import subprocess
import requests
import xml.etree.ElementTree as ET
import json
import questionary
import sys
import argparse
import socket
import concurrent.futures
import logging
from typing import Optional

try:
    import tzdata
except ImportError:
    pass

from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones
from pathlib import Path
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.live import Live

console = Console()


def make_status(state: str, label: str, style: str | None = None):
    return {"state": state, "label": label, "style": style}


def pending(label: str):
    return make_status("pending", label)


def progress(label: str):
    return make_status("in_progress", label)


def success(label: str):
    return make_status("success", label)


def failure(label: str):
    return make_status("error", label)


def warning(label: str):
    return make_status("warning", label)


def info(label: str):
    return make_status("info", label)


def render_status(cell):
    if not isinstance(cell, dict):
        return cell

    state = cell["state"]
    label = cell["label"]
    style = cell.get("style")

    if state == "in_progress":
        return Spinner("dots", text=Text(label, style=style or "bold cyan"), style=style or "cyan")
    if state == "success":
        return Text(label, style=style or "bold green")
    if state == "error":
        return Text(label, style=style or "bold red")
    if state == "warning":
        return Text(label, style=style or "bold yellow")
    if state == "info":
        return Text(label, style=style or "bold blue")
    return Text(label, style=style or "dim")


def prompt_confirmed_password():
    while True:
        password = questionary.password("Admin Password:").ask()
        password_confirmation = questionary.password("Confirm Admin Password:").ask()

        if password == password_confirmation:
            return password

        console.print(
            Panel.fit(
                "[bold yellow]Passwords did not match.[/bold yellow]\n[dim]Please re-enter them to avoid locking yourself out later.[/dim]",
                border_style="yellow",
            )
        )


def render_setup_summary(install_path: Path, timezone: str, selected_services: set[str], global_user: str, global_email: str):
    service_list = ", ".join(sorted(service.title() for service in selected_services))
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold cyan", justify="right")
    summary.add_column(style="white")
    summary.add_row("Install Path", str(install_path))
    summary.add_row("Timezone", timezone)
    summary.add_row("Admin User", global_user)
    summary.add_row("Admin Email", global_email)
    summary.add_row("Services", service_list)
    return Panel(summary, title="Configuration Summary", border_style="bright_blue", padding=(1, 2))


def render_next_steps_panel(lan_ip: str, selected_services: set[str], include_dashy: bool, include_qbit: bool):
    lines = []
    if include_dashy:
        lines.append(f"[bold cyan]Dashboard[/bold cyan]  http://{lan_ip}:4000")
    if "prowlarr" in selected_services:
        lines.append(f"[bold cyan]Prowlarr[/bold cyan]  http://{lan_ip}:9696")
    if "radarr" in selected_services:
        lines.append(f"[bold cyan]Radarr[/bold cyan]  http://{lan_ip}:7878")
    if "sonarr" in selected_services:
        lines.append(f"[bold cyan]Sonarr[/bold cyan]  http://{lan_ip}:8989")
    if "jellyfin" in selected_services:
        lines.append(f"[bold cyan]Jellyfin[/bold cyan]  http://{lan_ip}:8096")
    if "jellyseerr" in selected_services:
        lines.append(f"[bold cyan]Jellyseerr[/bold cyan]  http://{lan_ip}:5055")
    if include_qbit:
        lines.append(f"[bold cyan]qBittorrent[/bold cyan]  http://{lan_ip}:8080")

    return Panel(
        "\n".join(lines),
        title="Ready",
        subtitle="Open the services you need",
        border_style="green",
        padding=(1, 2),
    )

SERVICE_CHOICES = [
    questionary.Choice("qBittorrent", checked=True, value="qbittorrent"),
    questionary.Choice("Prowlarr", checked=True, value="prowlarr"),
    questionary.Choice("Radarr", checked=True, value="radarr"),
    questionary.Choice("Sonarr", checked=True, value="sonarr"),
    questionary.Choice("Jellyfin", checked=True, value="jellyfin"),
    questionary.Choice("Jellyseerr", checked=True, value="jellyseerr"),
    questionary.Choice("FlareSolverr", checked=True, value="flaresolverr"),
    questionary.Choice("Dashy", checked=True, value="dashy"),
]

# Set up comprehensive file logging
logging.basicConfig(
    filename='arr_installer.log',
    filemode='w',
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
# Silence noisy libraries
logging.getLogger("urllib3").setLevel(logging.WARNING)

def get_lan_ip():
    """Detects the primary LAN IP address of the host machine."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            logging.info(f"Detected LAN IP: {ip}")
            return ip
    except Exception as e:
        logging.warning(f"Failed to detect LAN IP, defaulting to localhost: {e}")
        return "localhost"

def get_timezone_choices():
    choices =[]
    try:
        now = datetime.now()
        for zone in available_timezones():
            try:
                z = ZoneInfo(zone)
                offset = now.astimezone(z).strftime('%z')
                pretty_offset = f"UTC{offset[:3]}:{offset[3:]}"
                display_name = f"({pretty_offset}) {zone}"
                choices.append((offset, display_name, zone))
            except Exception:
                continue
    except Exception:
        pass

    if not choices:
        fallback_zones =[
            "America/Sao_Paulo", "America/New_York", "America/Los_Angeles", 
            "Europe/London", "Europe/Paris", "Asia/Tokyo", "UTC"
        ]
        for zone in fallback_zones:
            choices.append(("+0000", zone, zone))
            
    choices.sort(key=lambda x: x[0])
    return[questionary.Choice(title=c[1], value=c[2]) for c in choices]

def get_user_input():
    console.print(
        Panel.fit(
            "[bold cyan]ARR Stack Installer[/bold cyan]\n[dim]Docker-based media stack bootstrapper with API auto-linking[/dim]",
            border_style="bright_blue",
            padding=(1, 3),
        )
    )
    console.print("[dim]Detailed logs are being written to arr_installer.log[/dim]\n")
    
    default_path = "C:\\Server" if os.name == 'nt' else "/opt/server"
    install_path = questionary.text("Where do you want to install the server?", default=default_path).ask()
    
    tz_choices = get_timezone_choices()
    default_tz = next((c for c in tz_choices if "Sao_Paulo" in c.value), tz_choices[0])

    timezone = questionary.select(
        "Select your Timezone:",
        choices=tz_choices,
        default=default_tz,
        use_indicator=True,
    ).ask()

    selected_services = set(questionary.checkbox(
        "Select the services to install:",
        choices=SERVICE_CHOICES,
        validate=lambda value: True if value else "Select at least one service.",
    ).ask() or [])

    if "jellyseerr" in selected_services:
        selected_services.update({"jellyfin", "radarr", "sonarr"})
    if "flaresolverr" in selected_services:
        selected_services.add("prowlarr")

    include_fs = "flaresolverr" in selected_services
    include_dashy = "dashy" in selected_services
    configure_js = "jellyseerr" in selected_services

    console.print(
        Panel.fit(
            "[bold cyan]Global Credentials[/bold cyan]\n[dim]Applied to Jellyfin, Sonarr, Radarr, and Prowlarr[/dim]",
            border_style="cyan",
        )
    )
    global_user = questionary.text("Admin Username:").ask()
    global_pass = prompt_confirmed_password()
    global_email = questionary.text("Admin Email (used by Jellyseerr/Dashy):", default="admin@example.com").ask()

    console.print("")
    console.print(render_setup_summary(Path(install_path), timezone, selected_services, global_user, global_email))

    logging.info(
        "User Inputs -> Path: %s, TZ: %s, Services: %s, FS: %s, Dashy: %s, JS: %s",
        install_path, timezone, sorted(selected_services), include_fs, include_dashy, configure_js
    )
    return Path(install_path), timezone, selected_services, global_user, global_pass, global_email

def create_folders(base_path: Path, selected_services: set[str]):
    service_dirs = {
        "qbittorrent": "config/qbittorrent",
        "prowlarr": "config/prowlarr",
        "radarr": "config/radarr",
        "sonarr": "config/sonarr",
        "jellyfin": "config/jellyfin",
        "jellyseerr": "config/jellyseerr",
        "dashy": "config/dashy",
    }
    dirs = [path for service, path in service_dirs.items() if service in selected_services]
    if selected_services.intersection({"qbittorrent", "radarr", "sonarr", "jellyfin", "jellyseerr"}):
        dirs.extend(["data/torrents", "data/media/movies", "data/media/tv"])

    for d in dirs:
        (base_path / d).mkdir(parents=True, exist_ok=True)
    logging.info("Folder structure generated/verified successfully.")
    console.print("[green]Folder structure checked[/green]")

def pre_configure_qbittorrent(base_path: Path):
    config_file = base_path / "config/qbittorrent/qBittorrent.conf"
    if not config_file.exists():
        content = """[LegalNotice]
Accepted=true
[BitTorrent]
Session\\DefaultSavePath=/data/torrents
Session\\Port=6881
Session\\TempPath=/data/torrents/temp
[Network]
Cookies=@Invalid()
[Preferences]
WebUI\\Port=8080
WebUI\\UseUPnP=false
WebUI\\LocalHostAuth=false
WebUI\\AuthSubnetWhitelist=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
WebUI\\AuthSubnetWhitelistEnabled=true
"""
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(content)
        logging.info("Pre-configured qBittorrent default configurations.")

def pre_configure_dashy(base_path: Path, selected_services: set[str], lan_ip: str):
    config_file = base_path / "config/dashy/conf.yml"
    if not config_file.exists():
        config_file.parent.mkdir(parents=True, exist_ok=True)
        dashy_items = []
        if "jellyseerr" in selected_services:
            dashy_items.append(("Jellyseerr", f"http://{lan_ip}:5055", "hl-jellyseerr"))
        if "jellyfin" in selected_services:
            dashy_items.append(("Jellyfin", f"http://{lan_ip}:8096", "hl-jellyfin"))
        if "sonarr" in selected_services:
            dashy_items.append(("Sonarr", f"http://{lan_ip}:8989", "hl-sonarr"))
        if "radarr" in selected_services:
            dashy_items.append(("Radarr", f"http://{lan_ip}:7878", "hl-radarr"))
        if "prowlarr" in selected_services:
            dashy_items.append(("Prowlarr", f"http://{lan_ip}:9696", "hl-prowlarr"))
        if "qbittorrent" in selected_services:
            dashy_items.append(("qBittorrent", f"http://{lan_ip}:8080", "hl-qbittorrent"))
        if "flaresolverr" in selected_services:
            dashy_items.append(("FlareSolverr", f"http://{lan_ip}:8191", "fas fa-fire"))

        items_yaml = "".join(
            f"""
      - title: {title}
        url: {url}
        icon: {icon}"""
            for title, url, icon in dashy_items
        )
        content = f"""---
pageInfo:
  title: ARR Stack Dashboard
  description: Welcome to your self-hosted media server
  navLinks:
    - title: GitHub
      path: https://github.com/lissy93/dashy
appConfig:
  theme: dracula
  layout: auto
sections:
  - name: Media & Automation
    icon: fas fa-server
    items:{items_yaml}
"""
        config_file.write_text(content)
        logging.info("Pre-configured Dashy layout.")

def create_docker_compose(base_path: Path, timezone: str, selected_services: set[str]):
    services = "\nservices:\n"
    if "qbittorrent" in selected_services:
        services += f"""
  qbittorrent:
    image: lscr.io/linuxserver/qbittorrent:latest
    container_name: qbittorrent
    environment:
      - PUID=1000
      - PGID=1000
      - TZ={timezone}
      - WEBUI_PORT=8080
    volumes:
      - ./config/qbittorrent:/config
      - ./data:/data
    ports:
      - 8080:8080
      - 6881:6881
      - 6881:6881/udp
    restart: unless-stopped
"""
    if "prowlarr" in selected_services:
        services += f"""
  prowlarr:
    image: lscr.io/linuxserver/prowlarr:latest
    container_name: prowlarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ={timezone}
    volumes:
      - ./config/prowlarr:/config
    ports:
      - 9696:9696
    restart: unless-stopped
"""
    if "radarr" in selected_services:
        services += f"""
  radarr:
    image: lscr.io/linuxserver/radarr:latest
    container_name: radarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ={timezone}
    volumes:
      - ./config/radarr:/config
      - ./data:/data
    ports:
      - 7878:7878
    restart: unless-stopped
"""
    if "sonarr" in selected_services:
        services += f"""
  sonarr:
    image: lscr.io/linuxserver/sonarr:latest
    container_name: sonarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ={timezone}
    volumes:
      - ./config/sonarr:/config
      - ./data:/data
    ports:
      - 8989:8989
    restart: unless-stopped
"""
    if "jellyfin" in selected_services:
        services += f"""
  jellyfin:
    image: lscr.io/linuxserver/jellyfin:latest
    container_name: jellyfin
    environment:
      - PUID=1000
      - PGID=1000
      - TZ={timezone}
    volumes:
      - ./config/jellyfin:/config
      - ./data/media:/data/media
    ports:
      - 8096:8096
    restart: unless-stopped
"""
    if "jellyseerr" in selected_services:
        services += f"""
  seerr:
    image: ghcr.io/seerr-team/seerr:latest
    container_name: seerr
    init: true
    environment:
      - LOG_LEVEL=debug
      - TZ={timezone}
    volumes:
      - ./config/jellyseerr:/app/config
    ports:
      - 5055:5055
    restart: unless-stopped
"""
    if "flaresolverr" in selected_services:
        services += f"""
  flaresolverr:
    image: flaresolverr/flaresolverr:latest
    container_name: flaresolverr
    environment:
      - LOG_LEVEL=info
      - LOG_HTML=false
      - CAPTCHA_SOLVER=none
      - TZ={timezone}
    ports:
      - 8191:8191
    restart: unless-stopped
"""
    if "dashy" in selected_services:
        services += f"""
  dashy:
    image: lissy93/dashy:latest
    container_name: dashy
    environment:
      - TZ={timezone}
    volumes:
      - ./config/dashy/conf.yml:/app/user-data/conf.yml
    ports:
      - 4000:8080
    restart: unless-stopped
"""
    (base_path / "docker-compose.yml").write_text(services)
    logging.info("Created docker-compose.yml file successfully.")
    console.print("[green]Docker Compose file created[/green]")

def run_docker(base_path: Path):
    console.print(Panel.fit("[bold cyan]Launching Containers[/bold cyan]", border_style="cyan"))
    console.print("[yellow]Starting Docker containers...[/yellow]")
    logging.info("Running docker compose up -d...")
    try:
        res = subprocess.run(["docker", "compose", "up", "-d"], cwd=base_path, check=True, capture_output=True, text=True)
        logging.debug(f"Docker Compose Stdout:\n{res.stdout}")
        logging.debug(f"Docker Compose Stderr:\n{res.stderr}")
        console.print("[green]Docker stack is running[/green]")
    except subprocess.CalledProcessError as e:
        logging.error(f"Docker Compose up failed with exit code {e.returncode}.")
        logging.error(f"Stderr:\n{e.stderr}")
        error_msg = e.stderr or ""
        if "Conflict" in error_msg or "already in use" in error_msg:
            console.print("\n[bold red]Conflict Detected![/bold red] Containers exist.")
            if questionary.confirm("Remove existing containers to proceed? (Data remains safe)", default=True).ask():
                logging.info("User elected to run docker compose down.")
                down_res = subprocess.run(["docker", "compose", "down"], cwd=base_path, check=False, capture_output=True, text=True)
                logging.debug(f"Docker Compose down stderr:\n{down_res.stderr}")
                try:
                    up_res = subprocess.run(["docker", "compose", "up", "-d"], cwd=base_path, check=True, capture_output=True, text=True)
                    logging.debug(f"Docker Compose up (retry) stderr:\n{up_res.stderr}")
                    console.print("[green]Docker stack is running[/green]")
                except subprocess.CalledProcessError as e2:
                    logging.error(f"Failed again on retry: {e2.stderr}")
                    console.print(f"[red]Failed again: {e2.stderr}[/red]")
                    sys.exit(1)
            else:
                logging.warning("User aborted during container conflict.")
                sys.exit(1)
        else:
            console.print(f"[bold red]Docker Error:[/bold red] Check arr_installer.log for details.")
            sys.exit(1)

def wait_for_app_and_get_key(app_name: str, port: int) -> str:
    key = None
    logging.info(f"[{app_name}] Extracting API Key...")
    for _ in range(45):
        try:
            out = subprocess.check_output(["docker", "exec", app_name, "cat", "/config/config.xml"], stderr=subprocess.DEVNULL)
            tree = ET.fromstring(out)
            found_key = tree.find("ApiKey").text
            if found_key:
                key = found_key
                break
        except Exception:
            pass
        time.sleep(2)
        
    if not key:
        logging.error(f"[{app_name}] Timed out waiting for config.xml API Key extraction.")
        return None
        
    logging.info(f"[{app_name}] Found API Key. Waiting for API readiness on port {port}...")
    headers = {"X-Api-Key": key}
    test_url = f"http://localhost:{port}/api/v1/system/status" if app_name == "prowlarr" else f"http://localhost:{port}/api/v3/system/status"

    for _ in range(30):
        try:
            res = requests.get(test_url, headers=headers, timeout=2)
            if res.status_code == 200:
                logging.info(f"[{app_name}] API is Online and ready.")
                return key
        except Exception:
            pass
        time.sleep(2)
            
    logging.warning(f"[{app_name}] Timed out waiting for API readiness, but returning key anyway.")
    return key

def wait_for_jellyseerr_and_get_key() -> str:
    logging.info("[Jellyseerr] Waiting for public settings endpoint...")
    key = None
    last_status = None
    last_error = None

    for _ in range(120):
        try:
            res = requests.get("http://localhost:5055/api/v1/settings/public", timeout=3)
            last_status = res.status_code
            if res.status_code == 200:
                try:
                    out = subprocess.check_output(
                        ["docker", "exec", "seerr", "cat", "/app/config/settings.json"],
                        stderr=subprocess.DEVNULL,
                    )
                    settings = json.loads(out)
                    key = settings.get("apiKey")
                except Exception:
                    # First boot can expose the public API before persisting an API key.
                    key = None

                logging.info(
                    "[Jellyseerr] Public API is Online. initialized=%s, apiKeyPresent=%s",
                    res.json().get("initialized", False),
                    bool(key),
                )
                return key
        except Exception as e:
            last_error = e
        time.sleep(2)

    logging.error(
        "[Jellyseerr] Timed out waiting for public settings endpoint. Last status=%s Last error=%s",
        last_status,
        last_error,
    )
    return None

def set_servarr_credentials(app_name: str, port: int, api_key: str, username: str, password: str, version="v3"):
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    url = f"http://localhost:{port}/api/{version}/config/host"
    logging.info(f"[{app_name}] Configuring credentials via API...")
    # Retry loop to handle RemoteDisconnected during app self-restart
    res = None
    for attempt in range(20):
        try:
            res = requests.get(url, headers=headers, timeout=5)
            break
        except Exception as e:
            logging.warning(f"[{app_name}] GET attempt {attempt+1} failed: {e}. Retrying...")
            time.sleep(5)
    
    if res is None:
        logging.error(f"[{app_name}] All GET attempts failed.")
        return False, "Req Error"

    try:
        if res.status_code == 200:
            config = res.json()
            config["authenticationMethod"] = "forms"
            config["username"] = username
            config["password"] = password
            config["passwordConfirmation"] = password           
            put_url = f"{url}/{config.get('id', 1)}"
            put_res = requests.put(put_url, headers=headers, json=config, timeout=5)
            
            if put_res.status_code in (200, 201, 202):
                logging.info(f"[{app_name}] Successfully set credentials.")
                return True, ""
            
            logging.error(f"[{app_name}] Failed to PUT host config. HTTP {put_res.status_code}: {put_res.text}")
            return False, f"HTTP {put_res.status_code}"
            
        logging.error(f"[{app_name}] Failed to GET host config. HTTP {res.status_code}: {res.text}")
        return False, f"GET: {res.status_code}"
    except Exception as e:
        logging.exception(f"[{app_name}] Exception during credential setup.")
        return False, "Req Error"


def boot_and_auth_servarr(app_id: str, display_name: str, port: int, version: str, keys: dict, user: str, passwd: str, update_fn):
    update_fn(display_name, "api", progress("Waiting for API"))
    key = wait_for_app_and_get_key(app_id, port)
    if not key:
        update_fn(display_name, "api", failure("Boot failed"))
        return False
    keys[app_id] = key
    update_fn(display_name, "api", success("Online"))
    
    update_fn(display_name, "auth", progress("Applying credentials"))
    auth_ok, msg = set_servarr_credentials(app_id, port, key, user, passwd, version)
    update_fn(display_name, "auth", success("Configured") if auth_ok else failure(f"Failed ({msg})"))
    return True

def boot_and_auth_jellyfin(user: str, passwd: str, update_fn):
    app_name = "Jellyfin"
    update_fn(app_name, "api", progress("Waiting for API"))
    
    ready = False
    logging.info(f"[{app_name}] Waiting for system initialization...")
    for _ in range(45):
        try:
            if requests.get("http://localhost:8096/System/Info/Public", timeout=2).status_code == 200:
                ready = True
                break
        except Exception: pass
        time.sleep(2)
        
    if not ready:
        logging.error(f"[{app_name}] Timed out waiting for API boot.")
        update_fn(app_name, "api", failure("Boot failed"))
        return False
        
    update_fn(app_name, "api", success("Online"))
    update_fn(app_name, "auth", progress("Running setup"))
    
    try:
        info = requests.get("http://localhost:8096/System/Info/Public", timeout=5).json()
        if not info.get("StartupWizardCompleted"):
            logging.info(f"[{app_name}] Waiting for Startup Wizard to become ready...")
            wizard_ready = False
            last_status = None
            last_error = None
            for _ in range(60):
                try:
                    probe = requests.get("http://localhost:8096/Startup/Configuration", timeout=3)
                    last_status = probe.status_code
                    if probe.status_code == 200:
                        wizard_ready = True
                        break
                except Exception as e:
                    last_error = e
                time.sleep(3)
            
            if not wizard_ready:
                logging.error(
                    f"[{app_name}] Wizard API never became ready. Last status={last_status} Last error={last_error}"
                )
                update_fn(app_name, "auth", failure("Wizard timeout"))
                return False

            logging.info(f"[{app_name}] Bypassing Startup Wizard and creating Admin User...")
            conf_res = requests.post("http://localhost:8096/Startup/Configuration", json={"UICulture":"en-US","MetadataCountryCode":"US","MetadataLanguage":"en"}, timeout=5)
            if conf_res.status_code not in (200, 204):
                logging.error(f"[{app_name}] Startup/Configuration failed: {conf_res.status_code}")
                update_fn(app_name, "auth", failure("Config step failed"))
                return False
            time.sleep(2) 
            
            # Jellyfin Quirk: A GET request to /Startup/User MUST be called before POSTing, or else it throws a 500 error.
            try:
                requests.get("http://localhost:8096/Startup/User", timeout=5)
            except Exception as e:
                logging.warning(f"[{app_name}] GET /Startup/User failed: {e}")

            res1 = requests.post("http://localhost:8096/Startup/User", json={"Name": user, "Password": passwd}, timeout=5)
            res2 = requests.post("http://localhost:8096/Startup/Complete", json={}, timeout=5)
            
            if res1.status_code in (200, 204) and res2.status_code in (200, 204):
                logging.info(f"[{app_name}] Setup Complete successful.")
                create_jellyfin_default_libraries(user, passwd)
                update_fn(app_name, "auth", success("Configured"))
                return True
            else:
                logging.error(f"[{app_name}] Failed wizard completion. Res1: {res1.status_code}, Res2: {res2.status_code}")
                update_fn(app_name, "auth", failure(f"HTTP {res1.status_code}|{res2.status_code}"))
                return False
        else:
            logging.info(f"[{app_name}] StartupWizard already completed.")
            create_jellyfin_default_libraries(user, passwd)
            update_fn(app_name, "auth", success("Already configured"))
            return True
    except Exception as e:
        logging.exception(f"[{app_name}] Exception during Jellyfin boot/auth.")
        update_fn(app_name, "auth", failure("Request error"))
        return False

def boot_jellyseerr(keys: dict, update_fn):
    app_id, display_name = "jellyseerr", "Jellyseerr"
    update_fn(display_name, "api", progress("Waiting for API"))
    key = wait_for_jellyseerr_and_get_key()
    if key:
        keys[app_id] = key
        update_fn(display_name, "api", success("Online"))
        update_fn(display_name, "auth", pending("Uses Jellyfin"))
    else:
        update_fn(display_name, "api", failure("Boot failed"))

def boot_jellyseerr_bootstrap(keys: dict, update_fn):
    app_id, display_name = "jellyseerr", "Jellyseerr"
    update_fn(display_name, "api", progress("Waiting for API"))
    key = wait_for_jellyseerr_and_get_key()

    if key is not None:
        keys[app_id] = key
        update_fn(display_name, "api", success("Online"))
        update_fn(display_name, "auth", pending("Uses Jellyfin"))
        return

    try:
        res = requests.get("http://localhost:5055/api/v1/settings/public", timeout=3)
        if res.status_code == 200:
            logging.info("[Jellyseerr] Proceeding without API key; bootstrap mode detected.")
            keys[app_id] = ""
            update_fn(display_name, "api", success("Online"))
            update_fn(display_name, "auth", info("Bootstrap mode"))
            return
    except Exception:
        pass

    update_fn(display_name, "api", failure("Boot failed"))

def configure_prowlarr_app(prowlarr_key, app_name, app_key, app_port):
    url_schema = "http://localhost:9696/api/v1/applications/schema"
    url_post = "http://localhost:9696/api/v1/applications"
    headers = {"X-Api-Key": prowlarr_key, "Content-Type": "application/json"}
    logging.info(f"[Prowlarr] Linking App {app_name}...")
    try:
        existing = requests.get(url_post, headers=headers).json()
        if any(app.get('name', '').lower() == app_name.lower() for app in existing): 
            logging.info(f"[Prowlarr] {app_name} is already linked.")
            return True, ""

        schemas = requests.get(url_schema, headers=headers).json()
        schema = next((s for s in schemas if s.get('implementation', '').lower() == app_name.lower()), None)
        if not schema: 
            logging.error(f"[Prowlarr] Schema for {app_name} not found.")
            return False, "No Schema"

        schema['name'] = app_name.capitalize()
        schema['syncLevel'] = 'fullSync'
        schema['appProfileId'] = 1 

        for field in schema.get('fields', []):
            if field['name'] == 'prowlarrUrl': field['value'] = "http://prowlarr:9696"
            elif field['name'] == 'baseUrl': field['value'] = f"http://{app_name}:{app_port}"
            elif field['name'] == 'apiKey': field['value'] = app_key

        for _ in range(3):
            res = requests.post(url_post, json=schema, headers=headers)
            if res.status_code in (200, 201, 202): 
                logging.info(f"[Prowlarr] Successfully linked {app_name}.")
                return True, ""
            time.sleep(2)
        logging.error(f"[Prowlarr] Failed to link {app_name}. HTTP {res.status_code}: {res.text}")
        return False, f"HTTP {res.status_code}"
    except Exception as e: 
        logging.exception(f"[Prowlarr] Exception linking {app_name}")
        return False, "Req Error"

def configure_prowlarr_flaresolverr(prowlarr_key):
    url_schema = "http://localhost:9696/api/v1/indexerproxy/schema"
    url_post = "http://localhost:9696/api/v1/indexerproxy"
    headers = {"X-Api-Key": prowlarr_key, "Content-Type": "application/json"}
    logging.info("[Prowlarr] Linking FlareSolverr...")
    try:
        existing = requests.get(url_post, headers=headers).json()
        if any(p.get('name') == "FlareSolverr" for p in existing): 
            return True, ""

        schemas = requests.get(url_schema, headers=headers).json()
        schema = next((s for s in schemas if s.get('implementation') == 'FlareSolverr'), None)
        if not schema: return False, "No Schema"

        schema['name'] = "FlareSolverr"
        schema['tags'] =[]
        for field in schema.get('fields',[]):
            if field['name'] == 'host': field['value'] = "http://flaresolverr:8191"

        res = requests.post(url_post, json=schema, headers=headers)
        if res.status_code in (200, 201, 202):
            logging.info("[Prowlarr] Successfully linked FlareSolverr.")
            return True, ""
        logging.error(f"[Prowlarr] Failed to link FlareSolverr. HTTP {res.status_code}: {res.text}")
        return False, f"HTTP {res.status_code}"
    except Exception as e: 
        logging.exception("[Prowlarr] Exception linking FlareSolverr")
        return False, "Req Error"

def configure_download_client(app_name: str, api_key: str, port: int, version: str):
    url_schema = f"http://localhost:{port}/api/{version}/downloadclient/schema"
    url_post = f"http://localhost:{port}/api/{version}/downloadclient"
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    logging.info(f"[{app_name}] Adding qBittorrent Download Client...")
    try:
        existing = requests.get(url_post, headers=headers)
        if existing.status_code == 200 and any(c.get("implementation") == "QBittorrent" for c in existing.json()):
            logging.info(f"[{app_name}] qBittorrent already configured.")
            return True, "Already Exists"

        schema_res = requests.get(url_schema, headers=headers)
        if schema_res.status_code != 200:
            logging.error(f"[{app_name}] Failed to fetch DC Schema: {schema_res.status_code}")
            return False, f"HTTP {schema_res.status_code}"

        schema = next((s for s in schema_res.json() if s.get("implementation") == "QBittorrent"), None)
        if not schema: 
            logging.error(f"[{app_name}] qBittorrent schema not found in app.")
            return False, "No Schema"

        schema["name"] = "qBittorrent"
        schema["enable"] = True
        for field in schema.get("fields",[]):
            name = field.get("name")
            if name == "host": field["value"] = "qbittorrent"
            elif name == "port": field["value"] = 8080
            elif name == "username": field["value"] = ""
            elif name == "password": field["value"] = ""
            elif name == "tvCategory" and app_name in ("sonarr", "prowlarr"): field["value"] = "tv"
            elif name == "movieCategory" and app_name in ("radarr", "prowlarr"): field["value"] = "movies"

        res = requests.post(url_post, json=schema, headers=headers)
        if res.status_code in (200, 201, 202):
            logging.info(f"[{app_name}] qBittorrent Download Client added successfully.")
            return True, ""
        
        logging.error(f"[{app_name}] Failed to post DC config. HTTP {res.status_code}: {res.text}")
        return False, f"HTTP {res.status_code}"
    except Exception as e: 
        logging.exception(f"[{app_name}] Exception adding Download Client.")
        return False, "Req Error"

def get_servarr_defaults(app_name: str, api_key: str, port: int):
    headers = {"X-Api-Key": api_key}
    logging.info(f"[{app_name}] Fetching Root Folders and Profiles for Jellyseerr setup...")
    try:
        profiles = requests.get(f"http://localhost:{port}/api/v3/qualityprofile", headers=headers, timeout=5).json()
        root_folders = requests.get(f"http://localhost:{port}/api/v3/rootfolder", headers=headers, timeout=5).json()
        
        default_profile = profiles[0] if profiles else {"id": 1, "name": "Any"}
        desired_path = "/data/media/movies" if app_name == "radarr" else "/data/media/tv"
        default_root = next((folder for folder in root_folders if folder.get("path") == desired_path), None)
        if not default_root and root_folders: default_root = root_folders[0]

        defaults = {
            "profile_id": default_profile.get("id", 1),
            "profile_name": default_profile.get("name", "Any"),
            "root_folder": default_root.get("path", desired_path) if default_root else desired_path,
        }

        if app_name == "sonarr":
            res = requests.get(f"http://localhost:{port}/api/v3/languageprofile", headers=headers, timeout=5)
            lp = res.json() if res.status_code == 200 else []
            defaults["language_profile_id"] = lp[0].get("id", 1) if lp else 1

        return defaults
    except Exception as e:
        logging.exception(f"[{app_name}] Error fetching defaults, returning fallbacks.")
        fallback = {"profile_id": 1, "profile_name": "Any", "root_folder": "/data/media/movies" if app_name == "radarr" else "/data/media/tv"}
        if app_name == "sonarr": fallback["language_profile_id"] = 1
        return fallback

def get_jellyfin_libraries(username: str, password: str):
    auth_headers = {
        "Content-Type": "application/json",
        "X-Emby-Authorization": 'MediaBrowser Client="ARR Installer", Device="ARR Installer", DeviceId="arr-installer", Version="1.0.0"',
    }
    logging.info("[Jellyfin] Connecting to fetch libraries for Jellyseerr...")
    try:
        auth_res = requests.post("http://localhost:8096/Users/AuthenticateByName", headers=auth_headers, json={"Username": username, "Pw": password}, timeout=10)
        if auth_res.status_code != 200: 
            logging.error(f"[Jellyfin] Failed to authenticate to get libraries. HTTP {auth_res.status_code}")
            return[]
            
        auth_data = auth_res.json()
        user_id = auth_data.get("User", {}).get("Id")
        token = auth_data.get("AccessToken")

        views_res = requests.get(f"http://localhost:8096/Users/{user_id}/Views", headers={"X-Emby-Token": token}, timeout=10)
        if views_res.status_code != 200: 
            logging.error(f"[Jellyfin] Failed to fetch Views. HTTP {views_res.status_code}")
            return []
        
        libraries =[item.get("Name") for item in views_res.json().get("Items", []) if item.get("CollectionType") in {"movies", "tvshows"}]
        logging.info(f"[Jellyfin] Found libraries: {libraries}")
        return libraries
    except Exception as e: 
        logging.exception("[Jellyfin] Exception fetching libraries.")
        return[]

def create_jellyfin_default_libraries(username: str, password: str):
    auth_headers = {
        "Content-Type": "application/json",
        "X-Emby-Authorization": 'MediaBrowser Client="ARR Installer", Device="ARR Installer", DeviceId="arr-installer", Version="1.0.0"',
    }
    desired_libraries = [
        {"name": "Movies", "collection_type": "movies", "path": "/data/media/movies"},
        {"name": "TV Shows", "collection_type": "tvshows", "path": "/data/media/tv"},
    ]

    logging.info("[Jellyfin] Ensuring default libraries exist...")
    try:
        auth_res = requests.post(
            "http://localhost:8096/Users/AuthenticateByName",
            headers=auth_headers,
            json={"Username": username, "Pw": password},
            timeout=10,
        )
        if auth_res.status_code != 200:
            logging.error(f"[Jellyfin] Failed to authenticate to create libraries. HTTP {auth_res.status_code}")
            return False

        token = auth_res.json().get("AccessToken")
        if not token:
            logging.error("[Jellyfin] No access token returned while creating libraries.")
            return False

        headers = {"X-Emby-Token": token}
        existing_names = set()
        existing_paths = set()
        try:
            existing_res = requests.get("http://localhost:8096/Library/VirtualFolders", headers=headers, timeout=10)
            if existing_res.status_code == 200:
                for folder in existing_res.json():
                    if folder.get("Name"):
                        existing_names.add(folder["Name"])
                    for location in folder.get("Locations", []) or []:
                        existing_paths.add(location)
        except Exception:
            logging.warning("[Jellyfin] Could not enumerate existing virtual folders before creation.")

        created_any = False
        for library in desired_libraries:
            if library["name"] in existing_names or library["path"] in existing_paths:
                continue

            create_res = requests.post(
                "http://localhost:8096/Library/VirtualFolders",
                headers=headers,
                params={
                    "name": library["name"],
                    "collectionType": library["collection_type"],
                    "paths": library["path"],
                    "refreshLibrary": "true",
                },
                timeout=15,
            )
            if create_res.status_code not in (200, 204):
                logging.error(
                    f"[Jellyfin] Failed creating library {library['name']}. HTTP {create_res.status_code}: {create_res.text}"
                )
                return False

            logging.info(f"[Jellyfin] Created library {library['name']} at {library['path']}.")
            created_any = True

        if created_any:
            time.sleep(2)
        return True
    except Exception:
        logging.exception("[Jellyfin] Exception creating default libraries.")
        return False

def ensure_servarr_root_folder(app_name: str, api_key: str, port: int, path: str):
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    logging.info(f"[{app_name}] Ensuring root folder exists: {path}")
    try:
        root_res = requests.get(f"http://localhost:{port}/api/v3/rootfolder", headers=headers, timeout=10)
        if root_res.status_code != 200:
            logging.error(f"[{app_name}] Failed to fetch root folders. HTTP {root_res.status_code}: {root_res.text}")
            return False

        root_folders = root_res.json()
        if any(folder.get("path") == path for folder in root_folders):
            return True

        create_res = requests.post(
            f"http://localhost:{port}/api/v3/rootfolder",
            headers=headers,
            json={"path": path},
            timeout=10,
        )
        if create_res.status_code in (200, 201):
            logging.info(f"[{app_name}] Created root folder entry: {path}")
            return True

        logging.error(f"[{app_name}] Failed creating root folder {path}. HTTP {create_res.status_code}: {create_res.text}")
        return False
    except Exception:
        logging.exception(f"[{app_name}] Exception ensuring root folder {path}.")
        return False

def create_jellyseerr_session(jellyfin_config: dict, lan_ip: str):
    logging.info("[Jellyseerr] Creating authenticated session via Jellyfin login...")
    session = requests.Session()
    payload = {
        "username": jellyfin_config["username"],
        "password": jellyfin_config["password"],
        "hostname": lan_ip,
        "port": 8096,
        "useSsl": False,
        "urlBase": "",
        "email": jellyfin_config["email"],
        "serverType": 2,
    }

    res = session.post("http://localhost:5055/api/v1/auth/jellyfin", json=payload, timeout=15)
    if res.status_code != 200:
        logging.error(f"[Jellyseerr] Jellyfin auth bootstrap failed. HTTP {res.status_code}: {res.text}")
        return None

    if "connect.sid" not in session.cookies.get_dict():
        logging.error("[Jellyseerr] Jellyfin auth did not return a session cookie.")
        return None

    return session

def configure_jellyseerr(jellyseerr_key: str, jellyfin_config: dict, radarr_key: str, sonarr_key: str, lan_ip: str):
    logging.info("[Jellyseerr] Injecting server configurations...")
    try:
        public_res = requests.get("http://localhost:5055/api/v1/settings/public", timeout=5)
        initialized = public_res.status_code == 200 and public_res.json().get("initialized", False)
    except Exception: initialized = False

    ensure_servarr_root_folder("radarr", radarr_key, 7878, "/data/media/movies")
    ensure_servarr_root_folder("sonarr", sonarr_key, 8989, "/data/media/tv")

    radarr_defaults = get_servarr_defaults("radarr", radarr_key, 7878)
    sonarr_defaults = get_servarr_defaults("sonarr", sonarr_key, 8989)
    create_jellyfin_default_libraries(jellyfin_config["username"], jellyfin_config["password"])
    libraries = get_jellyfin_libraries(jellyfin_config["username"], jellyfin_config["password"])

    jellyfin_url = f"http://{lan_ip}:8096"
    session = create_jellyseerr_session(jellyfin_config, lan_ip)
    if session is None:
        return False, "Auth Err"

    def session_post(url: str, payload: Optional[dict], label: str):
        res = session.post(url, json=payload, timeout=15)
        if res.status_code not in (200, 201, 204):
            logging.error(f"[Jellyseerr] {label} failed. HTTP {res.status_code}: {res.text}")
        return res

    def session_get(url: str, params: Optional[dict], label: str):
        res = session.get(url, params=params, timeout=15)
        if res.status_code not in (200, 201, 204):
            logging.error(f"[Jellyseerr] {label} failed. HTTP {res.status_code}: {res.text}")
        return res

    jellyfin_payload = {
        "hostname": jellyfin_url,
        "externalHostname": jellyfin_url,
        "adminUser": jellyfin_config["username"],
        "adminPass": jellyfin_config["password"],
    }
    j_res = session_post("http://localhost:5055/api/v1/settings/jellyfin", jellyfin_payload, "Jellyfin settings")
    if j_res.status_code not in (200, 201):
        return False, f"JF Err: {j_res.status_code}"

    if libraries:
        sync_res = session_get("http://localhost:5055/api/v1/settings/jellyfin/library", {"sync": "true"}, "Jellyfin library sync")
        if sync_res.status_code == 200:
            available_libraries = sync_res.json()
            enable_ids = []
            desired_names = set(libraries)
            for library in available_libraries:
                if library.get("name") in desired_names and library.get("id"):
                    enable_ids.append(str(library["id"]))

            if enable_ids:
                enable_res = session_get(
                    "http://localhost:5055/api/v1/settings/jellyfin/library",
                    {"enable": ",".join(enable_ids)},
                    "Jellyfin library enable",
                )
                if enable_res.status_code not in (200, 204):
                    return False, f"JF Lib Err: {enable_res.status_code}"

    radarr_payload = {
        "name": "Radarr", "hostname": "radarr", "port": 7878, "apiKey": radarr_key, "useSsl": False, "baseUrl": "",
        "activeProfileId": radarr_defaults["profile_id"], "activeProfileName": radarr_defaults["profile_name"],
        "activeDirectory": radarr_defaults["root_folder"], "is4k": False, "minimumAvailability": "released",
        "isDefault": True, "externalUrl": f"http://{lan_ip}:7878", "syncEnabled": True, "preventSearch": False,
    }
    rad_res = session_post("http://localhost:5055/api/v1/settings/radarr", radarr_payload, "Radarr settings")
    if rad_res.status_code not in (200, 201): 
        return False, f"Radarr Err: {rad_res.status_code}"

    sonarr_payload = {
        "name": "Sonarr", "hostname": "sonarr", "port": 8989, "apiKey": sonarr_key, "useSsl": False, "baseUrl": "",
        "activeProfileId": sonarr_defaults["profile_id"], "activeProfileName": sonarr_defaults["profile_name"],
        "activeDirectory": sonarr_defaults["root_folder"], "activeLanguageProfileId": sonarr_defaults["language_profile_id"],
        "activeAnimeProfileId": sonarr_defaults["profile_id"], "activeAnimeProfileName": sonarr_defaults["profile_name"],
        "activeAnimeDirectory": sonarr_defaults["root_folder"], "activeAnimeLanguageProfileId": sonarr_defaults["language_profile_id"],
        "is4k": False, "enableSeasonFolders": True, "isDefault": True, "externalUrl": f"http://{lan_ip}:8989", "syncEnabled": True, "preventSearch": False,
    }
    son_res = session_post("http://localhost:5055/api/v1/settings/sonarr", sonarr_payload, "Sonarr settings")
    if son_res.status_code not in (200, 201): 
        return False, f"Sonarr Err: {son_res.status_code}"

    if not initialized:
        for payload in (None, {}, {"applicationTitle": "Jellyseerr", "applicationUrl": f"http://{lan_ip}:5055"}):
            init_res = session_post("http://localhost:5055/api/v1/settings/initialize", payload, "Initialization")
            if init_res.status_code in (200, 201, 204):
                initialized = True
                break
        if not initialized: 
            logging.error(f"[Jellyseerr] Failed to finalize initialization request.")
            return False, "Init Err"

    logging.info("[Jellyseerr] Jellyseerr fully configured.")
    return True, ""

def main(verbose=False, debug=False):
    logging.info("--- Starting Installer Script Session ---")
    (install_path, timezone, selected_services,
     global_user, global_pass, global_email) = get_user_input()

    include_fs = "flaresolverr" in selected_services
    include_dashy = "dashy" in selected_services
    configure_js = "jellyseerr" in selected_services
    include_qbit = "qbittorrent" in selected_services

    lan_ip = get_lan_ip()

    create_folders(install_path, selected_services)
    if include_qbit:
        pre_configure_qbittorrent(install_path)
    if include_dashy:
        pre_configure_dashy(install_path, selected_services, lan_ip)

    create_docker_compose(install_path, timezone, selected_services)
    run_docker(install_path)

    console.print("")
    console.print(
        Panel.fit(
            "[bold cyan]Provisioning Services[/bold cyan]\n[dim]Waiting for containers, APIs, and cross-service setup. This usually takes 30 to 90 seconds.[/dim]",
            border_style="bright_blue",
        )
    )

    status_data = {}
    if "prowlarr" in selected_services:
        status_data["Prowlarr"] = {"url": f"http://{lan_ip}:9696", "api": pending("Queued"), "auth": pending("Queued"), "link": pending("Queued")}
    if "sonarr" in selected_services:
        status_data["Sonarr"] = {"url": f"http://{lan_ip}:8989", "api": pending("Queued"), "auth": pending("Queued"), "link": pending("Queued")}
    if "radarr" in selected_services:
        status_data["Radarr"] = {"url": f"http://{lan_ip}:7878", "api": pending("Queued"), "auth": pending("Queued"), "link": pending("Queued")}
    if "jellyfin" in selected_services:
        status_data["Jellyfin"] = {"url": f"http://{lan_ip}:8096", "api": pending("Queued"), "auth": pending("Queued"), "link": pending("N/A")}
    if configure_js:
        status_data["Jellyseerr"] = {"url": f"http://{lan_ip}:5055", "api": pending("Queued"), "auth": pending("Uses Jellyfin"), "link": pending("Queued")}
    if include_fs:
        status_data["FlareSolverr"] = {"url": f"http://{lan_ip}:8191", "api": progress("Starting"), "auth": pending("N/A"), "link": pending("Queued")}
    if include_qbit:
        status_data["qBittorrent"] = {"url": f"http://{lan_ip}:8080", "api": success("Online"), "auth": info("LAN bypass"), "link": pending("N/A")}
    if include_dashy:
        status_data["Dashy"] = {"url": f"http://{lan_ip}:4000", "api": success("Online"), "auth": pending("N/A"), "link": success("Dashboard ready")}

    def generate_table():
        table = Table(
            title=f"Setup Progress  {timezone}",
            title_style="bold bright_blue",
            box=box.ROUNDED,
            border_style="bright_blue",
            header_style="bold white",
            row_styles=["none", "dim"],
            pad_edge=False,
        )
        table.add_column("Application", style="bold cyan", min_width=12)
        table.add_column("Local URL", style="magenta", min_width=22)
        table.add_column("API / Boot", style="white", min_width=18)
        table.add_column("Auth Config", style="white", min_width=18)
        table.add_column("App Linking", style="white", min_width=18)
        for app, data in status_data.items():
            table.add_row(
                app,
                data["url"],
                render_status(data["api"]),
                render_status(data["auth"]),
                render_status(data["link"]),
            )
        return table

    keys = {}
    jellyfin_ready = False

    with Live(generate_table(), refresh_per_second=4) as live:
        def update_status(app, col, val):
            status_data[app][col] = val
            live.update(generate_table())

        logging.info("Starting Phase 1: Boot and Initialization Threading...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = {}
            if "prowlarr" in selected_services:
                futures["prowlarr"] = executor.submit(boot_and_auth_servarr, "prowlarr", "Prowlarr", 9696, "v1", keys, global_user, global_pass, update_status)
            if "sonarr" in selected_services:
                futures["sonarr"] = executor.submit(boot_and_auth_servarr, "sonarr", "Sonarr", 8989, "v3", keys, global_user, global_pass, update_status)
            if "radarr" in selected_services:
                futures["radarr"] = executor.submit(boot_and_auth_servarr, "radarr", "Radarr", 7878, "v3", keys, global_user, global_pass, update_status)
            if "jellyfin" in selected_services:
                futures["jellyfin"] = executor.submit(boot_and_auth_jellyfin, global_user, global_pass, update_status)
            if configure_js:
                futures["jellyseerr"] = executor.submit(boot_jellyseerr_bootstrap, keys, update_status)
            if include_fs:
                def check_fs():
                    update_status("FlareSolverr", "api", progress("Waiting for API"))
                    for _ in range(30):
                        try:
                            if requests.get("http://localhost:8191/", timeout=2).status_code == 200:
                                update_status("FlareSolverr", "api", success("Online"))
                                return
                        except Exception:
                            pass
                        time.sleep(2)
                    update_status("FlareSolverr", "api", failure("Boot failed"))
                futures["flaresolverr"] = executor.submit(check_fs)

            for name, future in futures.items():
                result = future.result()
                if name == "jellyfin":
                    jellyfin_ready = result

        logging.info("Starting Phase 2: Inter-App Linking...")
        if "prowlarr" in keys:
            update_status("Prowlarr", "link", progress("Linking services"))
            linked_all = True

            if "sonarr" in keys:
                ok, msg = configure_prowlarr_app(keys["prowlarr"], "sonarr", keys["sonarr"], 8989)
                linked_all &= ok
                status_str = "Linked" if ok else f"Failed ({msg})"
                if include_qbit:
                    dc_ok, dc_msg = configure_download_client("sonarr", keys["sonarr"], 8989, "v3")
                    status_str += " | qBittorrent ready" if dc_ok else f" | qBittorrent failed ({dc_msg})"
                update_status("Sonarr", "link", success(status_str) if ok else failure(status_str))

            if "radarr" in keys:
                ok, msg = configure_prowlarr_app(keys["prowlarr"], "radarr", keys["radarr"], 7878)
                linked_all &= ok
                status_str = "Linked" if ok else f"Failed ({msg})"
                if include_qbit:
                    dc_ok, dc_msg = configure_download_client("radarr", keys["radarr"], 7878, "v3")
                    status_str += " | qBittorrent ready" if dc_ok else f" | qBittorrent failed ({dc_msg})"
                update_status("Radarr", "link", success(status_str) if ok else failure(status_str))

            if include_fs:
                ok, msg = configure_prowlarr_flaresolverr(keys["prowlarr"])
                linked_all &= ok
                update_status("FlareSolverr", "link", success("Linked to Prowlarr") if ok else failure(f"Failed ({msg})"))

            dc_ok_prowlarr = True
            if include_qbit:
                dc_ok_prowlarr, _ = configure_download_client("prowlarr", keys["prowlarr"], 9696, "v1")

            if linked_all and dc_ok_prowlarr:
                update_status("Prowlarr", "link", success("Linked | qBittorrent ready") if include_qbit else success("Linked"))
            else:
                update_status("Prowlarr", "link", warning("Partial or failed"))

        if configure_js and "jellyseerr" in keys and jellyfin_ready and "radarr" in keys and "sonarr" in keys:
            update_status("Jellyseerr", "link", progress("Configuring"))
            js_conf = {"username": global_user, "password": global_pass, "email": global_email}
            js_ok, msg = configure_jellyseerr(keys["jellyseerr"], js_conf, keys["radarr"], keys["sonarr"], lan_ip)
            update_status("Jellyseerr", "link", success("Linked") if js_ok else failure(f"Failed ({msg})"))
        elif configure_js:
            update_status("Jellyseerr", "link", failure("Missing dependencies"))

        time.sleep(1)
        logging.info("--- Installer Script Session Complete ---")

    console.print("")
    console.print(render_next_steps_panel(lan_ip, selected_services, include_dashy, include_qbit))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARR Stack Installer")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging (Currently routed to file)")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging (Currently routed to file)")
    args = parser.parse_args()
    
    main(verbose=args.verbose, debug=args.debug)


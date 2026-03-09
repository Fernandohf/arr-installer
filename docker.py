# Docker operations and compose generation
import subprocess
import logging
import questionary
from pathlib import Path
from typing import Optional
from ui import console, Panel
from config import SERVICE_PORTS

def create_folders(base_path: Path, selected_services: set[str]):
    from config import SERVICE_DIRS

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

def create_docker_compose(base_path: Path, timezone: str, selected_services: set[str]):
    services = f"""version: '3.8'

services:
"""
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
      - ./data/torrents:/data/torrents
    ports:
      - 8080:8080
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
                    import sys
                    sys.exit(1)
            else:
                logging.warning("User aborted during container conflict.")
                import sys
                sys.exit(1)
        else:
            console.print(f"[bold red]Docker Error:[/bold red] Check arr_installer.log for details.")
            import sys
            sys.exit(1)
import os
import time
import subprocess
import requests
import xml.etree.ElementTree as ET
import questionary
import sys
import argparse
import socket

try:
    import tzdata
except ImportError:
    pass

from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

def get_lan_ip():
    """Detects the primary LAN IP address of the host machine."""
    try:
        # We don't actually need to send data or successfully connect.
        # This just forces the OS to figure out the primary routing interface.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
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
    return [questionary.Choice(title=c[1], value=c[2]) for c in choices]

def get_user_input():
    console.print(Panel.fit("[bold cyan]ARR Stack Installer (Auto-Cleanup Edition)[/bold cyan]", border_style="cyan"))
    
    default_path = "C:\\Server"
    install_path = questionary.text("Where do you want to install the server?", default=default_path).ask()
    
    tz_choices = get_timezone_choices()
    default_tz = next((c for c in tz_choices if "Sao_Paulo" in c.value), tz_choices[0])

    timezone = questionary.select(
        "Select your Timezone:",
        choices=tz_choices,
        default=default_tz,
        use_indicator=True,
    ).ask()

    include_fs = questionary.confirm("Include FlareSolverr?", default=True).ask()
    include_dashy = questionary.confirm("Include Dashy (Dashboard)?", default=True).ask()
    
    return Path(install_path), timezone, include_fs, include_dashy

def create_folders(base_path: Path, include_dashy: bool):
    dirs =[
        "config/qbittorrent", "config/prowlarr", "config/radarr",
        "config/sonarr", "config/jellyfin", "config/jellyseerr",
        "data/torrents", "data/media/movies", "data/media/tv"
    ]
    if include_dashy:
        dirs.append("config/dashy")
        
    for d in dirs:
        (base_path / d).mkdir(parents=True, exist_ok=True)
    console.print(f"[green]✓ Folder structure checked[/green]")

def pre_configure_qbittorrent(base_path: Path):
    config_file = base_path / "config/qbittorrent/qBittorrent.conf"
    if not config_file.exists():
        content = """[LegalNotice]
Accepted=true[BitTorrent]
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

def pre_configure_dashy(base_path: Path, include_fs: bool, lan_ip: str):
    config_file = base_path / "config/dashy/conf.yml"
    if not config_file.exists():
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        items_yaml = f"""
      - title: Jellyseerr
        url: http://{lan_ip}:5055
        icon: hl-jellyseerr
      - title: Jellyfin
        url: http://{lan_ip}:8096
        icon: hl-jellyfin
      - title: Sonarr
        url: http://{lan_ip}:8989
        icon: hl-sonarr
      - title: Radarr
        url: http://{lan_ip}:7878
        icon: hl-radarr
      - title: Prowlarr
        url: http://{lan_ip}:9696
        icon: hl-prowlarr
      - title: qBittorrent
        url: http://{lan_ip}:8080
        icon: hl-qbittorrent"""
        
        if include_fs:
            items_yaml += f"""
      - title: FlareSolverr
        url: http://{lan_ip}:8191
        icon: fas fa-fire"""

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

def create_docker_compose(base_path: Path, timezone: str, include_fs: bool, include_dashy: bool):
    services = f"""
services:
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

  jellyseerr:
    image: fallenbagel/jellyseerr:latest
    container_name: jellyseerr
    environment:
      - LOG_LEVEL=debug
      - TZ={timezone}
    volumes:
      - ./config/jellyseerr:/app/config
    ports:
      - 5055:5055
    restart: unless-stopped
"""
    if include_fs:
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

    if include_dashy:
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
    console.print(f"[green]✓ Docker Compose file created[/green]")

def run_docker(base_path: Path, verbose: bool):
    console.print("[yellow]Starting Docker containers...[/yellow]")
    try:
        if verbose: console.print("[dim]Running 'docker compose up -d'[/dim]")
        subprocess.run(["docker", "compose", "up", "-d"], cwd=base_path, check=True, capture_output=True, text=True)
        console.print("[green]✓ Docker stack is running[/green]")
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or ""
        if "Conflict" in error_msg or "already in use" in error_msg:
            console.print("\n[bold red]Conflict Detected![/bold red] Containers exist.")
            if questionary.confirm("Remove existing containers to proceed? (Data remains safe)", default=True).ask():
                subprocess.run(["docker", "compose", "down"], cwd=base_path, check=False, capture_output=not verbose)
                try:
                    subprocess.run(["docker", "compose", "up", "-d"], cwd=base_path, check=True, capture_output=True)
                    console.print("[green]✓ Docker stack is running[/green]")
                except subprocess.CalledProcessError as e2:
                    console.print(f"[red]Failed again: {e2.stderr}[/red]")
                    sys.exit(1)
            else:
                sys.exit(1)
        else:
            console.print(f"[bold red]Docker Error:[/bold red] {error_msg}")
            sys.exit(1)

def wait_for_app_and_get_key(base_path: Path, app_name: str, port: int, verbose: bool, debug: bool = False) -> str:
    config_path = base_path / f"config/{app_name}/config.xml"
    key = None
    
    if verbose or debug: console.print(f"\n[dim]Looking for {app_name} API Key...[/dim]")
    for _ in range(30):
        if config_path.exists():
            try:
                tree = ET.parse(config_path)
                found_key = tree.getroot().find("ApiKey").text
                if found_key:
                    key = found_key
                    break
            except Exception:
                pass
        time.sleep(2)
        
    if not key:
        if debug: console.print(f"[red]Could not find ApiKey for {app_name}.[/red]")
        return None
        
    if verbose or debug: console.print(f"[dim]Waiting for {app_name} API readiness on port {port}...[/dim]")
    
    headers = {"X-Api-Key": key}
    if app_name == "prowlarr":
        test_url = f"http://localhost:{port}/api/v1/system/status"
    elif app_name in ["radarr", "sonarr"]:
        test_url = f"http://localhost:{port}/api/v3/system/status"
    else:
        test_url = f"http://localhost:{port}/"

    for _ in range(45):
        try:
            res = requests.get(test_url, headers=headers, timeout=2)
            if res.status_code == 200:
                if verbose or debug: console.print(f"[dim]{app_name} API is online and fully authenticated.[/dim]")
                return key
            elif debug:
                console.print(f"[dim]{app_name} status check returned HTTP {res.status_code}[/dim]")
        except requests.ConnectionError:
            pass
        except Exception as e:
            if debug: console.print(f"[dim]Error checking {app_name}: {e}[/dim]")
        time.sleep(2)
            
    if debug: console.print(f"[yellow]Warning: {app_name} API check timed out, attempting to continue anyway...[/yellow]")
    return key

def configure_prowlarr_app(prowlarr_key, app_name, app_key, app_port, verbose, debug=False):
    url_schema = "http://localhost:9696/api/v1/applications/schema"
    url_post = "http://localhost:9696/api/v1/applications"
    headers = {"X-Api-Key": prowlarr_key, "Content-Type": "application/json"}

    try:
        existing = requests.get(url_post, headers=headers).json()
        if any(app.get('name', '').lower() == app_name.lower() for app in existing): 
            return True

        if verbose or debug: console.print(f"\n[dim]Fetching schema to link {app_name}...[/dim]")
        schemas = requests.get(url_schema, headers=headers).json()
        schema = next((s for s in schemas if s.get('implementation', '').lower() == app_name.lower()), None)
        if not schema: 
            if debug: console.print(f"[red]Could not locate schema for {app_name} inside Prowlarr API[/red]")
            return False

        schema['name'] = app_name.capitalize()
        schema['syncLevel'] = 'fullSync'
        schema['appProfileId'] = 1 

        for field in schema.get('fields', []):
            if field['name'] == 'prowlarrUrl': field['value'] = "http://prowlarr:9696"
            elif field['name'] == 'baseUrl': field['value'] = f"http://{app_name}:{app_port}"
            elif field['name'] == 'apiKey': field['value'] = app_key

        res = requests.post(url_post, json=schema, headers=headers)
        if (verbose or debug) and res.status_code not in (200, 201, 202):
            console.print(f"[red]Failed to link {app_name} to Prowlarr. HTTP {res.status_code}: {res.text}[/red]")
        return res.status_code in (200, 201, 202)
    except Exception as e:
        if verbose or debug: console.print(f"[red]Exception linking {app_name}: {e}[/red]")
        return False

def configure_prowlarr_flaresolverr(prowlarr_key, verbose, debug=False):
    url_schema = "http://localhost:9696/api/v1/indexerproxy/schema"
    url_post = "http://localhost:9696/api/v1/indexerproxy"
    headers = {"X-Api-Key": prowlarr_key, "Content-Type": "application/json"}
    
    try:
        existing = requests.get(url_post, headers=headers).json()
        if any(p.get('name') == "FlareSolverr" for p in existing): return True

        schemas = requests.get(url_schema, headers=headers).json()
        schema = next((s for s in schemas if s.get('implementation') == 'FlareSolverr'), None)
        if not schema: return False

        schema['name'] = "FlareSolverr"
        schema['tags'] =[]
        for field in schema.get('fields', []):
            if field['name'] == 'host': field['value'] = "http://flaresolverr:8191"

        res = requests.post(url_post, json=schema, headers=headers)
        if (verbose or debug) and res.status_code not in (200, 201, 202):
            console.print(f"[red]Failed to link FlareSolverr. HTTP {res.status_code}: {res.text}[/red]")
        return res.status_code in (200, 201, 202)
    except Exception as e:
        if verbose or debug: console.print(f"[red]Exception linking FlareSolverr: {e}[/red]")
        return False

def configure_download_client(app_name: str, api_key: str, port: int, version: str, verbose: bool, debug: bool = False):
    url_schema = f"http://localhost:{port}/api/{version}/downloadclient/schema"
    url_post = f"http://localhost:{port}/api/{version}/downloadclient"
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    
    try:
        existing = requests.get(url_post, headers=headers)
        if existing.status_code == 200 and any(c.get("implementation") == "QBittorrent" for c in existing.json()):
            return True

        schemas_res = requests.get(url_schema, headers=headers)
        if schemas_res.status_code != 200: return False

        schema = next((s for s in schemas_res.json() if s.get("implementation") == "QBittorrent"), None)
        if not schema: return False

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
        if (verbose or debug) and res.status_code not in (200, 201, 202):
            console.print(f"[red]Failed to add DC to {app_name}. HTTP {res.status_code}: {res.text}[/red]")
        return res.status_code in (200, 201, 202)
    except Exception as e:
        if verbose or debug: console.print(f"[red]Exception adding DC to {app_name}: {e}[/red]")
        return False

def main(verbose=False, debug=False):
    install_path, timezone, include_fs, include_dashy = get_user_input()
    
    # Automatically get the primary LAN IP (e.g., 192.168.68.5)
    lan_ip = get_lan_ip()
    if verbose or debug:
        console.print(f"[dim]Detected Host LAN IP: {lan_ip}[/dim]")

    create_folders(install_path, include_dashy)
    
    pre_configure_qbittorrent(install_path)
    if include_dashy:
        pre_configure_dashy(install_path, include_fs, lan_ip)
        
    create_docker_compose(install_path, timezone, include_fs, include_dashy)
    
    run_docker(install_path, verbose)
    
    console.print("\n[bold cyan]Waiting for API Keys and Boot Sequences (Approx 30-90s)...[/bold cyan]")
    
    keys = {}
    status = {
        'sonarr_app': False, 'radarr_app': False, 'fs': False,
        'dc_prowlarr': False, 'dc_sonarr': False, 'dc_radarr': False
    }

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
        
        t1 = progress.add_task("Extracting keys & Waiting for APIs...", total=3)
        keys['Prowlarr'] = wait_for_app_and_get_key(install_path, "prowlarr", 9696, verbose, debug); progress.advance(t1)
        keys['Sonarr']   = wait_for_app_and_get_key(install_path, "sonarr", 8989, verbose, debug); progress.advance(t1)
        keys['Radarr']   = wait_for_app_and_get_key(install_path, "radarr", 7878, verbose, debug); progress.advance(t1)

        if keys['Prowlarr']:
            t2 = progress.add_task("Linking Apps to Prowlarr...", total=3 if include_fs else 2)
            if keys['Sonarr']:
                status['sonarr_app'] = configure_prowlarr_app(keys['Prowlarr'], "sonarr", keys['Sonarr'], 8989, verbose, debug)
            progress.advance(t2)
            if keys['Radarr']:
                status['radarr_app'] = configure_prowlarr_app(keys['Prowlarr'], "radarr", keys['Radarr'], 7878, verbose, debug)
            progress.advance(t2)
            if include_fs:
                status['fs'] = configure_prowlarr_flaresolverr(keys['Prowlarr'], verbose, debug)
                progress.advance(t2)
                
            t3 = progress.add_task("Configuring Download Clients...", total=3)
            status['dc_prowlarr'] = configure_download_client("prowlarr", keys['Prowlarr'], 9696, "v1", verbose, debug)
            progress.advance(t3)
            if keys['Sonarr']:
                status['dc_sonarr'] = configure_download_client("sonarr", keys['Sonarr'], 8989, "v3", verbose, debug)
            progress.advance(t3)
            if keys['Radarr']:
                status['dc_radarr'] = configure_download_client("radarr", keys['Radarr'], 7878, "v3", verbose, debug)
            progress.advance(t3)

    def s_fmt(success): return "[green]Linked ✓[/green]" if success else "[red]Failed ✗[/red]"

    table = Table(title=f"Setup Complete ({timezone})")
    table.add_column("Application", style="cyan")
    table.add_column("Local URL", style="magenta")
    table.add_column("App Link Status", style="white")
    table.add_column("Download Client Status", style="white")
    
    if include_dashy:
        table.add_row("Dashy", f"http://{lan_ip}:4000", "Dashboard ✓", "N/A")
        
    table.add_row("Prowlarr", f"http://{lan_ip}:9696", "Main Hub", s_fmt(status['dc_prowlarr']))
    table.add_row("Sonarr", f"http://{lan_ip}:8989", s_fmt(status['sonarr_app']), s_fmt(status['dc_sonarr']))
    table.add_row("Radarr", f"http://{lan_ip}:7878", s_fmt(status['radarr_app']), s_fmt(status['dc_radarr']))
    table.add_row("Jellyseerr", f"http://{lan_ip}:5055", "N/A", "N/A")
    table.add_row("Jellyfin", f"http://{lan_ip}:8096", "N/A", "N/A")
    
    if include_fs:
        table.add_row("FlareSolverr", f"http://{lan_ip}:8191", s_fmt(status['fs']), "N/A")
        
    table.add_row("qBittorrent", f"http://{lan_ip}:8080", "N/A", "Host ✓")
    
    console.print(table)
    
    if include_dashy:
        console.print(f"\n[bold yellow]Final Step:[/bold yellow] Open[cyan]http://{lan_ip}:4000[/cyan] to view your new homelab dashboard.")
    else:
        console.print("\n[bold yellow]Final Step:[/bold yellow] Open Prowlarr and add your Indexers.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARR Stack Installer")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging and print exact error JSON payloads")
    args = parser.parse_args()
    
    main(verbose=args.verbose, debug=args.debug)
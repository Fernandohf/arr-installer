#!/usr/bin/env python3
"""
ARR Stack Installer - Docker-based media stack bootstrapper with API auto-linking
"""

import os
import sys
import argparse
import logging
import concurrent.futures
import time
import requests
from pathlib import Path
import questionary
from rich.live import Live
from rich.panel import Panel

# Import our modules
from config import SERVICE_CHOICES
from ui import console, render_next_steps_panel, render_status
from input import get_user_input
from utils import get_lan_ip
from docker import create_folders, create_docker_compose, run_docker
from services.qbittorrent import pre_configure_qbittorrent
from services.dashy import pre_configure_dashy
from services.jellyfin import boot_and_auth_jellyfin
from services.jellyseerr import boot_jellyseerr_bootstrap, configure_jellyseerr
from services.arr_services import boot_and_auth_servarr
from api import (
    configure_prowlarr_app,
    configure_prowlarr_flaresolverr,
    configure_download_client
)

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

def check_prerequisites():
    """Check if Docker is available before proceeding."""
    console.print("[yellow]Checking Docker availability...[/yellow]")

    # Check if Docker is available
    try:
        import subprocess
        result = subprocess.run(["docker", "--version"], capture_output=True, text=True, check=True)
        console.print(f"[green]Docker available: {result.stdout.strip()}[/green]")
    except (subprocess.CalledProcessError, FileNotFoundError):
        console.print("[bold red]Error: Docker is not installed or not available in PATH.[/bold red]")
        console.print("[dim]Please install Docker and ensure it's running before proceeding.[/dim]")
        sys.exit(1)

    # Check if Docker Compose is available
    try:
        result = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, check=True)
        console.print(f"[green]Docker Compose available: {result.stdout.strip()}[/green]")
    except (subprocess.CalledProcessError, FileNotFoundError):
        console.print("[bold red]Error: Docker Compose is not available.[/bold red]")
        console.print("[dim]Please ensure Docker Compose is installed.[/dim]")
        sys.exit(1)

def main(verbose=False, debug=False):
    logging.info("--- Starting Installer Script Session ---")

    check_prerequisites()

    (install_path, timezone, selected_services,
     global_user, global_pass, global_email) = get_user_input()

    # Check if docker-compose.yml already exists
    docker_compose_path = install_path / "docker-compose.yml"
    if docker_compose_path.exists():
        console.print(f"[yellow]Warning: A docker-compose.yml file already exists at {docker_compose_path}[/yellow]")
        if not questionary.confirm("Do you want to overwrite the existing docker-compose.yml file?", default=False).ask():
            console.print("[dim]Installation cancelled by user.[/dim]")
            sys.exit(0)

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
        status_data["Prowlarr"] = {"url": f"http://{lan_ip}:9696", "api": "pending", "auth": "pending", "link": "pending"}
    if "sonarr" in selected_services:
        status_data["Sonarr"] = {"url": f"http://{lan_ip}:8989", "api": "pending", "auth": "pending", "link": "pending"}
    if "radarr" in selected_services:
        status_data["Radarr"] = {"url": f"http://{lan_ip}:7878", "api": "pending", "auth": "pending", "link": "pending"}
    if "jellyfin" in selected_services:
        status_data["Jellyfin"] = {"url": f"http://{lan_ip}:8096", "api": "pending", "auth": "pending", "link": "N/A"}
    if configure_js:
        status_data["Jellyseerr"] = {"url": f"http://{lan_ip}:5055", "api": "pending", "auth": "Uses Jellyfin", "link": "pending"}
    if include_fs:
        status_data["FlareSolverr"] = {"url": f"http://{lan_ip}:8191", "api": "in_progress", "auth": "N/A", "link": "pending"}
    if include_qbit:
        status_data["qBittorrent"] = {"url": f"http://{lan_ip}:8080", "api": "success", "auth": "LAN bypass", "link": "N/A"}
    if include_dashy:
        status_data["Dashy"] = {"url": f"http://{lan_ip}:4000", "api": "success", "auth": "N/A", "link": "Dashboard ready"}

    def generate_table():
        from rich.table import Table, box

        table = Table(
            title=f"Setup Progress  {timezone}",
            title_style="bold bright_blue",
            box=box.ROUNDED,
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
        def update_status(app, col, state_or_val, label=None):
            if label is not None:
                # New format: (app, col, state, label)
                status_data[app][col] = {"state": state_or_val, "label": label}
            else:
                # Old format: (app, col, val)
                status_data[app][col] = state_or_val
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
                    update_status("FlareSolverr", "api", "in_progress", "Waiting for API")
                    for _ in range(30):
                        try:
                            if requests.get("http://localhost:8191/", timeout=2).status_code == 200:
                                update_status("FlareSolverr", "api", "success", "Online")
                                return
                        except Exception:
                            pass
                        time.sleep(2)
                    update_status("FlareSolverr", "api", "error", "Boot failed")
                futures["flaresolverr"] = executor.submit(check_fs)

            for name, future in futures.items():
                result = future.result()
                if name == "jellyfin":
                    jellyfin_ready = result

        logging.info("Starting Phase 2: Inter-App Linking...")
        if "prowlarr" in keys:
            update_status("Prowlarr", "link", "in_progress", "Linking services")
            linked_all = True

            if "sonarr" in keys:
                ok, msg = configure_prowlarr_app(keys["prowlarr"], "sonarr", keys["sonarr"], 8989)
                linked_all &= ok
                status_str = "Linked" if ok else f"Failed ({msg})"
                if include_qbit:
                    dc_ok, dc_msg = configure_download_client("sonarr", keys["sonarr"], 8989, "v3")
                    status_str += " | qBittorrent ready" if dc_ok else f" | qBittorrent failed ({dc_msg})"
                update_status("Sonarr", "link", "success" if ok else "error", status_str)

            if "radarr" in keys:
                ok, msg = configure_prowlarr_app(keys["prowlarr"], "radarr", keys["radarr"], 7878)
                linked_all &= ok
                status_str = "Linked" if ok else f"Failed ({msg})"
                if include_qbit:
                    dc_ok, dc_msg = configure_download_client("radarr", keys["radarr"], 7878, "v3")
                    status_str += " | qBittorrent ready" if dc_ok else f" | qBittorrent failed ({dc_msg})"
                update_status("Radarr", "link", "success" if ok else "error", status_str)

            if include_fs:
                ok, msg = configure_prowlarr_flaresolverr(keys["prowlarr"])
                linked_all &= ok
                update_status("FlareSolverr", "link", "success" if ok else "error", "Linked to Prowlarr" if ok else f"Failed ({msg})")

            dc_ok_prowlarr = True
            if include_qbit:
                dc_ok_prowlarr, _ = configure_download_client("prowlarr", keys["prowlarr"], 9696, "v1")

            if linked_all and dc_ok_prowlarr:
                update_status("Prowlarr", "link", "success", "Linked | qBittorrent ready" if include_qbit else "Linked")
            else:
                update_status("Prowlarr", "link", "warning", "Partial or failed")

        if configure_js and "jellyseerr" in keys and jellyfin_ready and "radarr" in keys and "sonarr" in keys:
            update_status("Jellyseerr", "link", "in_progress", "Configuring")
            js_conf = {"username": global_user, "password": global_pass, "email": global_email}
            js_ok, msg = configure_jellyseerr(keys["jellyseerr"], js_conf, keys["radarr"], keys["sonarr"], lan_ip)
            update_status("Jellyseerr", "link", "success" if js_ok else "error", "Linked" if js_ok else f"Failed ({msg})")
        elif configure_js:
            update_status("Jellyseerr", "link", "error", "Missing dependencies")

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


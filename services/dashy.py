# Dashy configuration
import logging
from pathlib import Path

def pre_configure_dashy(base_path: Path, selected_services: set[str], lan_ip: str):
    config_file = base_path / "config/dashy/conf.yml"
    config_file.parent.mkdir(parents=True, exist_ok=True)

    sections = []

    # Dashboard section
    sections.append("""
pageInfo:
  title: ARR Stack
  description: Self-hosted media stack dashboard
  navLinks:
  - title: GitHub
    path: https://github.com/Fernandohf/arr-installer
  - title: Docs
    path: https://github.com/Fernandohf/arr-installer#readme""")

    # Apps section
    sections.append("""
appConfig:
  theme: colorful
  layout: auto
  iconSize: medium
  language: en

sections:
- name: Media Stack
  icon: fas fa-server
  items:""")

    # Add services based on selection
    items = []
    if "qbittorrent" in selected_services:
        items.append(f"""
  - title: qBittorrent
    description: Torrent client
    icon: fas fa-download
    url: http://{lan_ip}:8080
    statusCheck: true""")

    if "prowlarr" in selected_services:
        items.append(f"""
  - title: Prowlarr
    description: Indexer manager
    icon: fas fa-search
    url: http://{lan_ip}:9696
    statusCheck: true""")

    if "radarr" in selected_services:
        items.append(f"""
  - title: Radarr
    description: Movie collection manager
    icon: fas fa-film
    url: http://{lan_ip}:7878
    statusCheck: true""")

    if "sonarr" in selected_services:
        items.append(f"""
  - title: Sonarr
    description: TV series collection manager
    icon: fas fa-tv
    url: http://{lan_ip}:8989
    statusCheck: true""")

    if "jellyfin" in selected_services:
        items.append(f"""
  - title: Jellyfin
    description: Media server
    icon: fas fa-play-circle
    url: http://{lan_ip}:8096
    statusCheck: true""")

    if "jellyseerr" in selected_services:
        items.append(f"""
  - title: Jellyseerr
    description: Request management for Jellyfin
    icon: fas fa-list
    url: http://{lan_ip}:5055
    statusCheck: true""")

    if "flaresolverr" in selected_services:
        items.append(f"""
  - title: FlareSolverr
    description: Cloudflare bypass for indexers
    icon: fas fa-shield-alt
    url: http://{lan_ip}:8191
    statusCheck: true""")

    if "dashy" in selected_services:
        items.append(f"""
  - title: Dashy
    description: Dashboard
    icon: fas fa-tachometer-alt
    url: http://{lan_ip}:4000
    statusCheck: true""")

    config_content = "".join(sections) + "".join(items)

    config_file.write_text(config_content)
    logging.info("Generated Dashy configuration.")
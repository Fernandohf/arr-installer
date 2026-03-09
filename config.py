# Configuration constants and service definitions
import os
from pathlib import Path

# Service choices for the installer
SERVICE_CHOICES = [
    {
        "name": "qBittorrent",
        "value": "qbittorrent",
        "checked": True,
        "description": "Torrent client"
    },
    {
        "name": "Prowlarr",
        "value": "prowlarr",
        "checked": True,
        "description": "Indexer manager"
    },
    {
        "name": "Radarr",
        "value": "radarr",
        "checked": True,
        "description": "Movie collection manager"
    },
    {
        "name": "Sonarr",
        "value": "sonarr",
        "checked": True,
        "description": "TV series collection manager"
    },
    {
        "name": "Jellyfin",
        "value": "jellyfin",
        "checked": True,
        "description": "Media server"
    },
    {
        "name": "Jellyseerr",
        "value": "jellyseerr",
        "checked": True,
        "description": "Request management for Jellyfin"
    },
    {
        "name": "FlareSolverr",
        "value": "flaresolverr",
        "checked": True,
        "description": "Cloudflare bypass for indexers"
    },
    {
        "name": "Dashy",
        "value": "dashy",
        "checked": True,
        "description": "Dashboard for all services"
    }
]

# Default paths
DEFAULT_INSTALL_PATH = "C:\\Server" if os.name == 'nt' else "/opt/server"

# Service port mappings
SERVICE_PORTS = {
    "qbittorrent": 8080,
    "prowlarr": 9696,
    "radarr": 7878,
    "sonarr": 8989,
    "jellyfin": 8096,
    "jellyseerr": 5055,
    "flaresolverr": 8191,
    "dashy": 4000
}

# Service directory mappings
SERVICE_DIRS = {
    "qbittorrent": "config/qbittorrent",
    "prowlarr": "config/prowlarr",
    "radarr": "config/radarr",
    "sonarr": "config/sonarr",
    "jellyfin": "config/jellyfin",
    "jellyseerr": "config/jellyseerr",
    "dashy": "config/dashy",
}
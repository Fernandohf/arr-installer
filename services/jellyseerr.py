# Jellyseerr service setup
import time
import requests
import subprocess
import json
import logging
from typing import Optional
from .jellyfin import get_jellyfin_libraries, create_jellyfin_default_libraries
from api import get_servarr_defaults, ensure_servarr_root_folder

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

def boot_jellyseerr(keys: dict, update_fn):
    app_id, display_name = "jellyseerr", "Jellyseerr"
    update_fn(display_name, "api", "progress", "Waiting for API")
    key = wait_for_jellyseerr_and_get_key()
    if key:
        keys[app_id] = key
        update_fn(display_name, "api", "success", "Online")
        update_fn(display_name, "auth", "info", "Uses Jellyfin")
    else:
        update_fn(display_name, "api", "failure", "Boot failed")

def boot_jellyseerr_bootstrap(keys: dict, update_fn):
    app_id, display_name = "jellyseerr", "Jellyseerr"
    update_fn(display_name, "api", "progress", "Waiting for API")
    key = wait_for_jellyseerr_and_get_key()

    if key is not None:
        keys[app_id] = key
        update_fn(display_name, "api", "success", "Online")
        update_fn(display_name, "auth", "info", "Uses Jellyfin")
        return

    try:
        res = requests.get("http://localhost:5055/api/v1/settings/public", timeout=3)
        if res.status_code == 200:
            logging.info("[Jellyseerr] Proceeding without API key; bootstrap mode detected.")
            keys[app_id] = ""
            update_fn(display_name, "api", "success", "Online")
            update_fn(display_name, "auth", "info", "Bootstrap mode")
            return
    except Exception:
        pass

    update_fn(display_name, "api", "failure", "Boot failed")

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
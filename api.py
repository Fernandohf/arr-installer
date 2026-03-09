# API interaction functions
import time
import requests
import subprocess
import xml.etree.ElementTree as ET
import json
import logging
from typing import Optional

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
    except Exception as e:
        logging.exception(f"[{app_name}] Exception ensuring root folder {path}.")
        return False
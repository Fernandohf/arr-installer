# Jellyfin service setup
import time
import requests
import subprocess
import logging
from typing import Optional

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
    except Exception as e:
        logging.exception("[Jellyfin] Exception creating default libraries.")
        return False

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

def boot_and_auth_jellyfin(user: str, passwd: str, update_fn):
    app_name = "Jellyfin"
    update_fn(app_name, "api", "progress", "Waiting for API")

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
        update_fn(app_name, "api", "failure", "Boot failed")
        return False

    update_fn(app_name, "api", "success", "Online")
    update_fn(app_name, "auth", "progress", "Running setup")

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
                update_fn(app_name, "auth", "failure", "Wizard timeout")
                return False

            logging.info(f"[{app_name}] Bypassing Startup Wizard and creating Admin User...")
            conf_res = requests.post("http://localhost:8096/Startup/Configuration", json={"UICulture":"en-US","MetadataCountryCode":"US","MetadataLanguage":"en"}, timeout=5)
            if conf_res.status_code not in (200, 204):
                logging.error(f"[{app_name}] Startup/Configuration failed: {conf_res.status_code}")
                update_fn(app_name, "auth", "failure", "Config step failed")
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
                update_fn(app_name, "auth", "success", "Configured")
                return True
            else:
                logging.error(f"[{app_name}] Failed wizard completion. Res1: {res1.status_code}, Res2: {res2.status_code}")
                update_fn(app_name, "auth", "failure", f"HTTP {res1.status_code}|{res2.status_code}")
                return False
        else:
            logging.info(f"[{app_name}] StartupWizard already completed.")
            create_jellyfin_default_libraries(user, passwd)
            update_fn(app_name, "auth", "success", "Already configured")
            return True
    except Exception as e:
        logging.exception(f"[{app_name}] Exception during Jellyfin boot/auth.")
        update_fn(app_name, "auth", "failure", "Request error")
        return False
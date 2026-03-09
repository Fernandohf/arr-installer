# ARR services setup (Sonarr, Radarr, Prowlarr)
import time
import requests
import logging
from api import (
    wait_for_app_and_get_key,
    set_servarr_credentials,
    configure_prowlarr_app,
    configure_prowlarr_flaresolverr,
    configure_download_client
)

def boot_and_auth_servarr(app_id: str, display_name: str, port: int, version: str, keys: dict, user: str, passwd: str, update_fn):
    update_fn(display_name, "api", "progress", "Waiting for API")
    key = wait_for_app_and_get_key(app_id, port)
    if not key:
        update_fn(display_name, "api", "failure", "Boot failed")
        return False
    keys[app_id] = key
    update_fn(display_name, "api", "success", "Online")

    update_fn(display_name, "auth", "progress", "Applying credentials")
    auth_ok, msg = set_servarr_credentials(app_id, port, key, user, passwd, version)
    update_fn(display_name, "auth", "success" if auth_ok else "failure", "Configured" if auth_ok else f"Failed ({msg})")
    return True
# Utility functions
import socket
import logging

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
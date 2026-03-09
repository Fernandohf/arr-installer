# qBittorrent service setup
import logging

def pre_configure_qbittorrent(base_path):
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
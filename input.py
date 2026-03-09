# User input collection and validation
import questionary
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from rich.panel import Panel
from config import DEFAULT_INSTALL_PATH, SERVICE_CHOICES
from ui import console, render_setup_summary

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

    choices.sort(key=lambda x: x[2])  # Sort alphabetically by timezone name
    choices.sort(key=lambda x: x[0])  # Then sort by UTC offset
    return[questionary.Choice(title=c[1], value=c[2]) for c in choices]

def prompt_confirmed_password():
    while True:
        password = questionary.password("Admin Password:").ask()
        password_confirmation = questionary.password("Confirm Admin Password:").ask()

        if password == password_confirmation:
            return password

        console.print(
            Panel.fit(
                "[bold yellow]Passwords did not match.[/bold yellow]\n[dim]Please re-enter them to avoid locking yourself out later.[/dim]",
                border_style="yellow",
            )
        )

def get_user_input():
    console.print(
        Panel.fit(
            "[bold cyan]ARR Stack Installer[/bold cyan]\n[dim]Docker-based media stack bootstrapper with API auto-linking[/dim]",
            border_style="bright_blue",
            padding=(1, 3),
        )
    )
    console.print("[dim]Detailed logs are being written to arr_installer.log[/dim]\n")

    install_path = questionary.text("Where do you want to install the server?", default=DEFAULT_INSTALL_PATH).ask()

    tz_choices = get_timezone_choices()
    default_tz = next((c for c in tz_choices if "Sao_Paulo" in c.value), tz_choices[0])

    timezone = questionary.select(
        "Select your Timezone:",
        choices=tz_choices,
        default=default_tz,
        use_indicator=True,
    ).ask()

    # Convert SERVICE_CHOICES to questionary format
    service_choices = [
        questionary.Choice(service["name"], checked=service["checked"], value=service["value"])
        for service in SERVICE_CHOICES
    ]

    selected_services = set(questionary.checkbox(
        "Select the services to install:",
        choices=service_choices,
        validate=lambda value: True if value else "Select at least one service.",
    ).ask() or [])

    if "jellyseerr" in selected_services:
        selected_services.update({"jellyfin", "radarr", "sonarr"})
    if "flaresolverr" in selected_services:
        selected_services.add("prowlarr")

    include_fs = "flaresolverr" in selected_services
    include_dashy = "dashy" in selected_services
    configure_js = "jellyseerr" in selected_services

    console.print(
        Panel.fit(
            "[bold cyan]Global Credentials[/bold cyan]\n[dim]Applied to Jellyfin, Sonarr, Radarr, and Prowlarr[/dim]",
            border_style="cyan",
        )
    )
    global_user = questionary.text("Admin Username:").ask()
    global_pass = prompt_confirmed_password()
    global_email = questionary.text("Admin Email (used by Jellyseerr/Dashy):", default="admin@example.com").ask()

    console.print("")
    console.print(render_setup_summary(Path(install_path), timezone, selected_services, global_user, global_email))

    return Path(install_path), timezone, selected_services, global_user, global_pass, global_email
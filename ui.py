# User interface functions using Rich
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from pathlib import Path
from typing import Optional

console = Console()

def make_status(state: str, label: str, style: str | None = None):
    return {"state": state, "label": label, "style": style}

def pending(label: str):
    return make_status("pending", label)

def progress(label: str):
    return make_status("in_progress", label)

def success(label: str):
    return make_status("success", label)

def failure(label: str):
    return make_status("error", label)

def warning(label: str):
    return make_status("warning", label)

def info(label: str):
    return make_status("info", label)

def render_status(cell):
    if not isinstance(cell, dict):
        return cell

    state = cell["state"]
    label = cell["label"]
    style = cell.get("style")

    if state == "in_progress":
        return Spinner("dots", text=Text(label, style=style or "bold cyan"), style=style or "cyan")
    if state == "success":
        return Text(label, style=style or "bold green")
    if state == "error":
        return Text(label, style=style or "bold red")
    if state == "warning":
        return Text(label, style=style or "bold yellow")
    if state == "info":
        return Text(label, style=style or "bold blue")
    return Text(label, style=style or "dim")

def render_setup_summary(install_path: Path, timezone: str, selected_services: set[str], global_user: str, global_email: str):
    service_list = ", ".join(sorted(service.title() for service in selected_services))
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold cyan", justify="right")
    summary.add_column(style="white")
    summary.add_row("Install Path", str(install_path))
    summary.add_row("Timezone", timezone)
    summary.add_row("Admin User", global_user)
    summary.add_row("Admin Email", global_email)
    summary.add_row("Services", service_list)
    return Panel(summary, title="Configuration Summary", border_style="bright_blue", padding=(1, 2))

def render_next_steps_panel(lan_ip: str, selected_services: set[str], include_dashy: bool, include_qbit: bool):
    lines = []
    if include_dashy:
        lines.append(f"[bold cyan]Dashboard[/bold cyan]  http://{lan_ip}:4000")
    if "prowlarr" in selected_services:
        lines.append(f"[bold cyan]Prowlarr[/bold cyan]  http://{lan_ip}:9696")
    if "radarr" in selected_services:
        lines.append(f"[bold cyan]Radarr[/bold cyan]  http://{lan_ip}:7878")
    if "sonarr" in selected_services:
        lines.append(f"[bold cyan]Sonarr[/bold cyan]  http://{lan_ip}:8989")
    if "jellyfin" in selected_services:
        lines.append(f"[bold cyan]Jellyfin[/bold cyan]  http://{lan_ip}:8096")
    if "jellyseerr" in selected_services:
        lines.append(f"[bold cyan]Jellyseerr[/bold cyan]  http://{lan_ip}:5055")
    if include_qbit:
        lines.append(f"[bold cyan]qBittorrent[/bold cyan]  http://{lan_ip}:8080")
    if "prowlarr" in selected_services:
        lines.append("")
        lines.append("[bold yellow]Manual step:[/bold yellow] Add your indexers in Prowlarr.")

    return Panel(
        "\n".join(lines),
        title="Ready",
        subtitle="Open the services you need",
        border_style="green",
        padding=(1, 2),
    )
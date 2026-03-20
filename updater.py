"""In-app update checker using GitHub Releases (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class UpdateCheckResult:
    ok: bool
    update_available: bool
    latest_version: str = ""
    download_url: str = ""
    release_notes: str = ""
    error: str = ""


def _normalize_version(v: str) -> tuple:
    """Convert versions like 'v1.2.3' into comparable tuples."""
    raw = (v or "").strip().lstrip("vV")
    parts = []
    for token in raw.split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _pick_download_url(assets: list[dict], asset_keyword: str) -> str:
    exe_assets = [a for a in assets if str(a.get("name", "")).lower().endswith(".exe")]
    if not exe_assets:
        return ""

    keyword = (asset_keyword or "").lower()
    if keyword:
        for asset in exe_assets:
            name = str(asset.get("name", "")).lower()
            if keyword in name:
                return str(asset.get("browser_download_url", ""))

    return str(exe_assets[0].get("browser_download_url", ""))


def check_for_update(
    current_version: str,
    github_owner: str,
    github_repo: str,
    asset_keyword: str = "Setup",
    timeout: int = 8,
) -> UpdateCheckResult:
    """Check GitHub latest release and compare against current_version."""
    owner = (github_owner or "").strip()
    repo = (github_repo or "").strip()

    if not owner or not repo:
        return UpdateCheckResult(
            ok=False,
            update_available=False,
            error="Update channel not configured. Set GITHUB_OWNER and GITHUB_REPO in app_meta.py.",
        )

    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "BrokerageCalculator-Updater",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return UpdateCheckResult(
                ok=False,
                update_available=False,
                error=(
                    "No public GitHub release found yet. "
                    "Publish a release in this repo (or make the repo public) "
                    "to enable customer updates."
                ),
            )
        return UpdateCheckResult(
            ok=False,
            update_available=False,
            error=f"Update check failed: HTTP {exc.code}",
        )
    except Exception as exc:  # network/http/parse issues
        return UpdateCheckResult(
            ok=False,
            update_available=False,
            error=f"Update check failed: {exc}",
        )

    latest_version = str(payload.get("tag_name") or payload.get("name") or "").strip()
    notes = str(payload.get("body") or "").strip()

    assets = payload.get("assets") or []
    download_url = _pick_download_url(assets, asset_keyword)
    if not download_url:
        download_url = str(payload.get("html_url") or "").strip()

    if _normalize_version(latest_version) > _normalize_version(current_version):
        return UpdateCheckResult(
            ok=True,
            update_available=True,
            latest_version=latest_version,
            download_url=download_url,
            release_notes=notes,
        )

    return UpdateCheckResult(
        ok=True,
        update_available=False,
        latest_version=latest_version,
        download_url=download_url,
        release_notes=notes,
    )

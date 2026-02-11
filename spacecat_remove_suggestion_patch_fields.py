#!/usr/bin/env python3
"""
SpaceCat - Remove patch-related fields from a suggestion's data

Fetches a suggestion (view=full), removes:
  - data.patchContent
  - data.isCodeChangeAvailable

Then PATCHes the suggestion back via:

  PATCH /sites/{siteId}/opportunities/{opportunityId}/suggestions/{suggestionId}

Auth / config is loaded from .env (same keys as a11y-autofix.py):
  - SPACECAT_API_BASE (default: https://spacecat.experiencecloud.live/api/ci)
  - SPACECAT_SESSION_TOKEN (preferred)
  - SPACECAT_API_KEY (legacy)
  - SPACECAT_IMS_ORG_ID (required)

PATCH body strategy:
  - Prefer using the fetched suggestion payload as the PATCH body, after removing obvious
    server-managed/read-only keys, and with the modified `data`.
  - If the API rejects extra fields (e.g. 400/409/422), retry once with a minimal PATCH body:
      {"data": { ...updated data... }}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import requests  # type: ignore[import-untyped]
except ImportError:
    print("ERROR: requests library not found. Install with: pip install requests")
    raise

try:
    from dotenv import load_dotenv  # type: ignore

    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False


def _print_error(message: str) -> None:
    print(f"X {message}")


def _print_info(message: str) -> None:
    print(f"ℹ {message}")


def _print_success(message: str) -> None:
    print(message)


def _load_env_file(env_path: str = ".env") -> bool:
    env_file = Path(env_path)
    if not env_file.exists():
        sibling = Path(__file__).parent / ".env"
        if sibling.exists():
            env_file = sibling
        else:
            return False

    if DOTENV_AVAILABLE:
        try:
            load_dotenv(env_file, override=True)
            return True
        except Exception:
            pass

    try:
        with env_file.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:]
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ[k] = v.strip().strip('"').strip("'")
        return True
    except Exception:
        return False


def _get_config() -> dict:
    return {
        "spacecat_api_base": os.getenv("SPACECAT_API_BASE", "https://spacecat.experiencecloud.live/api/ci"),
        "api_key": os.getenv("SPACECAT_API_KEY", ""),
        "session_token": os.getenv("SPACECAT_SESSION_TOKEN", ""),
        "ims_org_id": os.getenv("SPACECAT_IMS_ORG_ID", ""),
    }


def _get_api_headers(config: dict) -> dict:
    headers = {
        "x-gw-ims-org-id": config["ims_org_id"],
        "Content-Type": "application/json",
    }

    if config.get("session_token"):
        headers["Authorization"] = f"Bearer {config['session_token']}"
    elif config.get("api_key"):
        headers["x-api-key"] = config["api_key"]

    return headers


def _validate_config(config: dict) -> None:
    if not config.get("ims_org_id"):
        raise ValueError("Missing required configuration: SPACECAT_IMS_ORG_ID")
    if not config.get("session_token") and not config.get("api_key"):
        raise ValueError("Missing authentication: set SPACECAT_SESSION_TOKEN (preferred) or SPACECAT_API_KEY (legacy)")


def _write_json(path: str, data) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def fetch_suggestion(*, config: dict, site_id: str, opportunity_id: str, suggestion_id: str) -> dict:
    base = config["spacecat_api_base"].rstrip("/")
    url = f"{base}/sites/{site_id}/opportunities/{opportunity_id}/suggestions/{suggestion_id}"
    headers = _get_api_headers(config)
    resp = requests.get(url, headers=headers, params={"view": "full"}, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected response shape from GET suggestion (expected object).")
    return payload


def patch_suggestion(*, config: dict, site_id: str, opportunity_id: str, suggestion_id: str, body: dict) -> dict:
    base = config["spacecat_api_base"].rstrip("/")
    url = f"{base}/sites/{site_id}/opportunities/{opportunity_id}/suggestions/{suggestion_id}"
    headers = _get_api_headers(config)
    resp = requests.patch(url, headers=headers, data=json.dumps(body), timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected response shape from PATCH suggestion (expected object).")
    return payload


def _build_patch_body_from_payload(*, suggestion: dict, updated_data: dict) -> dict:
    patch_body = dict(suggestion)  # shallow copy
    patch_body["data"] = updated_data

    for k in [
        "id",
        "siteId",
        "opportunityId",
        "createdAt",
        "updatedAt",
        "created_at",
        "updated_at",
        "links",
        "_links",
        "href",
        "url",
    ]:
        patch_body.pop(k, None)

    return patch_body


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove patchContent + isCodeChangeAvailable from a SpaceCat suggestion")
    parser.add_argument("--site-id", required=True, help="Site UUID")
    parser.add_argument("--opportunity-id", required=True, help="Opportunity UUID")
    parser.add_argument("--suggestion-id", required=True, help="Suggestion UUID")
    parser.add_argument(
        "--patch-field",
        default="patchContent",
        help="Name of the patch field inside suggestion.data to remove (default: patchContent)",
    )
    parser.add_argument(
        "--availability-field",
        default="isCodeChangeAvailable",
        help="Name of the availability field inside suggestion.data to remove (default: isCodeChangeAvailable)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not PATCH; only show what would change")
    parser.add_argument("--out-json", help="Write PATCH response JSON to this path")
    args = parser.parse_args()

    _load_env_file()
    config = _get_config()
    try:
        _validate_config(config)
    except Exception as e:
        _print_error(str(e))
        sys.exit(2)

    try:
        suggestion = fetch_suggestion(
            config=config,
            site_id=args.site_id,
            opportunity_id=args.opportunity_id,
            suggestion_id=args.suggestion_id,
        )
    except requests.HTTPError as e:
        body = ""
        try:
            body = e.response.text  # type: ignore[union-attr]
        except Exception:
            pass
        _print_error(f"GET suggestion failed: {e}")
        if body:
            _print_info(body[:2000])
        sys.exit(1)
    except Exception as e:
        _print_error(str(e))
        sys.exit(1)

    data = suggestion.get("data")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        _print_error("Suggestion 'data' is not an object; refusing to modify.")
        sys.exit(1)

    had_patch = args.patch_field in data
    had_availability = args.availability_field in data
    old_patch_value = data.get(args.patch_field)
    old_patch_len = len(old_patch_value) if isinstance(old_patch_value, str) else 0

    data.pop(args.patch_field, None)
    data.pop(args.availability_field, None)

    patch_body = _build_patch_body_from_payload(suggestion=suggestion, updated_data=data)
    minimal_patch_body = {"data": data}

    _print_info(f"API Base: {config['spacecat_api_base']}")
    _print_info(f"siteId: {args.site_id}")
    _print_info(f"opportunityId: {args.opportunity_id}")
    _print_info(f"suggestionId: {args.suggestion_id}")
    _print_info(f"removed: data.{args.patch_field} (was_present={had_patch}, old_len={old_patch_len})")
    _print_info(f"removed: data.{args.availability_field} (was_present={had_availability})")

    if args.dry_run:
        _print_success("Dry run: not sending PATCH.")
        return

    try:
        updated = patch_suggestion(
            config=config,
            site_id=args.site_id,
            opportunity_id=args.opportunity_id,
            suggestion_id=args.suggestion_id,
            body=patch_body,
        )
    except requests.HTTPError as e:
        status_code = None
        try:
            status_code = e.response.status_code  # type: ignore[union-attr]
        except Exception:
            pass

        if status_code in (400, 409, 422):
            _print_info(f"PATCH rejected (HTTP {status_code}); retrying with minimal body (data only).")
            try:
                updated = patch_suggestion(
                    config=config,
                    site_id=args.site_id,
                    opportunity_id=args.opportunity_id,
                    suggestion_id=args.suggestion_id,
                    body=minimal_patch_body,
                )
            except Exception:
                body = ""
                try:
                    body = e.response.text  # type: ignore[union-attr]
                except Exception:
                    pass
                _print_error(f"PATCH suggestion failed: {e}")
                if body:
                    _print_info(body[:2000])
                sys.exit(1)
        else:
            body = ""
            try:
                body = e.response.text  # type: ignore[union-attr]
            except Exception:
                pass
            _print_error(f"PATCH suggestion failed: {e}")
            if body:
                _print_info(body[:2000])
            sys.exit(1)
    except Exception as e:
        _print_error(str(e))
        sys.exit(1)

    if args.out_json:
        _write_json(args.out_json, updated)
        _print_success(f"Wrote response to {args.out_json}")

    _print_success("Removed patch fields successfully.")


if __name__ == "__main__":
    main()


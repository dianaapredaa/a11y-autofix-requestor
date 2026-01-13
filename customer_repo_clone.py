#!/usr/bin/env python3
# ADOBE CONFIDENTIAL
#
# Copyright 2025-2026 Adobe
# All Rights Reserved.
#
# NOTICE:  All information contained herein is, and remains
# the property of Adobe and its suppliers, if any. The intellectual
# and technical concepts contained herein are proprietary to Adobe
# and its suppliers and are protected by all applicable intellectual
# property laws, including trade secret and copyright laws.
# Dissemination of this information or reproduction of this material
# is strictly forbidden unless prior written permission is obtained
# from Adobe.

"""
Customer Repository Clone Tool

This script automates cloning customer repositories from Adobe Cloud Manager using SSO authentication.

Usage:
    python customer_repo_clone.py --program-id 42155
"""

import argparse

DEBUG = False
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError:
    print("ERROR: playwright not found. Install with: pip install playwright")
    print("Then run: playwright install chromium")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: requests library not found. Install with: pip install requests")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False
    print("WARNING: python-dotenv not found. Install with: pip install python-dotenv")


def print_section(title: str):
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}\n")


def print_success(message: str):
    print(f"{message}")


def print_error(message: str):
    print(f"X {message}")


def print_info(message: str):
    print(f"ℹ {message}")


def print_warning(message: str):
    print(f"⚠ {message}")


def load_env_file(env_path: str = ".env") -> bool:
    env_file = Path(env_path)
    
    if not env_file.exists():
        parent_env = Path(__file__).parent / ".env"
        if parent_env.exists():
            env_file = parent_env
        else:
            return False
    
    if DOTENV_AVAILABLE:
        try:
            load_dotenv(env_file, override=True)
            print_success(f"Loaded configuration from {env_file}")
            return True
        except Exception as e:
            print_warning(f"Failed to load with python-dotenv: {e}")

    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith('export '):
                    line = line[7:]
                if '=' in line:
                    key, value = line.split('=', 1)
                    value = value.strip('"').strip("'")
                    os.environ[key] = value
        print_success(f"Loaded configuration from {env_file} (manual parsing)")
        return True
    except Exception as e:
        print_warning(f"Failed to load {env_file}: {e}")
        return False


def get_config():
    return {
        "central_repo_dir": os.getenv("CENTRAL_REPO_DIR", ""),
        "program_id": os.getenv("PROGRAM_ID", ""),
    }


def validate_config(config: dict) -> bool:
    if not config.get("central_repo_dir"):
        print_error("Missing CENTRAL_REPO_DIR in .env file")
        return False
    
    repo_dir = Path(config["central_repo_dir"])
    if not repo_dir.exists():
        print_error(f"CENTRAL_REPO_DIR does not exist: {repo_dir}")
        print_info("Creating directory...")
        try:
            repo_dir.mkdir(parents=True, exist_ok=True)
            print_success(f"Created directory: {repo_dir}")
        except Exception as e:
            print_error(f"Failed to create directory: {e}")
            return False
    
    return True


def capture_auth_headers(program_id: str) -> dict:
    print_section("Step 1: Browser Authentication")
    print_info("Opening browser for SSO authentication...")
    print_info("Please complete the authentication process in the browser window.")
    
    target_url = f"https://git.corp.adobe.com/pages/experience-platform/self-service-hal-browser/#https://ssg.adobe.io/api/program/{program_id}/repositories"
    api_url_pattern = f"https://ssg.adobe.io/api/program/{program_id}/repositories"
    
    captured_headers = {}
    request_count = 0
    ssg_requests = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            ignore_https_errors=False,
            java_script_enabled=True,
        )
        page = context.new_page()
        
        def handle_route(route):
            url = route.request.url
            modified = False
            new_url = url
            
            if "auth-stg" in url or "stg1" in url or "stg2" in url:
                new_url = new_url.replace("auth-stg1.services.adobe.com", "auth.services.adobe.com")
                new_url = new_url.replace("auth-stg2.services.adobe.com", "auth.services.adobe.com")
                new_url = new_url.replace("auth-stg.services.adobe.com", "auth.services.adobe.com")
                new_url = new_url.replace("-stg1.", ".")
                new_url = new_url.replace("-stg2.", ".")
                new_url = new_url.replace("-stg.", ".")
                modified = True
            
            if "ssg-dev.adobe.io" in url:
                new_url = new_url.replace("ssg-dev.adobe.io", "ssg.adobe.io")
                modified = True
            
            if DEBUG and modified and new_url != url:
                print_warning(f"Redirecting to production: {url[:60]}")
                print_info(f"  -> {new_url[:60]}")
                
            route.continue_(url=new_url)
        
        page.route("**/*", handle_route)
        
        def handle_response(response):
            if response.status in [301, 302, 303, 307, 308]:
                location = response.headers.get('location', '')
                if location and ('stg' in location or 'stg1' in location or 'stg2' in location):
                    print_warning(f"Detected staging redirect in response: {location[:60]}")
        
        page.on("response", handle_response)
        
        def handle_framenavigated(frame):
            current_url = frame.url
            new_url = current_url
            needs_redirect = False
            
            if "auth-stg" in current_url or "stg1" in current_url or "stg2" in current_url:
                new_url = new_url.replace("auth-stg1.services.adobe.com", "auth.services.adobe.com")
                new_url = new_url.replace("auth-stg2.services.adobe.com", "auth.services.adobe.com")
                new_url = new_url.replace("auth-stg.services.adobe.com", "auth.services.adobe.com")
                needs_redirect = True
            
            if "ssg-dev.adobe.io" in current_url:
                new_url = new_url.replace("ssg-dev.adobe.io", "ssg.adobe.io")
                needs_redirect = True
            
            if "#https://ssg.adobe.io/api" in current_url and "repositories" not in current_url:
                new_url = new_url.replace("#https://ssg.adobe.io/api", f"#https://ssg.adobe.io/api/program/{program_id}/repositories")
                needs_redirect = True
                if DEBUG:
                    print_warning("Detected incorrect API path, correcting to repositories endpoint")
            
            if needs_redirect and new_url != current_url:
                if DEBUG:
                    print_warning(f"Frame navigated to wrong endpoint, redirecting...")
                    print_info(f"  From: {current_url[:80]}")
                    print_info(f"  To: {new_url[:80]}")
                try:
                    page.goto(new_url, wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    if DEBUG:
                        print_warning(f"Failed to redirect: {e}")
        
        page.on("framenavigated", handle_framenavigated)
        
        def handle_request(request):
            nonlocal request_count
            request_count += 1
            if "ssg.adobe.io" in request.url:
                ssg_requests.append(request.url)
                if DEBUG:
                    print_info(f"SSG API call: {request.url}")
            if api_url_pattern in request.url:
                captured_headers.update(dict(request.headers))
                print_success(f"Captured authentication headers")
        
        page.on("request", handle_request)
        
        try:
            print_info(f"Navigating to: {target_url}")
            page.goto(target_url, wait_until="domcontentloaded", timeout=300000)
            
            print_info("Waiting for authentication and page load...")
            page.wait_for_timeout(5000)
            
            
            max_attempts = 60
            for attempt in range(max_attempts):
                if captured_headers:
                    if DEBUG:
                        print_success("Headers captured! Closing browser...")
                    break
                    
                if DEBUG and attempt % 10 == 0:
                    print_info(f"Waiting for API call... ({attempt+1}/{max_attempts} - {(max_attempts-attempt)*5}s remaining)")
                    print_info(f"  Total requests: {request_count}, SSG API calls: {len(ssg_requests)}")
                    
                    if len(ssg_requests) > 0:
                        print_info(f"  Last SSG API call: {ssg_requests[-1][:80]}...")
                
                page.wait_for_timeout(5000)
            
        except PlaywrightTimeoutError:
            print_warning("Page load timed out, but may have captured headers")
        except Exception as e:
            print_error(f"Error during browser automation: {e}")
        finally:
            browser.close()
    
    if not captured_headers:
        print_error("Failed to capture authentication headers")
        print_info("The page may not have loaded correctly or you need to refresh.")
        sys.exit(1)
    
    print_success("Authentication headers captured successfully")
    return captured_headers


def fetch_repositories(program_id: str, headers: dict) -> list:
    print_section("Step 2: Fetching Repositories")
    
    base_url = f"https://ssg.adobe.io/api/program/{program_id}/repositories"
    all_repositories = []
    url = base_url
    page_limit = 20
    
    while url:
        print_info(f"Fetching: {url}")
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code in [401, 403]:
                print_error(f"Authentication failed (status {response.status_code})")
                print_info("You need to request Cloud Manager SRE role on Slack:")
                print_info("https://adobe.enterprise.slack.com/archives/C0648EGB1FY")
                sys.exit(1)
            
            response.raise_for_status()
            data = response.json()
            
            repositories = data.get("_embedded", {}).get("repositories", [])
            all_repositories.extend(repositories)
            
            if DEBUG:
                print_success(f"Fetched {len(repositories)} repositories (total: {len(all_repositories)})")
            
            if len(repositories) < page_limit:
                if DEBUG:
                    print_info("Reached end of results (page not full)")
                break
            
            next_link = data.get("_links", {}).get("next", {}).get("href")
            if next_link:
                url = f"https://ssg.adobe.io{next_link}" if not next_link.startswith("http") else next_link
            else:
                url = None
                
        except requests.exceptions.RequestException as e:
            print_error(f"Failed to fetch repositories: {e}")
            sys.exit(1)
    
    print_success(f"Total repositories found: {len(all_repositories)}")
    return all_repositories


def filter_repositories(repositories: list, program_id: str) -> dict:
    print_section("Step 3: Filtering Repositories")
    
    if not repositories:
        print_error("No repositories found for this program")
        sys.exit(1)
    
    if len(repositories) == 1:
        print_info("Only one repository found, selecting it")
        return repositories[0]
    
    print_info(f"Filtering {len(repositories)} repositories...")
    
    primary_pattern = re.compile(rf'^[^-]+-p{program_id}(?:-uk\d+)?$')
    fallback_pattern = re.compile(r'^[^-]+-aem-cloud$')
    
    exclude_keywords = ['config', 'dispatcher', 'qa', 'stage', 'dev']
    
    filtered = []
    for repo in repositories:
        repo_name = repo.get("repo", "")
        status = repo.get("status", "")
        
        if status != "ready":
            continue
        
        if any(keyword in repo_name.lower() for keyword in exclude_keywords):
            continue
        
        if primary_pattern.match(repo_name):
            filtered.append(repo)
            print_info(f"  Matched: {repo_name}")
    
    if filtered:
        if len(filtered) > 1:
            print_warning(f"Multiple matching repositories found ({len(filtered)}), using first:")
            for r in filtered:
                print(f"    - {r.get('repo')}")
        
        selected = filtered[0]
        print_success(f"Selected repository: {selected.get('repo')}")
        return selected
    
    print_warning("No repositories matched primary pattern, trying fallback pattern...")
    
    for repo in repositories:
        repo_name = repo.get("repo", "")
        status = repo.get("status", "")
        
        if status != "ready":
            continue
        
        if fallback_pattern.match(repo_name):
            print_success(f"Selected repository (fallback): {repo_name}")
            return repo
    
    print_error("No suitable repositories found after filtering")
    print_info("Available repositories:")
    for repo in repositories:
        print(f"  - {repo.get('repo')} (status: {repo.get('status')})")
    sys.exit(1)


def get_clone_command(program_id: str, repository_id: str, headers: dict) -> str:
    print_section("Step 4: Getting Clone Command")
    
    url = f"https://ssg.adobe.io/api/program/{program_id}/repository/{repository_id}/commands"
    print_info(f"Fetching clone command from: {url}")
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code in [401, 403]:
            print_error(f"Authentication failed (status {response.status_code})")
            print_info("You need to request Cloud Manager SRE role on Slack:")
            print_info("https://adobe.enterprise.slack.com/archives/C0648EGB1FY")
            sys.exit(1)
        
        response.raise_for_status()
        data = response.json()
        
        clone_command = data.get("clone")
        if not clone_command:
            print_error("Clone command not found in response")
            sys.exit(1)
        
        print_success("Clone command retrieved")
        return clone_command
        
    except requests.exceptions.RequestException as e:
        print_error(f"Failed to get clone command: {e}")
        sys.exit(1)


def clone_repository(clone_command: str, target_dir: str):
    print_section("Step 5: Cloning Repository")
    
    target_path = Path(target_dir)
    
    print_info(f"Target directory: {target_path}")
    print_info(f"Command: {clone_command}")
    
    try:
        result = subprocess.run(
            clone_command,
            shell=True,
            cwd=str(target_path),
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            print_success("Repository cloned successfully!")
            if result.stdout:
                print(result.stdout)
        else:
            print_error(f"Clone failed with exit code {result.returncode}")
            if result.stderr:
                print(result.stderr)
            sys.exit(1)
            
    except subprocess.TimeoutExpired:
        print_error("Clone operation timed out (5 minutes)")
        sys.exit(1)
    except Exception as e:
        print_error(f"Failed to execute clone command: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Customer Repository Clone Tool - Clone customer repos with SSO authentication",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Clone repository for a specific program
  python customer_repo_clone.py --program-id 42155

  # Use PROGRAM_ID from .env file
  python customer_repo_clone.py

Configuration:
  CENTRAL_REPO_DIR must be set in .env file to specify where repos should be cloned.
  PROGRAM_ID can be set in .env file to avoid passing --program-id argument.

Requirements:
  - Playwright must be installed: pip install playwright
  - Playwright browsers must be installed: playwright install chromium
  - User must have Cloud Manager SRE role for the program
"""
    )
    
    parser.add_argument(
        "--program-id",
        required=False,
        help="Adobe Cloud Manager program ID (uses PROGRAM_ID from .env if not provided)"
    )
    
    args = parser.parse_args()
    
    print_section("Customer Repository Clone Tool")
    
    load_env_file()
    config = get_config()
    
    if not validate_config(config):
        sys.exit(1)
    
    program_id = args.program_id or config.get("program_id")
    
    if not program_id:
        print_error("Program ID not provided")
        print_info("Either provide --program-id argument or set PROGRAM_ID in .env file")
        sys.exit(1)
    
    print_info(f"Using Program ID: {program_id}")
    
    headers = capture_auth_headers(program_id)
    
    repositories = fetch_repositories(program_id, headers)
    
    selected_repo = filter_repositories(repositories, program_id)
    
    print_info(f"Repository ID: {selected_repo.get('id')}")
    print_info(f"Repository Name: {selected_repo.get('repo')}")
    print_info(f"Repository URL: {selected_repo.get('repositoryUrl')}")
    
    clone_command = get_clone_command(
        program_id,
        selected_repo.get('id'),
        headers
    )
    
    clone_repository(clone_command, config["central_repo_dir"])
    
    print_section("Complete")
    print_success(f"Repository '{selected_repo.get('repo')}' cloned to {config['central_repo_dir']}")


if __name__ == "__main__":
    main()


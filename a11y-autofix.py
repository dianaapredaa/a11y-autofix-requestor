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
A11y Autofix Requestor - Unified Script

This script automates the process of:
1. Finding sites by name or ID in Spacecat
2. Discovering accessibility opportunities and suggestions
3. Creating and sending SQS messages to Mystique for code fixes

Usage:
    python a11y-autofix.py --name sunstargum
    python a11y-autofix.py --site-id d2960efd-a226-4b15-b5ec-b64ccb99995e
    python a11y-autofix.py --name sunstargum --send-by-aggregation-key
    python a11y-autofix.py --name sunstargum --send-by-issue-type
    python a11y-autofix.py --site-id <site-id> --opportunity-id <opp-id> --suggestion-id <sugg-id>
    python a11y-autofix.py --site-id <site-id> --opportunity-id <opp-id> --suggestion-ids <id1> <id2> <id3>
    python a11y-autofix.py --name sunstargum --send-all-issues
"""

import argparse
import json
import os
import sys
import tarfile
import tempfile
import uuid
from datetime import datetime, UTC
from pathlib import Path

# Third-party imports
try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("ERROR: boto3 not found. Install with: pip install boto3")
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


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def print_section(title: str):
    """Print a formatted section header"""
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}\n")


def print_success(message: str):
    """Print success message"""
    print(f"{message}")


def print_error(message: str):
    """Print error message"""
    print(f"X {message}")


def print_info(message: str):
    """Print info message"""
    print(f"ℹ {message}")


def print_warning(message: str):
    """Print warning message"""
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
        "spacecat_api_base": os.getenv("SPACECAT_API_BASE", "https://spacecat.experiencecloud.live/api/ci"),
        "api_key": os.getenv("SPACECAT_API_KEY", ""),
        "session_token": os.getenv("SPACECAT_SESSION_TOKEN", ""),
        "ims_org_id": os.getenv("SPACECAT_IMS_ORG_ID", ""),
        "s3_bucket": os.getenv("S3_BUCKET_NAME", "spacecat-dev-mystique-assets"),
        "sqs_queue_url": os.getenv("SQS_SPACECAT_TO_MYSTIQUE_QUEUE_URL", ""),
        "aws_region": os.getenv("AWS_REGION", "us-east-1"),
        "repo_path": os.getenv("REPO_PATH", ""),
        "archive_name": os.getenv("ARCHIVE_NAME", ""),
    }


def get_aws_credentials():
    access_key = os.getenv("SPACECAT_AWS_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("SPACECAT_AWS_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
    session_token = os.getenv("SPACECAT_AWS_SESSION_TOKEN") or os.getenv("AWS_SESSION_TOKEN")
    
    credentials = {
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
        "region_name": os.getenv("AWS_REGION", "us-east-1"),
    }
    
    if session_token:
        credentials["aws_session_token"] = session_token
    
    return credentials


def validate_config(config: dict) -> bool:
    required = ["ims_org_id", "sqs_queue_url", "repo_path"]
    missing = [key for key in required if not config.get(key)]
    
    if missing:
        print_error(f"Missing required configuration: {', '.join(missing)}")
        print_info("Please check your .env file")
        return False

    if not config.get("session_token") and not config.get("api_key"):
        print_error("Missing authentication configuration: SPACECAT_SESSION_TOKEN")
        print_info("Provide a session token (preferred) or a legacy API key")
        return False

    if not config.get("session_token") and config.get("api_key"):
        print_warning("Using legacy SPACECAT_API_KEY; session tokens are preferred")
    
    return True


# ============================================================================
# SPACECAT API FUNCTIONS
# ============================================================================

def get_api_headers(config: dict) -> dict:
    headers = {
        "x-gw-ims-org-id": config["ims_org_id"],
        "Content-Type": "application/json"
    }

    if config.get("session_token"):
        headers["Authorization"] = f"Bearer {config['session_token']}"
    elif config.get("api_key"):
        headers["x-api-key"] = config["api_key"]

    return headers


def fetch_all_sites(config: dict) -> list:
    url = f"{config['spacecat_api_base']}/sites"
    headers = get_api_headers(config)
    
    try:
        print_info("Fetching sites from Spacecat...")
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        sites = response.json()
        print_success(f"Found {len(sites)} sites")
        return sites
    except Exception as e:
        print_error(f"Failed to fetch sites: {e}")
        return []


def find_site_by_name(sites: list, name_filter: str) -> list:
    name_filter = name_filter.lower()
    matching = []
    
    for site in sites:
        base_url = site.get('baseURL', '').lower()
        if name_filter in base_url:
            matching.append(site)
    
    return matching


def fetch_opportunities_for_site(config: dict, site_id: str) -> list:
    url = f"{config['spacecat_api_base']}/sites/{site_id}/opportunities"
    headers = get_api_headers(config)
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print_warning(f"Failed to fetch opportunities: {e}")
        return []


def fetch_suggestions_for_opportunity(config: dict, site_id: str, opportunity_id: str) -> list:
    url = f"{config['spacecat_api_base']}/sites/{site_id}/opportunities/{opportunity_id}/suggestions"
    headers = get_api_headers(config)
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception:
        return []


def create_tar_archive_with_root_ownership(source_dir: str, output_path: str):
    print_info(f"Creating tar.gz archive from {source_dir}...")
    
    with tarfile.open(output_path, "w:gz") as tar:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.dirname(source_dir))
                info = tar.gettarinfo(file_path, arcname=arcname)
                info.uid = 0
                info.gid = 0
                info.uname = "root"
                info.gname = "root"
                with open(file_path, 'rb') as f:
                    tar.addfile(info, f)
            for d in dirs:
                dir_path = os.path.join(root, d)
                arcname = os.path.relpath(dir_path, os.path.dirname(source_dir))
                info = tar.gettarinfo(dir_path, arcname=arcname)
                info.uid = 0
                info.gid = 0
                info.uname = "root"
                info.gname = "root"
                tar.addfile(info)
    
    file_size = Path(output_path).stat().st_size / (1024 * 1024)
    print_success(f"Created archive: {output_path} ({file_size:.2f} MB)")


def upload_to_s3(s3_client, bucket: str, local_path: str, s3_key: str) -> bool:
    print_info(f"Uploading to s3://{bucket}/{s3_key}...")
    
    try:
        with open(local_path, "rb") as f:
            s3_client.put_object(Bucket=bucket, Key=s3_key, Body=f)
        print_success("Upload complete!")
        return True
    except ClientError as e:
        print_error(f"Upload failed: {e}")
        return False


def find_latest_s3_object(s3_client, bucket: str, prefix: str) -> str:
    """Return the most recently modified object key for a prefix, or empty string."""
    try:
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)
    except ClientError as e:
        print_warning(f"Failed to list S3 objects: {e}")
        return ""
    except Exception as e:
        print_warning(f"Failed to list S3 objects: {e}")
        return ""

    contents = response.get("Contents", [])
    if not contents:
        return ""

    latest = max(contents, key=lambda obj: obj.get("LastModified"))
    return latest.get("Key", "")


def check_s3_object_exists(s3_client, bucket: str, key: str) -> bool:
    """Check if an S3 object exists."""
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            return False
        print_warning(f"Error checking S3 object: {e}")
        return False
    except Exception as e:
        print_warning(f"Error checking S3 object: {e}")
        return False


def send_sqs_message(sqs_client, queue_url: str, message: dict) -> str | None:
    try:
        response = sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message)
        )
        return response['MessageId']
    except ClientError as e:
        print_error(f"Failed to send SQS message: {e}")
        return None


# ============================================================================
# SUGGESTION ANALYSIS
# ============================================================================

def analyze_suggestions(suggestions: list) -> list:
    valid_suggestions = []
    
    for suggestion in suggestions:
        data = suggestion.get('data', {})
        agg_key = data.get('aggregationKey')
        
        if agg_key:
            # Extract target selector and faulty line from nested structure or top level
            target_selector = data.get('targetSelector', data.get('target_selector', ''))
            faulty_line = data.get('faultyLine', data.get('faulty_line', ''))
            
            # If not found at top level, look in nested issues structure
            if not target_selector or not faulty_line:
                issues = data.get('issues', [])
                if issues and len(issues) > 0:
                    html_with_issues = issues[0].get('htmlWithIssues', [])
                    if html_with_issues and len(html_with_issues) > 0:
                        if not target_selector:
                            target_selector = html_with_issues[0].get('target_selector', '')
                        if not faulty_line:
                            faulty_line = html_with_issues[0].get('update_from', '')
            
            # If still no target selector, try extracting from aggregation key
            # Format: URL|issue_type|selector
            if not target_selector:
                parts = agg_key.split('|')
                if len(parts) >= 3:
                    target_selector = parts[2]
            
            valid_suggestions.append({
                'id': suggestion['id'],
                'aggregationKey': agg_key,
                'type': suggestion.get('type'),
                'status': suggestion.get('status'),
                'url': data.get('url', ''),
                'issueType': extract_issue_type(agg_key),
                'faultyLine': faulty_line,
                'targetSelector': target_selector,
                'issueDescription': data.get('issueDescription', data.get('issue_description', '')),
            })
    
    return valid_suggestions


def extract_issue_type(agg_key: str) -> str:
    parts = agg_key.split('|')
    if len(parts) >= 2:
        return parts[1]
    return "unknown"


def display_suggestions(suggestions: list, max_display: int = 1000) -> list:
    displayed = suggestions[:max_display]
    
    print(f"\n{'─' * 80}")
    print(f"  Found {len(suggestions)} valid suggestions (showing {len(displayed)})")
    print(f"{'─' * 80}\n")
    
    for i, s in enumerate(displayed, 1):
        print(f"{i:2d}. Issue: {s['issueType']}")
        print(f"    URL: {s['url']}")
        print(f"    Suggestion ID: {s['id']}")
        if s['targetSelector']:
            print(f"    Target: {s['targetSelector'][:60]}...")
        if s['faultyLine']:
            faulty_preview = s['faultyLine'][:60].replace('\n', ' ')
            print(f"    Faulty: {faulty_preview}...")
        print()
    
    return displayed


def display_issue_types(suggestions: list) -> list:
    counts: dict[str, int] = {}
    for s in suggestions:
        counts[s["issueType"]] = counts.get(s["issueType"], 0) + 1

    items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    print(f"\n{'─' * 80}")
    print(f"  Found {len(items)} issue types")
    print(f"{'─' * 80}\n")

    for i, (issue_type, count) in enumerate(items, 1):
        print(f"{i:2d}. {issue_type} ({count})")
    print()

    return items


def display_aggregation_keys(suggestions: list) -> list:
    """Display aggregation keys with their counts and return sorted list"""
    counts: dict[str, int] = {}
    key_to_suggestion: dict[str, dict] = {}
    
    for s in suggestions:
        agg_key = s["aggregationKey"]
        counts[agg_key] = counts.get(agg_key, 0) + 1
        if agg_key not in key_to_suggestion:
            key_to_suggestion[agg_key] = s

    items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    print(f"\n{'─' * 80}")
    print(f"  Found {len(items)} aggregation keys")
    print(f"{'─' * 80}\n")

    for i, (agg_key, count) in enumerate(items, 1):
        # Get the first suggestion for this key to display context
        s = key_to_suggestion[agg_key]
        # Truncate long aggregation keys for display
        display_key = agg_key if len(agg_key) <= 70 else agg_key[:67] + "..."
        print(f"{i:2d}. {display_key}")
        print(f"    Issues: {count} | Type: {s['issueType']} | URL: {s['url'][:50]}...")
        print()

    return items


def run_workflow(args):
    print_section("Loading Configuration")
    load_env_file()
    config = get_config()
    
    if not validate_config(config):
        sys.exit(1)

    # Check for conflicting flags
    send_flags = [args.send_all_issues, args.send_by_issue_type, 
                  getattr(args, 'send_by_aggregation_key', False)]
    if sum(send_flags) > 1:
        print_error("Use only one of --send-all-issues, --send-by-issue-type, or --send-by-aggregation-key")
        sys.exit(1)
    
    if args.suggestion_id and args.suggestion_ids:
        print_error("Use only one of --suggestion-id or --suggestion-ids")
        sys.exit(1)
    
    if (args.suggestion_id or args.suggestion_ids) and not args.opportunity_id:
        print_error("--suggestion-id(s) requires --opportunity-id")
        sys.exit(1)
    
    credentials = get_aws_credentials()
    if not credentials.get("aws_access_key_id"):
        print_error("AWS credentials not found. Please check your .env file.")
        sys.exit(1)
    
    print_success("Configuration loaded")
    print_info(f"API Base: {config['spacecat_api_base']}")
    print_info(f"S3 Bucket: {config['s3_bucket']}")
    print_info(f"Repo Path: {config['repo_path']}")
    
    # Step 1: Find site
    print_section("Step 1: Finding Site")
    
    site_id = args.site_id
    site_url = None
    
    if not site_id:
        sites = fetch_all_sites(config)
        if not sites:
            print_error("No sites found")
            sys.exit(1)
        
        matching = find_site_by_name(sites, args.name)
        
        if not matching:
            print_error(f"No sites found matching '{args.name}'")
            sys.exit(1)
        
        if len(matching) == 1:
            site_id = matching[0]['id']
            site_url = matching[0].get('baseURL', 'N/A')
            print_success(f"Found site: {site_url}")
            print_info(f"Site ID: {site_id}")
        else:
            print_info(f"Found {len(matching)} matching sites:")
            for i, site in enumerate(matching[:10], 1):
                print(f"  {i}. {site.get('baseURL', 'N/A')} ({site['id']})")
            
            try:
                choice = int(input("\nSelect site number: "))
                if 1 <= choice <= len(matching):
                    site_id = matching[choice - 1]['id']
                    site_url = matching[choice - 1].get('baseURL', 'N/A')
                else:
                    print_error("Invalid selection")
                    sys.exit(1)
            except (ValueError, KeyboardInterrupt):
                print_error("\nCancelled")
                sys.exit(1)
    else:
        print_info(f"Using provided site ID: {site_id}")
    
    opportunity_id = args.opportunity_id
    suggestion_id = args.suggestion_id
    suggestion_ids = args.suggestion_ids if hasattr(args, 'suggestion_ids') else None
    all_suggestions = []
    
    # Parse comma-separated suggestion IDs if provided
    if suggestion_ids:
        # Flatten list and split by commas
        parsed_ids = []
        for item in suggestion_ids:
            parsed_ids.extend([s.strip() for s in item.split(',') if s.strip()])
        suggestion_ids = parsed_ids
    
    if opportunity_id:
        print_section("Step 2-4: Using Provided IDs")
        print_info(f"Opportunity ID: {opportunity_id}")
        if suggestion_id:
            print_info(f"Suggestion ID: {suggestion_id}")
        elif suggestion_ids:
            print_info(f"Suggestion IDs: {len(suggestion_ids)} provided")
        
        suggestions = fetch_suggestions_for_opportunity(config, site_id, opportunity_id)
        if not suggestions:
            print_error(f"No suggestions found for opportunity {opportunity_id}")
            sys.exit(1)
        
        valid = analyze_suggestions(suggestions)
        for s in valid:
            s['opportunityId'] = opportunity_id
            s['opportunityType'] = 'accessibility'
        
        if suggestion_ids:
            # Handle multiple suggestion IDs
            selected_suggestions = []
            for sid in suggestion_ids:
                found = None
                for s in valid:
                    if s['id'] == sid:
                        found = s
                        break
                if found:
                    selected_suggestions.append(found)
                else:
                    print_warning(f"Suggestion {sid} not found, skipping")
            
            if not selected_suggestions:
                print_error("None of the provided suggestion IDs were found")
                sys.exit(1)
            
            all_suggestions = valid
            print_success(f"Found {len(selected_suggestions)} matching suggestions")
            
            # Set selected to the first one for now (we'll handle multiple later)
            selected = selected_suggestions
        elif suggestion_id:
            selected = None
            for s in valid:
                if s['id'] == suggestion_id:
                    selected = s
                    break
            
            if not selected:
                print_error(f"Suggestion {suggestion_id} not found in opportunity {opportunity_id}")
                sys.exit(1)
            
            all_suggestions = valid
            print_success(f"Found suggestion: {selected['issueType']} - {selected['id']}")
        else:
            if not valid:
                print_error("No valid suggestions found with aggregation keys")
                sys.exit(1)
            
            print_success(f"Found {len(valid)} valid suggestions")
            print_section("Step 4: Select Suggestion")
            if args.send_by_issue_type:
                types = display_issue_types(valid)
                try:
                    choice = int(input(f"Select issue type number (1-{len(types)}): "))
                    if not (1 <= choice <= len(types)):
                        print_error("Invalid selection")
                        sys.exit(1)
                except (ValueError, KeyboardInterrupt):
                    print_error("\nCancelled")
                    sys.exit(1)
                chosen_type = types[choice - 1][0]
                selected = next(s for s in valid if s["issueType"] == chosen_type)
            elif getattr(args, 'send_by_aggregation_key', False):
                agg_keys = display_aggregation_keys(valid)
                try:
                    choice = int(input(f"Select aggregation key number (1-{len(agg_keys)}): "))
                    if not (1 <= choice <= len(agg_keys)):
                        print_error("Invalid selection")
                        sys.exit(1)
                except (ValueError, KeyboardInterrupt):
                    print_error("\nCancelled")
                    sys.exit(1)
                chosen_key = agg_keys[choice - 1][0]
                selected = next(s for s in valid if s["aggregationKey"] == chosen_key)
            else:
                displayed = display_suggestions(valid)
                try:
                    choice = int(input(f"Select suggestion number (1-{len(displayed)}): "))
                    if not (1 <= choice <= len(displayed)):
                        print_error("Invalid selection")
                        sys.exit(1)
                except (ValueError, KeyboardInterrupt):
                    print_error("\nCancelled")
                    sys.exit(1)
                selected = displayed[choice - 1]
            all_suggestions = valid
            print_success(f"Selected: {selected['issueType']} - {selected['id']}")
    else:
        
        # Step 2: Find opportunities
        print_section("Step 2: Finding Opportunities")
        
        opportunities = fetch_opportunities_for_site(config, site_id)
        if not opportunities:
            print_error("No opportunities found for this site")
            sys.exit(1)
        
        print_success(f"Found {len(opportunities)} opportunities")
        
        a11y_opportunities = [o for o in opportunities if 'accessibility' in o.get('type', '').lower()]
        
        if not a11y_opportunities:
            print_warning("No accessibility opportunities found, using all opportunities")
            a11y_opportunities = opportunities
        else:
            print_info(f"Found {len(a11y_opportunities)} accessibility opportunities")
        
        # Step 3: Find suggestions
        print_section("Step 3: Finding Suggestions")
        
        for opp in a11y_opportunities:
            opp_id = opp['id']
            suggestions = fetch_suggestions_for_opportunity(config, site_id, opp_id)
            
            if suggestions:
                valid = analyze_suggestions(suggestions)
                for s in valid:
                    s['opportunityId'] = opp_id
                    s['opportunityType'] = opp.get('type', '')
                all_suggestions.extend(valid)
        
        if not all_suggestions:
            print_error("No valid suggestions found with aggregation keys")
            sys.exit(1)
        
        print_success(f"Found {len(all_suggestions)} valid suggestions")
        
        # Step 4: User selection
        print_section("Step 4: Select Suggestion")
        
        if args.send_by_issue_type:
            types = display_issue_types(all_suggestions)
            try:
                choice = int(input(f"Select issue type number (1-{len(types)}): "))
                if not (1 <= choice <= len(types)):
                    print_error("Invalid selection")
                    sys.exit(1)
            except (ValueError, KeyboardInterrupt):
                print_error("\nCancelled")
                sys.exit(1)
            chosen_type = types[choice - 1][0]
            selected = next(s for s in all_suggestions if s["issueType"] == chosen_type)
        elif getattr(args, 'send_by_aggregation_key', False):
            agg_keys = display_aggregation_keys(all_suggestions)
            try:
                choice = int(input(f"Select aggregation key number (1-{len(agg_keys)}): "))
                if not (1 <= choice <= len(agg_keys)):
                    print_error("Invalid selection")
                    sys.exit(1)
            except (ValueError, KeyboardInterrupt):
                print_error("\nCancelled")
                sys.exit(1)
            chosen_key = agg_keys[choice - 1][0]
            selected = next(s for s in all_suggestions if s["aggregationKey"] == chosen_key)
        else:
            displayed = display_suggestions(all_suggestions)
            try:
                choice = int(input(f"Select suggestion number (1-{len(displayed)}): "))
                if not (1 <= choice <= len(displayed)):
                    print_error("Invalid selection")
                    sys.exit(1)
            except (ValueError, KeyboardInterrupt):
                print_error("\nCancelled")
                sys.exit(1)
            selected = displayed[choice - 1]
        
        # Print selection summary
        if isinstance(selected, list):
            print_success(f"Selected {len(selected)} suggestions")
        else:
            print_success(f"Selected: {selected['issueType']} - {selected['id']}")
    
    # Step 5: Create and upload archive
    print_section("Step 5: Preparing Code Archive")
    
    repo_path = config['repo_path']
    if not Path(repo_path).exists():
        print_error(f"Repo path does not exist: {repo_path}")
        sys.exit(1)
    
    repo_name = Path(repo_path).name
    
    s3_client = boto3.client("s3", **credentials)
    sqs_client = boto3.client("sqs", **credentials)
    
    # Validate conflicting flags
    if args.archive and args.force_upload:
        print_error("Cannot use both --archive and --force-upload together")
        print_info("Use --archive to specify existing S3 archive, or --force-upload to create new one")
        sys.exit(1)
    
    # Check if user wants to force upload from local
    if args.force_upload:
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        s3_key = f"tmp/codefix/source/{repo_name}-{timestamp}.tar.gz"
        
        print_info("Force upload enabled: creating fresh archive from local repo")
        with tempfile.TemporaryDirectory() as tmp_dir:
            tar_path = Path(tmp_dir) / f"{repo_name}.tar.gz"
            create_tar_archive_with_root_ownership(repo_path, str(tar_path))
            
            if not upload_to_s3(s3_client, config['s3_bucket'], str(tar_path), s3_key):
                sys.exit(1)
    
    # Check if archive name is specified in config (ARCHIVE_NAME env var)
    elif config.get('archive_name'):
        s3_key = f"tmp/codefix/source/{config['archive_name']}"
        print_info(f"Using archive from config: s3://{config['s3_bucket']}/{s3_key}")
        
        if not check_s3_object_exists(s3_client, config['s3_bucket'], s3_key):
            print_error(f"Archive specified in ARCHIVE_NAME not found in S3: {s3_key}")
            print_info("Available archives:")
            try:
                response = s3_client.list_objects_v2(
                    Bucket=config['s3_bucket'],
                    Prefix="tmp/codefix/source/"
                )
                for obj in response.get("Contents", [])[:10]:
                    print(f"  - {obj['Key']}")
            except Exception:
                pass
            sys.exit(1)
    
    # Check if user specified a specific archive via command line
    elif args.archive:
        s3_key = f"tmp/codefix/source/{args.archive}"
        print_info(f"Checking for specified archive: s3://{config['s3_bucket']}/{s3_key}")
        
        if check_s3_object_exists(s3_client, config['s3_bucket'], s3_key):
            print_success(f"Using specified archive: s3://{config['s3_bucket']}/{s3_key}")
        else:
            print_error(f"Specified archive not found in S3: {s3_key}")
            print_info("Available archives:")
            try:
                response = s3_client.list_objects_v2(
                    Bucket=config['s3_bucket'],
                    Prefix="tmp/codefix/source/"
                )
                for obj in response.get("Contents", [])[:10]:
                    print(f"  - {obj['Key']}")
            except Exception:
                pass
            sys.exit(1)
    
    # Auto-detect: look for existing archive or create new one
    else:
        existing_prefix = f"tmp/codefix/source/{repo_name}-"
        existing_key = find_latest_s3_object(s3_client, config['s3_bucket'], existing_prefix)
        
        if existing_key:
            s3_key = existing_key
            print_info(f"Found existing archive in S3, skipping upload: s3://{config['s3_bucket']}/{s3_key}")
        else:
            timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            s3_key = f"tmp/codefix/source/{repo_name}-{timestamp}.tar.gz"
            
            with tempfile.TemporaryDirectory() as tmp_dir:
                tar_path = Path(tmp_dir) / f"{repo_name}.tar.gz"
                create_tar_archive_with_root_ownership(repo_path, str(tar_path))
                
                if not upload_to_s3(s3_client, config['s3_bucket'], str(tar_path), s3_key):
                    sys.exit(1)
    
    # Step 6: Create SQS message
    print_section("Step 6: Creating SQS Message")
    
    def build_issues_list(suggestions: list) -> list:
        issues = []
        for s in suggestions:
            issues.append({
                "issue_name": s['issueType'],
                "issue_description": s['issueDescription'] or f"Accessibility issue: {s['issueType']}",
                "faulty_line": s['faultyLine'] or "",
                "target_selector": s['targetSelector'] or "",
                "suggestion_id": s['id'],
            })
        return issues

    def build_message(selected_suggestion: dict, issues: list) -> dict:
        return {
            "type": "guidance:accessibility-remediation",
            "siteId": site_id,
            "auditId": str(uuid.uuid4()),
            "time": datetime.now(UTC).isoformat(),
            "data": {
                "url": selected_suggestion['url'],
                "opportunityId": selected_suggestion['opportunityId'],
                "aggregationKey": selected_suggestion['aggregationKey'],
                "issuesList": issues,
                "codeBucket": config['s3_bucket'],
                "codePath": s3_key,
            }
        }

    message_batches = []
    
    # Handle multiple suggestion IDs
    if isinstance(selected, list):
        batch_size = 5
        num_batches = (len(selected) + batch_size - 1) // batch_size  # ceiling division
        print_info(f"Sending {len(selected)} suggestions in {num_batches} batch(es) of max {batch_size}")
        
        # Group suggestions by aggregation key first
        grouped_by_agg_key: dict[str, list[dict]] = {}
        for s in selected:
            grouped_by_agg_key.setdefault(s['aggregationKey'], []).append(s)
        
        # Create batches for each aggregation key
        for agg_key, suggestions_for_key in grouped_by_agg_key.items():
            # Split into batches of maximum batch_size
            for i in range(0, len(suggestions_for_key), batch_size):
                batch = suggestions_for_key[i:i + batch_size]
                message_batches.append((batch[0], build_issues_list(batch)))
    elif args.send_all_issues:
        matching_suggestions = [
            s for s in all_suggestions
            if s['aggregationKey'] == selected['aggregationKey']
        ]
        print_info(
            f"Sending all {len(matching_suggestions)} issues with aggregation key: {selected['aggregationKey']}"
        )
        message_batches.append((selected, build_issues_list(matching_suggestions)))
    elif args.send_by_issue_type:
        matching_suggestions = [
            s for s in all_suggestions
            if s['issueType'] == selected['issueType']
        ]
        if not matching_suggestions:
            print_error(f"No suggestions found for issue type: {selected['issueType']}")
            sys.exit(1)

        grouped: dict[str, list[dict]] = {}
        for s in matching_suggestions:
            grouped.setdefault(s['aggregationKey'], []).append(s)

        print_info(
            f"Sending {len(matching_suggestions)} '{selected['issueType']}' issues across {len(grouped)} aggregation keys"
        )
        for items in grouped.values():
            message_batches.append((items[0], build_issues_list(items)))
    elif getattr(args, 'send_by_aggregation_key', False):
        matching_suggestions = [
            s for s in all_suggestions
            if s['aggregationKey'] == selected['aggregationKey']
        ]
        print_info(
            f"Sending all {len(matching_suggestions)} issues with aggregation key: {selected['aggregationKey']}"
        )
        message_batches.append((selected, build_issues_list(matching_suggestions)))
    else:
        print_info("Sending single issue (use --send-all-issues to send all issues with same aggregation key)")
        message_batches.append((selected, build_issues_list([selected])))

    messages = [build_message(sel, issues) for sel, issues in message_batches]

    if len(messages) == 1:
        print_info("Message to be sent:")
        print()
        print(json.dumps(messages[0], indent=2))
        print()
    else:
        print_info(f"Messages to be sent: {len(messages)}")
        for i, message in enumerate(messages, 1):
            print(f"\nMessage {i}/{len(messages)}:")
            print(json.dumps(message, indent=2))
        print()
    
    # Step 7: Confirmation
    try:
        prompt = "Send this message? (Y/N): " if len(messages) == 1 else f"Send these {len(messages)} messages? (Y/N): "
        confirm = input(prompt).strip().upper()
        if confirm != 'Y':
            print_warning("Cancelled by user")
            sys.exit(0)
    except KeyboardInterrupt:
        print_warning("\nCancelled")
        sys.exit(0)
    
    # Step 8: Send message
    print_section("Step 7: Sending Message")
    
    message_ids = []
    for i, message in enumerate(messages, 1):
        message_id = send_sqs_message(sqs_client, config['sqs_queue_url'], message)
        if not message_id:
            print_error("Failed to send message")
            sys.exit(1)
        message_ids.append(message_id)
        print_success(f"Message {i}/{len(messages)} sent successfully!")
        print_info(f"Message ID: {message_id}")
        print_info(f"Site ID: {site_id}")
        print_info(f"Opportunity ID: {message['data']['opportunityId']}")
        print_info(f"Suggestion ID: {message['data']['issuesList'][0]['suggestion_id']}")
        print_info(f"S3 Path: s3://{config['s3_bucket']}/{s3_key}")

    print_section("Next Steps")
    print_info("1. Monitor Mystique logs in Splunk:")
    for opp_id in sorted({m['data']['opportunityId'] for m in messages}):
        print(f"   index=dx_aem_engineering sourcetype=dx_aem_sites_mystique_backend_prod \"{opp_id}\"")
    print_info("2. Check for generated diff in S3")
    print_info("3. Verify results in Spacecat opportunity")


def main():
    parser = argparse.ArgumentParser(
        description="A11y Autofix Requestor - Send accessibility fix requests to Mystique",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search for site by name (select individual suggestions)
  python a11y-autofix.py --name sunstargum

  # Use site ID directly
  python a11y-autofix.py --site-id d2960efd-a226-4b15-b5ec-b64ccb99995e

  # Browse and select by aggregation key
  python a11y-autofix.py --name sunstargum --send-by-aggregation-key

  # Group by issue type (sends multiple messages per type)
  python a11y-autofix.py --name sunstargum --send-by-issue-type

  # Skip query logic with explicit IDs
  python a11y-autofix.py --site-id <site-id> --opportunity-id <opp-id> --suggestion-id <sugg-id>

  # Send multiple specific suggestions
  python a11y-autofix.py --site-id <site-id> --opportunity-id <opp-id> --suggestion-ids <id1> <id2> <id3>
  python a11y-autofix.py --site-id <site-id> --opportunity-id <opp-id> --suggestion-ids <id1>,<id2>,<id3>

  # Send all related issues instead of just one
  python a11y-autofix.py --name sunstargum --send-all-issues

  # Use a specific archive from S3 instead of auto-detecting
  python a11y-autofix.py --name sunstargum --archive sunstargum-20260120-143000.tar.gz

  # Force upload fresh code from local repo (ignores existing S3 archives)
  python a11y-autofix.py --name sunstargum --force-upload

Configuration:
  All configuration is loaded from .env file in the script directory.
  See runbook.md for detailed setup instructions.
"""
    )
    
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--name",
        help="Partial site name to search (e.g., 'sunstargum', 'krisshop')"
    )
    group.add_argument(
        "--site-id",
        help="Direct site ID (bypasses name search)"
    )
    
    parser.add_argument(
        "--opportunity-id",
        help="Direct opportunity ID (bypasses opportunity search)"
    )
    parser.add_argument(
        "--suggestion-id",
        help="Direct suggestion ID (bypasses suggestion search)"
    )
    parser.add_argument(
        "--suggestion-ids",
        nargs='+',
        help="Multiple suggestion IDs (space or comma separated, bypasses suggestion search)"
    )
    parser.add_argument(
        "--send-all-issues",
        action="store_true",
        help="Send all issues for the selected suggestion/aggregation key (default: only first issue)"
    )
    parser.add_argument(
        "--send-by-issue-type",
        action="store_true",
        help="Send issues grouped by issue type (one message per aggregation key)"
    )
    parser.add_argument(
        "--send-by-aggregation-key",
        action="store_true",
        help="Browse and select by aggregation key (sends all issues for the selected key)"
    )
    parser.add_argument(
        "--archive",
        help="Specific archive filename to use from S3 (e.g., sunstargum.tar.gz). Will look in tmp/codefix/source/"
    )
    parser.add_argument(
        "--force-upload",
        action="store_true",
        help="Force upload fresh archive from local repo, even if one already exists in S3"
    )
    
    args = parser.parse_args()
    
    print_section("A11y Autofix Requestor")
    run_workflow(args)


if __name__ == "__main__":
    main()



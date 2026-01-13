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
    python a11y-autofix.py --site-id <site-id> --opportunity-id <opp-id> --suggestion-id <sugg-id>
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
        "ims_org_id": os.getenv("SPACECAT_IMS_ORG_ID", ""),
        "s3_bucket": os.getenv("S3_BUCKET_NAME", "spacecat-dev-mystique-assets"),
        "sqs_queue_url": os.getenv("SQS_SPACECAT_TO_MYSTIQUE_QUEUE_URL", ""),
        "aws_region": os.getenv("AWS_REGION", "us-east-1"),
        "repo_path": os.getenv("REPO_PATH", ""),
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
    required = ["api_key", "ims_org_id", "sqs_queue_url", "repo_path"]
    missing = [key for key in required if not config.get(key)]
    
    if missing:
        print_error(f"Missing required configuration: {', '.join(missing)}")
        print_info("Please check your .env file")
        return False
    
    return True


# ============================================================================
# SPACECAT API FUNCTIONS
# ============================================================================

def get_api_headers(config: dict) -> dict:
    return {
        "x-api-key": config["api_key"],
        "x-gw-ims-org-id": config["ims_org_id"],
        "Content-Type": "application/json"
    }


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


def send_sqs_message(sqs_client, queue_url: str, message: dict) -> str:
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
            valid_suggestions.append({
                'id': suggestion['id'],
                'aggregationKey': agg_key,
                'type': suggestion.get('type'),
                'status': suggestion.get('status'),
                'url': data.get('url', ''),
                'issueType': extract_issue_type(agg_key),
                'faultyLine': data.get('faultyLine', data.get('faulty_line', '')),
                'targetSelector': data.get('targetSelector', data.get('target_selector', '')),
                'issueDescription': data.get('issueDescription', data.get('issue_description', '')),
            })
    
    return valid_suggestions


def extract_issue_type(agg_key: str) -> str:
    parts = agg_key.split('|')
    if len(parts) >= 2:
        return parts[1]
    return "unknown"


def display_suggestions(suggestions: list, max_display: int = 10) -> list:
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


def run_workflow(args):
    print_section("Loading Configuration")
    load_env_file()
    config = get_config()
    
    if not validate_config(config):
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
    all_suggestions = []
    
    if opportunity_id and suggestion_id:
        print_section("Step 2-4: Using Provided IDs")
        print_info(f"Opportunity ID: {opportunity_id}")
        print_info(f"Suggestion ID: {suggestion_id}")
        
        suggestions = fetch_suggestions_for_opportunity(config, site_id, opportunity_id)
        if not suggestions:
            print_error(f"No suggestions found for opportunity {opportunity_id}")
            sys.exit(1)
        
        valid = analyze_suggestions(suggestions)
        for s in valid:
            s['opportunityId'] = opportunity_id
            s['opportunityType'] = 'accessibility'
        
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
        if opportunity_id or suggestion_id:
            print_error("Both --opportunity-id and --suggestion-id must be provided together")
            sys.exit(1)
        
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
        
        displayed = display_suggestions(all_suggestions)
        
        try:
            choice = int(input("Select suggestion number (1-10): "))
            if not (1 <= choice <= len(displayed)):
                print_error("Invalid selection")
                sys.exit(1)
        except (ValueError, KeyboardInterrupt):
            print_error("\nCancelled")
            sys.exit(1)
        
        selected = displayed[choice - 1]
        print_success(f"Selected: {selected['issueType']} - {selected['id']}")
    
    # Step 5: Create and upload archive
    print_section("Step 5: Preparing Code Archive")
    
    repo_path = config['repo_path']
    if not Path(repo_path).exists():
        print_error(f"Repo path does not exist: {repo_path}")
        sys.exit(1)
    
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    repo_name = Path(repo_path).name
    s3_key = f"tmp/codefix/source/{repo_name}-{timestamp}.tar.gz"
    
    s3_client = boto3.client("s3", **credentials)
    sqs_client = boto3.client("sqs", **credentials)
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        tar_path = Path(tmp_dir) / f"{repo_name}.tar.gz"
        create_tar_archive_with_root_ownership(repo_path, str(tar_path))
        
        if not upload_to_s3(s3_client, config['s3_bucket'], str(tar_path), s3_key):
            sys.exit(1)
    
    # Step 6: Create SQS message
    print_section("Step 6: Creating SQS Message")
    
    issues_list = []
    if args.send_all_issues:
        matching_suggestions = [s for s in all_suggestions 
                               if s['aggregationKey'] == selected['aggregationKey']]
        print_info(f"Sending all {len(matching_suggestions)} issues with aggregation key: {selected['aggregationKey']}")
        
        for s in matching_suggestions:
            issues_list.append({
                "issue_name": s['issueType'],
                "issue_description": s['issueDescription'] or f"Accessibility issue: {s['issueType']}",
                "faulty_line": s['faultyLine'] or "",
                "target_selector": s['targetSelector'] or "",
                "suggestion_id": s['id'],
            })
    else:
        print_info("Sending single issue (use --send-all-issues to send all related issues)")
        issues_list.append({
            "issue_name": selected['issueType'],
            "issue_description": selected['issueDescription'] or f"Accessibility issue: {selected['issueType']}",
            "faulty_line": selected['faultyLine'] or "",
            "target_selector": selected['targetSelector'] or "",
            "suggestion_id": selected['id'],
        })
    
    message = {
        "type": "guidance:accessibility-remediation",
        "siteId": site_id,
        "auditId": str(uuid.uuid4()),
        "time": datetime.now(UTC).isoformat(),
        "data": {
            "url": selected['url'],
            "opportunityId": selected['opportunityId'],
            "aggregationKey": selected['aggregationKey'],
            "issuesList": issues_list,
            "codeBucket": config['s3_bucket'],
            "codePath": s3_key,
        }
    }
    
    print_info("Message to be sent:")
    print()
    print(json.dumps(message, indent=2))
    print()
    
    # Step 7: Confirmation
    try:
        confirm = input("Send this message? (Y/N): ").strip().upper()
        if confirm != 'Y':
            print_warning("Cancelled by user")
            sys.exit(0)
    except KeyboardInterrupt:
        print_warning("\nCancelled")
        sys.exit(0)
    
    # Step 8: Send message
    print_section("Step 7: Sending Message")
    
    message_id = send_sqs_message(sqs_client, config['sqs_queue_url'], message)
    
    if message_id:
        print_success(f"Message sent successfully!")
        print_info(f"Message ID: {message_id}")
        print_info(f"Site ID: {site_id}")
        print_info(f"Opportunity ID: {selected['opportunityId']}")
        print_info(f"Suggestion ID: {selected['id']}")
        print_info(f"S3 Path: s3://{config['s3_bucket']}/{s3_key}")
        
        print_section("Next Steps")
        print_info("1. Monitor Mystique logs in Splunk:")
        print(f"   index=dx_aem_engineering sourcetype=dx_aem_sites_mystique_backend_dev \"{selected['opportunityId']}\"")
        print_info("2. Check for generated diff in S3")
        print_info("3. Verify results in Spacecat opportunity")
    else:
        print_error("Failed to send message")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="A11y Autofix Requestor - Send accessibility fix requests to Mystique",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search for site by name
  python a11y-autofix.py --name sunstargum

  # Use site ID directly
  python a11y-autofix.py --site-id d2960efd-a226-4b15-b5ec-b64ccb99995e

  # Skip query logic with explicit IDs
  python a11y-autofix.py --site-id <site-id> --opportunity-id <opp-id> --suggestion-id <sugg-id>

  # Send all related issues instead of just one
  python a11y-autofix.py --name sunstargum --send-all-issues

Configuration:
  All configuration is loaded from .env file in the script directory.
  See runbook.md for detailed setup instructions.
"""
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
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
        "--send-all-issues",
        action="store_true",
        help="Send all issues for the selected suggestion/aggregation key (default: only first issue)"
    )
    
    args = parser.parse_args()
    
    print_section("A11y Autofix Requestor")
    run_workflow(args)


if __name__ == "__main__":
    main()



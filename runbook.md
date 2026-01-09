# A11y Autofix Requestor - Runbook

This script automates the process of sending accessibility fix requests to Mystique via SQS.

## Overview

The script performs the following steps:

1. **Find Site** - Search for a site by name or use a direct site ID
2. **Find Opportunities** - Discover accessibility opportunities for the site
3. **Find Suggestions** - Get valid suggestions with aggregation keys
4. **User Selection** - Display suggestions and let you choose one
5. **Upload Code** - Create tar.gz archive and upload to S3
6. **Send Message** - Construct and send SQS message to Mystique

## Prerequisites

### 1. Python Environment

```bash
# Ensure Python 3.10+ is installed
python3 --version

# Install dependencies
cd a11y-autofix-requestor
pip install -r requirements.txt
```

### 2. AWS Credentials

You need temporary AWS credentials with access to:
- S3 bucket: `spacecat-dev-mystique-assets`
- SQS queue: `spacecat-to-mystique`

Get credentials from AWS SSO or your team's credential management system.

### 3. Configuration File

```bash
# Copy the template
cp config.env.template .env

# Edit with your values
nano .env  # or your preferred editor
```

**Required configuration:**

| Variable | Description | Example |
|----------|-------------|---------|
| `SPACECAT_API_KEY` | Spacecat API key | `hebelehebele` |
| `SPACECAT_IMS_ORG_ID` | Adobe IMS Org ID | `908936ED5D35CC220A495CD4@AdobeOrg` |
| `SPACECAT_AWS_ACCESS_KEY_ID` | AWS access key | `ASIA...` |
| `SPACECAT_AWS_SECRET_ACCESS_KEY` | AWS secret key | `xxx...` |
| `SPACECAT_AWS_SESSION_TOKEN` | AWS session token | `IQoJb3...` |
| `SQS_SPACECAT_TO_MYSTIQUE_QUEUE_URL` | SQS queue URL | `https://sqs.us-east-1...` |
| `REPO_PATH` | Path to customer repo | `/path/to/repo` |

### 4. Customer Repository

Ensure you have the customer's AEM repository cloned locally. Update `REPO_PATH` in `.env` to point to it.

```bash
# Example
REPO_PATH=/Users/yourname/projects/customer-repos/SUNSTARSUISSESAProgram-p49692-uk34867
```

## Usage

### Search by Site Name

```bash
python a11y-autofix.py --name sunstargum
```

This will:
1. Search all Spacecat sites for "sunstargum" (case-insensitive)
2. If multiple matches, prompt you to select one
3. Continue with the workflow

### Use Direct Site ID

```bash
python a11y-autofix.py --site-id d2960efd-a226-4b15-b5ec-b64ccb99995e
```

This bypasses the name search and uses the site ID directly.

## Workflow Example

```
$ python a11y-autofix.py --name sunstargum

================================================================================
  A11y Autofix Requestor
================================================================================

================================================================================
  Loading Configuration
================================================================================

✅ Loaded configuration from .env
✅ Configuration loaded
ℹ️  API Base: https://spacecat.experiencecloud.live/api/ci
ℹ️  S3 Bucket: spacecat-dev-mystique-assets
ℹ️  Repo Path: /Users/.../customer_repos/SUNSTARSUISSESAProgram-p49692-uk34867

================================================================================
  Step 1: Finding Site
================================================================================

ℹ️  Fetching sites from Spacecat...
✅ Found 150 sites
✅ Found site: https://www.sunstargum.com
ℹ️  Site ID: d2960efd-a226-4b15-b5ec-b64ccb99995e

================================================================================
  Step 2: Finding Opportunities
================================================================================

✅ Found 5 opportunities
ℹ️  Found 2 accessibility opportunities

================================================================================
  Step 3: Finding Suggestions
================================================================================

✅ Found 15 valid suggestions

================================================================================
  Step 4: Select Suggestion
================================================================================

────────────────────────────────────────────────────────────────────────────────
  Found 15 valid suggestions (showing 10)
────────────────────────────────────────────────────────────────────────────────

 1. Issue: aria-roles
    URL: https://www.sunstargum.com/us-en/products.html
    Suggestion ID: e04621ad-f3ff-47fd-a6d0-b22ac8c6e4d3
    Target: a.productcollection__item[role="product"]...
    Faulty: <a class="productcollection__item" role="product">...

 2. Issue: color-contrast
    URL: https://www.sunstargum.com/us-en/about.html
    ...

Select suggestion number (1-10): 1
✅ Selected: aria-roles - e04621ad-f3ff-47fd-a6d0-b22ac8c6e4d3

================================================================================
  Step 5: Preparing Code Archive
================================================================================

ℹ️  Creating tar.gz archive from /Users/.../SUNSTARSUISSESAProgram-p49692-uk34867...
✅ Created archive: /tmp/.../SUNSTARSUISSESAProgram-p49692-uk34867.tar.gz (51.01 MB)
ℹ️  Uploading to s3://spacecat-dev-mystique-assets/tmp/codefix/source/...
✅ Upload complete!

================================================================================
  Step 6: Creating SQS Message
================================================================================

ℹ️  Message to be sent:

{
  "type": "guidance:accessibility-remediation",
  "siteId": "d2960efd-a226-4b15-b5ec-b64ccb99995e",
  "auditId": "7fbd954f-caf7-4a24-827d-e49613555241",
  ...
}

Send this message? (Y/N): Y

================================================================================
  Step 7: Sending Message
================================================================================

✅ Message sent successfully!
ℹ️  Message ID: 3b5f82c9-c8e0-4758-8289-755bd57cd345
ℹ️  Site ID: d2960efd-a226-4b15-b5ec-b64ccb99995e
ℹ️  Opportunity ID: 7d8b7934-7c19-419e-bb8d-2c25ab792fb3
ℹ️  Suggestion ID: e04621ad-f3ff-47fd-a6d0-b22ac8c6e4d3

================================================================================
  Next Steps
================================================================================

ℹ️  1. Monitor Mystique logs in Splunk:
   index=dx_aem_engineering sourcetype=dx_aem_sites_mystique_backend_dev "7d8b7934-7c19-419e-bb8d-2c25ab792fb3"
ℹ️  2. Check for generated diff in S3
ℹ️  3. Verify results in Spacecat opportunity
```

## Monitoring

### Splunk Query

After sending a message, monitor Mystique processing with:

```
index=dx_aem_engineering sourcetype=dx_aem_sites_mystique_backend_dev "<opportunity_id>"
```

### Expected Log Flow

1. `Received message: {...}` - Message received by Mystique
2. `Downloading source code...` - S3 download started
3. `Git repository is functional` - Repo validated
4. `Starting semantic search...` - Context generation
5. `Aider coding orchestration completed successfully with diff:` - Fix generated

### S3 Results

Generated fixes are uploaded to:
```
s3://spacecat-dev-mystique-assets/tmp/codefix/results/<opportunity_id>/<aggregation_key>/report.json
```

## Troubleshooting

### AWS Credentials Expired

```
❌ Upload failed: An error occurred (ExpiredToken)...
```

**Solution:** Refresh your AWS credentials and update `.env`

### No Sites Found

```
❌ No sites found matching 'xyz'
```

**Solution:** Try a different search term or use `--site-id` directly

### No Suggestions Found

```
❌ No valid suggestions found with aggregation keys
```

**Solution:** The site may not have accessibility audits run yet, or suggestions don't have aggregation keys

### Empty Diff Generated

If Mystique returns an empty diff:

1. Check if `REPO_PATH` points to the correct repository
2. Verify the `faulty_line` and `target_selector` in the suggestion match actual code
3. Check Mystique logs for errors

## Configuration Reference

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SPACECAT_API_BASE` | No | `https://spacecat.experiencecloud.live/api/ci` | Spacecat API endpoint |
| `SPACECAT_API_KEY` | Yes | - | API key for Spacecat |
| `SPACECAT_IMS_ORG_ID` | Yes | - | Adobe IMS Organization ID |
| `AWS_REGION` | No | `us-east-1` | AWS region |
| `SPACECAT_AWS_ACCESS_KEY_ID` | Yes | - | AWS access key |
| `SPACECAT_AWS_SECRET_ACCESS_KEY` | Yes | - | AWS secret key |
| `SPACECAT_AWS_SESSION_TOKEN` | Yes* | - | AWS session token (*required for temp creds) |
| `S3_BUCKET_NAME` | No | `spacecat-dev-mystique-assets` | S3 bucket for uploads |
| `SQS_SPACECAT_TO_MYSTIQUE_QUEUE_URL` | Yes | - | SQS queue URL |
| `REPO_PATH` | Yes | - | Path to customer repository |

### Switching Environments

For **STAGE** environment, update these values:

```bash
S3_BUCKET_NAME=spacecat-stage-mystique-assets
SQS_SPACECAT_TO_MYSTIQUE_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/120569600543/spacecat-to-mystique
```

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review Mystique logs in Splunk
3. Contact the Sites Optimizer team


# A11y Autofix Requestor - Runbook

This script automates the process of sending accessibility fix requests to Mystique via SQS.

## Overview

The complete workflow consists of two main steps:

### Step 0: Clone Customer Repository (First Time Setup)
1. **Request Access** - Get Cloud Manager SRE role via Slack
2. **Clone Repository** - Use `customer_repo_clone.py` to automatically clone the customer's repository
3. **Configure Path** - Set `REPO_PATH` in `.env` to point to the cloned repository

### Step 1: Send Fix Request
1. **Find Site** - Search for a site by name or use a direct site ID
2. **Find Opportunities** - Discover accessibility opportunities for the site
3. **Find Suggestions** - Get valid suggestions with aggregation keys
4. **User Selection** - Display suggestions and let you choose one (or use `--send-by-issue-type` to group by type)
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
| `SPACECAT_SESSION_TOKEN` | Spacecat session token | `eyJhbGciOi...` |
| `SPACECAT_API_KEY` | Legacy Spacecat API key (deprecated) | `hebelehebele` |
| `SPACECAT_IMS_ORG_ID` | Adobe IMS Org ID | `908936ED5D35CC220A495CD4@AdobeOrg` |
| `SPACECAT_AWS_ACCESS_KEY_ID` | AWS access key | `ASIA...` |
| `SPACECAT_AWS_SECRET_ACCESS_KEY` | AWS secret key | `xxx...` |
| `SPACECAT_AWS_SESSION_TOKEN` | AWS session token | `IQoJb3...` |
| `SQS_SPACECAT_TO_MYSTIQUE_QUEUE_URL` | SQS queue URL | `https://sqs.us-east-1...` |
| `REPO_PATH` | Path to customer repo | `/path/to/repo` |

### 4. Customer Repository Setup

Before running the autofix script, you need to clone the customer's repository. See the **Cloning Customer Repository** section below for detailed instructions.

## Cloning Customer Repository (First Time)

### Prerequisites

Before you can clone customer repositories, you need the **Cloud Manager SRE role** on Cloud Manager Production.

**To request access:**
1. Go to the Slack channel: [#cc-sre-cloudmanager](https://adobe.enterprise.slack.com/archives/C0648EGB1FY)
2. Request the Cloud Manager SRE role for the specific program you need access to
3. Wait for approval (this may take some time)

### Step 1: Configure Program ID

Edit your `.env` file and set the program ID:

```bash
# Cloud Manager Program ID
PROGRAM_ID=170602

# Directory where repos will be cloned
CENTRAL_REPO_DIR=/Users/yourname/customer-repos
```

### Step 2: Run the Clone Script

```bash
# Using the program ID from .env
./run.sh customer_repo_clone.py

# Or specify program ID directly
./run.sh customer_repo_clone.py --program-id 42155
```

**What happens:**
1. A browser window opens for Adobe SSO authentication
2. Complete the authentication in the browser
3. The page will automatically redirect and load the HAL Browser
4. The script captures authentication headers automatically
5. Fetches available repositories for the program
6. Filters and selects the appropriate repository
7. Clones the repository to your `CENTRAL_REPO_DIR`

**Example output:**
```
================================================================================
  Customer Repository Clone Tool
================================================================================

Loaded configuration from .env
ℹ Using Program ID: 170602

================================================================================
  Step 1: Browser Authentication
================================================================================

ℹ Opening browser for SSO authentication...
Captured authentication headers

================================================================================
  Step 2: Fetching Repositories
================================================================================

ℹ Fetching: https://ssg.adobe.io/api/program/170602/repositories
Total repositories found: 1

================================================================================
  Step 3: Filtering Repositories
================================================================================

ℹ Only one repository found, selecting it
Selected repository: CustomerName-p170602

================================================================================
  Step 4: Getting Clone Command
================================================================================

ℹ Fetching clone command from: https://ssg.adobe.io/api/program/170602/repository/127902/commands
Clone command retrieved

================================================================================
  Step 5: Cloning Repository
================================================================================

ℹ Target directory: /Users/yourname/customer-repos
ℹ Command: git clone https://...
Repository cloned successfully!

================================================================================
  Complete
================================================================================

Repository 'CustomerName-p170602' cloned to /Users/yourname/customer-repos
```

### Step 3: Update REPO_PATH

After successfully cloning, **copy the repository path from the output** and update your `.env` file:

```bash
# In .env file
REPO_PATH=/Users/yourname/customer-repos/CustomerName-p170602
```

**Important:** The `REPO_PATH` should point to the specific repository directory that was cloned, not the parent `CENTRAL_REPO_DIR`.

### Troubleshooting Repository Clone

#### Authentication Failed (401/403)
```
X Authentication failed (status 403)
ℹ You need to request Cloud Manager SRE role on Slack:
ℹ https://adobe.enterprise.slack.com/archives/C0648EGB1FY
```

**Solution:** Request the Cloud Manager SRE role as described above, then try again.

#### Browser Closes Too Quickly
If the browser closes before you can authenticate, increase the timeout or manually refresh the page in the HAL Browser after authentication.

#### No Repositories Found
```
X No suitable repositories found after filtering
```

**Solution:** Check that the program ID is correct and that you have access to that program.

## Usage

### Basic Usage

After completing the repository clone setup above, you can run the autofix script:

```bash
# Using run.sh wrapper (recommended)
./run.sh a11y-autofix.py --name sunstargum

# Or directly with Python
python a11y-autofix.py --name sunstargum
```

**Search by Site Name:**

```bash
./run.sh a11y-autofix.py --name sunstargum
```

This will:
1. Search all Spacecat sites for "sunstargum" (case-insensitive)
2. If multiple matches, prompt you to select one
3. Continue with the workflow

**Use Direct Site ID:**

```bash
./run.sh a11y-autofix.py --site-id d2960efd-a226-4b15-b5ec-b64ccb99995e
```

This bypasses the name search and uses the site ID directly.

**Skip Query Logic with Explicit IDs:**

```bash
./run.sh a11y-autofix.py --site-id <site-id> --opportunity-id <opp-id> --suggestion-id <sugg-id>
```

This skips all the query logic and goes directly to creating the SQS message.

**Send Multiple Specific Suggestions:**

Use this when you have a list of specific suggestion IDs from Spacecat UI and want to send fixes for all of them in one command.

```bash
# Space-separated IDs
./run.sh a11y-autofix.py --site-id <site-id> --opportunity-id <opp-id> \
  --suggestion-ids <id1> <id2> <id3>

# Comma-separated IDs
./run.sh a11y-autofix.py --site-id <site-id> --opportunity-id <opp-id> \
  --suggestion-ids <id1>,<id2>,<id3>

# Mixed format (both commas and spaces work)
./run.sh a11y-autofix.py --site-id <site-id> --opportunity-id <opp-id> \
  --suggestion-ids <id1>,<id2> <id3>,<id4>
```

**What happens:**
1. Script fetches all suggestions for the specified opportunity
2. Filters to only the suggestion IDs you provided
3. Shows summary: `✅ Found X matching suggestions`
4. Creates **one SQS message per suggestion** (each with its own aggregation key)
5. Displays all messages for your review
6. Prompts: `Send these X messages? (Y/N):`
7. Sends all messages upon confirmation

**Use cases:**
- You've reviewed multiple suggestions in Spacecat UI and want to process them all at once
- You're working from a curated list of suggestion IDs (e.g., from a spreadsheet or ticket)
- You want to avoid interactive selection for automation or batch processing

**Real-world example:**

```bash
# Process 5 specific aria-roles fixes from Spacecat UI
./run.sh a11y-autofix.py \
  --site-id 8f34399d-4442-4545-ad6c-1060980107fb \
  --opportunity-id c31bfecf-82de-4664-806f-4845f8f03fc5 \
  --suggestion-ids \
    743b23c5-29aa-42e4-83a6-74a93ea34a80 \
    5967f8a7-1fd8-43fe-bb30-90ba8d0676c2 \
    adbed3d1-71d2-44fc-a66e-2fc3a4b20627 \
    77704827-d0db-429d-b124-561079de43c8 \
    42a4ad4f-beea-4301-997b-8050bfffe537
```

**Output:**
```
================================================================================
  Step 2-4: Using Provided IDs
================================================================================

ℹ Opportunity ID: c31bfecf-82de-4664-806f-4845f8f03fc5
ℹ Suggestion IDs: 5 provided
✅ Found 5 matching suggestions

================================================================================
  Step 6: Creating SQS Message
================================================================================

ℹ Sending 5 suggestions (one message per suggestion)
ℹ Messages to be sent: 5

Message 1/5:
{
  "type": "guidance:accessibility-remediation",
  "siteId": "8f34399d-4442-4545-ad6c-1060980107fb",
  ...
}

[... messages 2-5 ...]

Send these 5 messages? (Y/N):
```

**Important notes:**
- Each suggestion gets its own SQS message (and will be processed independently by Mystique)
- If any suggestion ID is not found, you'll see a warning but other valid IDs will still proceed
- Cannot be combined with `--send-all-issues` or `--send-by-issue-type` flags
- Requires both `--site-id` and `--opportunity-id` to be specified

**Send All Related Issues:**

```bash
./run.sh a11y-autofix.py --name sunstargum --send-all-issues
```

By default, only one issue is sent per suggestion. Use `--send-all-issues` to pack all issues with the same aggregation key into a single SQS message.

### Selection Modes

**Default: Individual Suggestion Selection**

By default, the script shows you a list of individual suggestions to choose from:

```bash
./run.sh a11y-autofix.py --name sunstargum
# Shows: List of individual suggestions
# Sends: Single message for the selected suggestion
```

**Issue Type Selection (Bulk Processing):**

If you want to process all suggestions of a specific issue type at once, use the `--send-by-issue-type` flag:

```bash
./run.sh a11y-autofix.py --name sunstargum --send-by-issue-type
# Shows: List of issue types (e.g., "aria-roles", "color-contrast", etc.)
# Sends: One message per aggregation key for the selected issue type
```

## Working with Spacecat UI

### Workflow: Sending Fixes for Multiple Suggestions from Spacecat UI

**Duration:** 5-10 minutes | **Difficulty:** Easy

This workflow shows you how to identify suggestion IDs in the Spacecat UI and batch process them using the script.

#### Phase 1: Identify Suggestions in Spacecat UI
**Duration:** 2-3 minutes

1. **Navigate to the Site's Opportunities**
   - Go to [Spacecat Portal](https://spacecat.experiencecloud.live/)
   - Search for your site (e.g., "sunstargum")
   - Click on the site to view details
   - Go to the **Opportunities** tab

2. **Filter for Accessibility Opportunities**
   - Look for opportunities with type: `accessibility`
   - Note the **Opportunity ID** from the URL or UI
   - Example: `c31bfecf-82de-4664-806f-4845f8f03fc5`

3. **Browse Suggestions**
   - Click on an accessibility opportunity to view its suggestions
   - Each suggestion shows:
     - **Issue Type** (e.g., `aria-roles`, `button-name`)
     - **URL** where the issue appears
     - **Status** (`NEW`, `IN_PROGRESS`, `APPROVED`, etc.)
     - **Suggestion ID** (UUID)

4. **Select Suggestions to Fix**
   - Review the suggestions you want to process
   - Copy the **Suggestion IDs** (the UUIDs)
   - Typical format: `743b23c5-29aa-42e4-83a6-74a93ea34a80`
   - You can select suggestions with status `NEW` that have `type: CODE_CHANGE`

#### Phase 2: Extract IDs from Spacecat API (Alternative)
**Duration:** 2-3 minutes

If you prefer to get suggestion IDs programmatically:

```bash
# Use curl to fetch suggestions for an opportunity
curl -X GET "https://spacecat.experiencecloud.live/api/v1/sites/<site-id>/opportunities/<opportunity-id>/suggestions" \
  -H "x-api-key: <your-api-key>" \
  -H "x-ims-org-id: <your-org-id>" | jq -r '.[] | select(.type == "CODE_CHANGE" and .status == "NEW") | .id'
```

Or use the browser console on the Spacecat UI page:

```javascript
// Open browser DevTools (F12) on Spacecat suggestions page
// Paste this in the console to extract all NEW suggestion IDs
copy(
  Array.from(document.querySelectorAll('[data-suggestion-id]'))
    .map(el => el.dataset.suggestionId)
    .join(' ')
);
// IDs are now copied to clipboard!
```

#### Phase 3: Run the Script with Suggestion IDs
**Duration:** 3-4 minutes

```bash
# Run with the IDs you collected
./run.sh a11y-autofix.py \
  --site-id 8f34399d-4442-4545-ad6c-1060980107fb \
  --opportunity-id c31bfecf-82de-4664-806f-4845f8f03fc5 \
  --suggestion-ids \
    743b23c5-29aa-42e4-83a6-74a93ea34a80 \
    5967f8a7-1fd8-43fe-bb30-90ba8d0676c2 \
    adbed3d1-71d2-44fc-a66e-2fc3a4b20627
```

**Expected Output:**

```
================================================================================
  Step 2-4: Using Provided IDs
================================================================================

ℹ Opportunity ID: c31bfecf-82de-4664-806f-4845f8f03fc5
ℹ Suggestion IDs: 3 provided
✅ Found 3 matching suggestions

================================================================================
  Step 5: Preparing Code Archive
================================================================================

ℹ Found existing archive in S3, skipping upload

================================================================================
  Step 6: Creating SQS Message
================================================================================

ℹ Sending 3 suggestions (one message per suggestion)
ℹ Messages to be sent: 3

[... message previews ...]

Send these 3 messages? (Y/N): Y

================================================================================
  Step 7: Sending Message
================================================================================

✅ Message 1/3 sent successfully!
ℹ Message ID: 35739fc0-b429-4ac7-9f40-9687a07f3bcd
ℹ Suggestion ID: 743b23c5-29aa-42e4-83a6-74a93ea34a80

✅ Message 2/3 sent successfully!
[...]

✅ Message 3/3 sent successfully!
```

#### Phase 4: Monitor Processing in Splunk
**Duration:** Ongoing

After sending the messages, monitor Mystique processing:

```splunk
index=dx_aem_engineering 
sourcetype=dx_aem_sites_mystique_backend_prod 
"c31bfecf-82de-4664-806f-4845f8f03fc5"
| sort - _time
```

Look for:
- ✅ **Success:** `"Successfully generated code fix"`
- ⚠️ **Warning:** Check for any issues during processing
- ❌ **Error:** `"Not found for codefix:accessibility"`

#### Tips and Best Practices

**✅ DO:**
- Start with a small batch (3-5 suggestions) to validate the workflow
- Verify all suggestion IDs belong to the same opportunity
- Check that suggestions have `status: NEW` and `type: CODE_CHANGE`
- Keep a log of which suggestion IDs you've already sent

**❌ DON'T:**
- Don't mix suggestion IDs from different opportunities
- Don't send suggestions that are already `IN_PROGRESS` or `APPROVED`
- Don't send more than 20-30 suggestions at once (to avoid overwhelming Mystique)
- Don't use `--send-all-issues` with `--suggestion-ids` (they're mutually exclusive)

**Troubleshooting:**

| Issue | Solution |
|-------|----------|
| `Suggestion {id} not found, skipping` | The ID doesn't exist in that opportunity, verify you copied it correctly |
| `None of the provided suggestion IDs were found` | Check that site ID and opportunity ID are correct |
| `Use only one of --suggestion-id or --suggestion-ids` | Don't mix singular and plural flags |
| `--suggestion-id(s) requires --opportunity-id` | You must specify the opportunity ID when using suggestion IDs |

## Complete Workflow Example

### First Time: Clone Repository

```bash
$ ./run.sh customer_repo_clone.py

================================================================================
  Customer Repository Clone Tool
================================================================================

Loaded configuration from .env
ℹ Using Program ID: 170602

[... authentication and cloning process ...]

================================================================================
  Complete
================================================================================

Repository 'SUNSTARSUISSESAProgram-p49692-uk34867' cloned to /Users/me/customer-repos
```

Then update `.env`:
```bash
REPO_PATH=/Users/me/customer-repos/SUNSTARSUISSESAProgram-p49692-uk34867
```

### Send Fix Request

```
$ ./run.sh a11y-autofix.py --name sunstargum

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
ℹ️  S3 Path: s3://spacecat-dev-mystique-assets/tmp/codefix/source/...

================================================================================
  Next Steps
================================================================================

ℹ️  1. Monitor Mystique logs in Splunk:
   index=dx_aem_engineering sourcetype=dx_aem_sites_mystique_backend_prod "7d8b7934-7c19-419e-bb8d-2c25ab792fb3"
ℹ️  2. Check for generated diff in S3
ℹ️  3. Verify results in Spacecat opportunity
```

## Monitoring

### Splunk Query

After sending a message, monitor Mystique processing with:

```
index=dx_aem_engineering sourcetype=dx_aem_sites_mystique_backend_prod "<opportunity_id>"
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
| `SPACECAT_SESSION_TOKEN` | Yes* | - | Session token for Spacecat (*preferred) |
| `SPACECAT_API_KEY` | No | - | Legacy API key for Spacecat (deprecated) |
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

## Quick Reference: Usage Modes Comparison

This table helps you choose the right command for your use case:

| Use Case | Command | What It Does | Messages Sent |
|----------|---------|--------------|---------------|
| **Explore & select one** | `./run.sh a11y-autofix.py --name <site>` | Interactive: Shows all suggestions, you pick one | 1 message |
| **Process all of one type** | `./run.sh a11y-autofix.py --name <site> --send-by-issue-type` | Interactive: Shows issue types, you pick one, sends all suggestions for that type | Multiple (1 per aggregation key) |
| **Send one specific fix** | `./run.sh a11y-autofix.py --site-id <sid> --opportunity-id <oid> --suggestion-id <sugid>` | Direct: No interaction, sends exactly one suggestion | 1 message |
| **Send multiple specific fixes** | `./run.sh a11y-autofix.py --site-id <sid> --opportunity-id <oid> --suggestion-ids <id1> <id2> <id3>` | Direct: No interaction, sends all specified suggestions | Multiple (1 per suggestion ID) |
| **Send all related issues** | `./run.sh a11y-autofix.py --name <site> --send-all-issues` | Interactive: Pick one suggestion, sends all issues with same aggregation key | 1 message (with multiple issues) |

### When to Use Each Mode

**🎯 Use `--name <site>` (default)** when:
- You're exploring what needs to be fixed
- You want to see all available suggestions
- You're fixing issues one at a time
- You're not sure which suggestion to prioritize

**📋 Use `--send-by-issue-type`** when:
- You want to fix all instances of one type of issue (e.g., all `aria-roles` issues)
- You have many suggestions of the same type
- You want to batch process by category
- You're systematically working through different issue types

**🎯 Use `--suggestion-id` (singular)** when:
- You know the exact suggestion you want to fix
- You're re-sending a failed request
- You want maximum precision (one specific fix)
- You're automating a single fix request

**📦 Use `--suggestion-ids` (plural)** when:
- You've curated a list of specific suggestions from Spacecat UI
- You want to batch process multiple specific fixes
- You're working from a spreadsheet or ticket with specific IDs
- You want to avoid interactive selection but still have granular control

**🔄 Use `--send-all-issues`** when:
- Multiple issues share the same aggregation key (same page + same selector)
- You want Mystique to fix all related issues in one code change
- You're optimizing for fewer PR/commits
- The issues are logically grouped together

### Flag Compatibility Matrix

| Primary Flag | Compatible With | NOT Compatible With |
|--------------|----------------|---------------------|
| `--name` | `--send-all-issues`, `--send-by-issue-type` | `--site-id`, `--opportunity-id` |
| `--site-id` | `--opportunity-id`, `--suggestion-id`, `--suggestion-ids` | `--name` |
| `--suggestion-id` | `--site-id`, `--opportunity-id`, `--send-all-issues` | `--suggestion-ids`, `--send-by-issue-type` |
| `--suggestion-ids` | `--site-id`, `--opportunity-id` | `--suggestion-id`, `--send-all-issues`, `--send-by-issue-type` |
| `--send-all-issues` | `--name`, `--site-id`, `--opportunity-id`, `--suggestion-id` | `--send-by-issue-type`, `--suggestion-ids` |
| `--send-by-issue-type` | `--name`, `--site-id`, `--opportunity-id` | `--send-all-issues`, `--suggestion-id`, `--suggestion-ids` |

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review Mystique logs in Splunk
3. Contact the Sites Optimizer team



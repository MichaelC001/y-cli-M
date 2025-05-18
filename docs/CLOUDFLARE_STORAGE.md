# Cloudflare Storage for Y-CLI

This document explains how to set up and use Cloudflare KV and R2 for storing chat data in Y-CLI.

## Overview

Y-CLI now supports storing chat data in Cloudflare KV with backup to Cloudflare R2. This provides:

1. **Cloud Storage**: Access your chat data from anywhere
2. **Backup**: Automatic backup of chat data to R2
3. **Reliability**: Cloudflare's global infrastructure

## Setup Instructions

### 1. Create Cloudflare Resources

#### Create a KV Namespace

1. Log in to your Cloudflare dashboard
2. Navigate to Workers & Pages > KV
3. Click "Create namespace"
4. Name it something like "y-cli-chats"
5. Note the Namespace ID for configuration

#### Create an R2 Bucket

1. Navigate to R2 in your Cloudflare dashboard
2. Click "Create bucket"
3. Name it something like "y-cli-backups"
4. Note the bucket name for configuration

#### Create an API Token

1. Go to your Cloudflare profile > API Tokens
2. Click "Create Token"
3. Use the "Edit Cloudflare Workers" template
4. Add the following permissions:
   - Account > Workers KV Storage > Edit
   - Account > R2 Storage > Edit
5. Set the Account Resources to include your account
6. Create the token and copy it for configuration

### 2. Configure Y-CLI

Edit your Y-CLI configuration file:

- On macOS: `~/Library/Preferences/y-cli/config.toml`
- On Linux: `~/.config/y-cli/config.toml`

Add the following configuration:

```toml
# Set storage type to cloudflare
storage_type = "cloudflare"

# Cloudflare configuration
[cloudflare]
account_id = "your-cloudflare-account-id"  # Your Cloudflare account ID
api_token = "your-cloudflare-api-token"    # API token created above
kv_namespace_id = "your-kv-namespace-id"   # KV namespace ID from step 1
r2_bucket_name = "y-cli-backups"           # R2 bucket name from step 1
```

### 3. Deploy the Backup Worker

To automatically backup data from KV to R2, deploy the provided Cloudflare Worker:

1. Install Wrangler CLI: `npm install -g wrangler`
2. Create a new directory for your worker: `mkdir y-cli-backup-worker && cd y-cli-backup-worker`
3. Initialize a new worker: `wrangler init`
4. Copy the contents of `cloudflare-worker.js` to your worker's main file
5. Create a `wrangler.toml` file:

```toml
name = "y-cli-backup-worker"
main = "src/index.js"
compatibility_date = "2023-10-30"

# KV Namespace binding
[[kv_namespaces]]
binding = "CHAT_KV"
id = "your-kv-namespace-id"

# R2 bucket binding
[[r2_buckets]]
binding = "CHAT_R2"
bucket_name = "y-cli-backups"

# Scheduled trigger (daily at 2:00 AM UTC)
[triggers]
crons = ["0 2 * * *"]
```

6. Deploy the worker: `wrangler deploy`

## Usage

Once configured, Y-CLI will automatically use Cloudflare KV for storing chat data. The backup worker (if deployed) will periodically copy data from KV to R2 for backup purposes.

No changes to your workflow are needed - all chat operations will work as before, but now your data is stored in the cloud.

## Troubleshooting

### Connection Issues

If you encounter connection issues:

1. Verify your API token has the correct permissions
2. Check that your account ID and namespace ID are correct
3. Ensure your R2 bucket exists and is accessible

### Data Migration

To migrate existing chats to Cloudflare:

1. Configure Cloudflare storage as described above
2. Upload your existing chat.jsonl file to R2 bucket

## Security Considerations

- Your API token has access to modify your KV and R2 data. Keep it secure.
- All data is transmitted to Cloudflare's servers. Ensure you're comfortable with this for your chat data.
- Consider using environment variables for sensitive configuration instead of storing directly in config files.

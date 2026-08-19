# Testing Chrome Profile Download from GCS Locally

This guide explains how to test the Kubernetes Chrome profile download from Google Cloud Storage (GCS) in your local development environment, simulating the init container behavior.

## Overview

The Kubernetes deployment uses an init container (`chrome-profile-downloader`) that:

1. Authenticates to GCS using Workload Identity
2. Downloads the Chrome profile archive from GCS
3. Extracts it to a shared volume
4. Exits successfully so the main container can start

For local testing, you'll replicate this workflow using the `gcloud` and `gsutil` CLI tools.

## Prerequisites

### 1. Google Cloud SDK

Install the Google Cloud SDK with gsutil:

```bash
# macOS with Homebrew
brew install --cask google-cloud-sdk

# Or download from
https://cloud.google.com/sdk/docs/install
```

Verify installation:

```bash
gcloud --version
gsutil version
```

### 2. GCP Credentials

Authenticate with your GCP account:

```bash
gcloud auth application-default login
```

This opens a browser to authenticate and stores credentials locally at:

```
~/.config/gcloud/application_default_credentials.json
```

### 3. GCS Bucket & Chrome Profile Setup

You need:

- A GCS bucket containing the Chrome profile archive (e.g., `my-org-chrome-profiles`)
- The archive path within the bucket (e.g., `profiles/chrome-profile.tar.gz`)
- A service account (or your user account) with `storage.objectViewer` role

If you don't have a Chrome profile yet, create one:

```bash
cd meeting-bot
make auth-profile        # Create a signed-in Chrome profile locally

# Then upload it to GCS
tar -czf chrome-profile.tar.gz -C chrome_profile .
gsutil cp chrome-profile.tar.gz gs://my-org-chrome-profiles/profiles/chrome-profile.tar.gz
```

## Testing Locally

### Method 1: Using the Test Script (Recommended)

The easiest way is to use the provided test script:

```bash
cd meeting-bot

# Set your GCS bucket details
export GCS_BUCKET="my-org-chrome-profiles"
export GCS_OBJECT_PATH="profiles/chrome-profile.tar.gz"

# Run the test script
bash scripts/test_gcs_profile_download.sh
```

**What the script does:**

1. ✓ Validates `GCS_BUCKET` and `GCS_OBJECT_PATH` environment variables
2. ✓ Checks that `gsutil` is available
3. ✓ Tests GCS bucket access
4. ✓ Verifies the object exists in GCS
5. ✓ Downloads the archive from GCS
6. ✓ Validates the archive is a valid tar.gz file
7. ✓ Lists archive contents
8. ✓ Extracts the archive to a temporary directory
9. ✓ Validates the extracted profile structure
10. ✓ Copies the profile to local `chrome_profile/` directory
11. ✓ Cleans up temporary files

**Example output:**

```
=== Chrome Profile GCS Download Test ===

[1] Checking environment variables...
✓ GCS_BUCKET: my-org-chrome-profiles
✓ GCS_OBJECT_PATH: profiles/chrome-profile.tar.gz

[2] Checking gsutil availability...
✓ gsutil is available
gsutil version: 5.20

[3] Testing GCS access...
✓ GCS bucket is accessible

[4] Verifying object exists in GCS...
✓ Object exists in GCS
2024-01-15 10:30:45  123.4 MiB  gs://my-org-chrome-profiles/profiles/chrome-profile.tar.gz

[5] Setting up directories...
✓ Temporary directory: /tmp/chrome_profile_test_12345

[6] Downloading Chrome profile from GCS...
Source: gs://my-org-chrome-profiles/profiles/chrome-profile.tar.gz
Destination: /tmp/chrome_profile_test_12345/chrome_profile.tar.gz
Copying gs://my-org-chrome-profiles/profiles/chrome-profile.tar.gz...
✓ Download successful
-rw-r--r--  123M  /tmp/chrome_profile_test_12345/chrome_profile.tar.gz

[7] Validating archive format...
✓ Archive is valid gzip
/tmp/chrome_profile_test_12345/chrome_profile.tar.gz: gzip compressed data

[8] Extracting Chrome profile...
Destination: /tmp/chrome_profile_test_12345/chrome_profile_extracted
Local State
Default/Cookies
Default/Cache/...
✓ Extraction successful

[9] Validating profile structure...
✓ Profile directory contains files
115M    /tmp/chrome_profile_test_12345/chrome_profile_extracted

Contents:
drwxr-xr-x  Bookmarks
drwxr-xr-x  Cache
-rw-r--r--  Cookies
-rw-r--r--  Local State
drwxr-xr-x  Default
✓ Preferences
✓ Local State
✓ Default
✗ chrome_debug.log (not found)

[10] Copying profile for local testing...
✓ Profile copied to: /Users/you/meeting-bot/chrome_profile

[11] Cleaning up temporary files...
✓ Temporary files removed

=== SUCCESS ===

The Chrome profile has been successfully downloaded and extracted.

Next steps for local testing:

  1. Run the meeting bot with the profile:
     make run

  2. Or with Docker:
     make docker-run

  3. The bot will now use the downloaded profile at:
     /Users/you/meeting-bot/chrome_profile

Environment:
  BROWSER_PROFILE_DIR=/chrome-profile (in Kubernetes)
  BROWSER_PROFILE_DIR=./chrome_profile (locally)
```

### Method 2: Manual Testing

If you prefer to test manually:

```bash
cd meeting-bot

# 1. Check authentication
gcloud auth list

# 2. List your GCS buckets
gsutil ls

# 3. List objects in your bucket
gsutil ls gs://my-org-chrome-profiles/

# 4. Download the archive
gsutil -m cp gs://my-org-chrome-profiles/profiles/chrome-profile.tar.gz /tmp/chrome_profile.tar.gz

# 5. Validate the archive
tar -tzf /tmp/chrome_profile.tar.gz | head -20

# 6. Extract it
mkdir -p /tmp/chrome_profile_extracted
tar -xzf /tmp/chrome_profile.tar.gz -C /tmp/chrome_profile_extracted/

# 7. Copy to the project
cp -r /tmp/chrome_profile_extracted chrome_profile

# 8. Verify permissions
ls -la chrome_profile/
```

## Running the Bot with Downloaded Profile

Once the profile is downloaded and placed in `chrome_profile/`, run the bot:

### Locally

```bash
cd meeting-bot
make run
```

The environment variable `BROWSER_PROFILE_DIR` is automatically set to `/data/chrome_profile` in the local setup (see `Makefile` and `docker-compose.yml`).

### With Docker

```bash
cd meeting-bot
make docker-run
```

Docker automatically mounts `chrome_profile/` to `/data/chrome_profile` inside the container.

### Manually

```bash
cd meeting-bot
export BROWSER_PROFILE_DIR=$(pwd)/chrome_profile
make install
source .venv/bin/activate
uvicorn app.main:app --port 5000
```

## Troubleshooting

### `gcloud: command not found`

**Problem:** Google Cloud SDK is not installed.

**Solution:**

```bash
# macOS
brew install --cask google-cloud-sdk

# Then add to your shell profile (~/.bash_profile, ~/.zprofile, etc.)
export PATH="/usr/local/Caskroom/google-cloud-sdk/latest/google-cloud-sdk/bin:$PATH"
```

### `ERROR: Cannot access gs://bucket-name`

**Problem:** Your credentials don't have access to the GCS bucket.

**Solutions:**

1. Re-authenticate:

   ```bash
   gcloud auth application-default login
   ```

2. Verify your GCP project is set:

   ```bash
   gcloud config list
   gcloud config set project YOUR_PROJECT_ID
   ```

3. Verify your account has `storage.objectViewer` role on the bucket:

   ```bash
   gcloud projects get-iam-policy YOUR_PROJECT_ID --flatten="bindings[].members" --filter="bindings.role:roles/storage.objectViewer"
   ```

### `ERROR: File is not a valid gzip archive`

**Problem:** The object in GCS is not a valid tar.gz file.

**Solutions:**

1. Verify the object in GCS:

   ```bash
   gsutil cat gs://my-org-chrome-profiles/profiles/chrome-profile.tar.gz | file -
   ```

2. Re-upload a valid archive:

   ```bash
   # Verify your local archive first
   file chrome-profile.tar.gz
   tar -tzf chrome-profile.tar.gz | head

   # Then upload
   gsutil cp chrome-profile.tar.gz gs://my-org-chrome-profiles/profiles/chrome-profile.tar.gz
   ```

### `ERROR: Extracted directory is empty`

**Problem:** The archive extracted but contains no files.

**Solutions:**

1. Check the archive contents:

   ```bash
   tar -tzf /path/to/archive.tar.gz | head -20
   ```

2. If the archive has a top-level directory, extract it differently:

   ```bash
   # If the archive is: chrome-profile/Preferences, chrome-profile/Default/, etc.
   tar -xzf /tmp/chrome_profile.tar.gz
   mv chrome-profile/* /tmp/chrome_profile_extracted/
   ```

### Permissions errors when running the bot

**Problem:** The extracted profile has wrong permissions.

**Solution:**

```bash
cd chrome_profile
chmod -R u+rw .
chmod u+x Default
```

## Differences Between Local and Kubernetes Testing

| Aspect | Local | Kubernetes |
|--------|-------|------------|
| **Authentication** | `gcloud auth application-default login` (user credentials) | Workload Identity (service account) |
| **Profile location** | `./chrome_profile` or `/data/chrome_profile` | `/chrome-profile` (shared volume) |
| **GCS access** | Direct `gsutil` commands | Init container with google-cloud-cli image |
| **Temporary storage** | `/tmp` | Container memory, cleaned after extraction |
| **Profile persistence** | Remains on local filesystem after test | Recreated on every pod restart |

## Next Steps

1. **Verify the profile works** in your local bot by joining a test meeting:

   ```bash
   curl -X POST http://localhost:5000/api/meet/meetings/join \
     -H 'Content-Type: application/json' \
     -d '{
       "meetingId": "test-gcs-profile",
       "meetingUrl": "https://meet.google.com/your-meet-code",
       "userEmail": "your-email@example.com",
       "projectId": "your-project-id"
     }'
   ```

2. **Test in Kubernetes** using the same GCS configuration:

   ```bash
   kubectl apply -f deploy/k8s/configmap.yaml
   kubectl apply -f deploy/k8s/deployment.yaml
   kubectl logs -f deployment/meeting-bot -c chrome-profile-downloader
   ```

3. **Monitor the init container** in the Kubernetes pod:

   ```bash
   kubectl describe pod <POD_NAME>
   kubectl logs <POD_NAME> -c chrome-profile-downloader
   ```

## See Also

- [CHROME_PROFILE.md](./CHROME_PROFILE.md) — Chrome profile architecture and Workload Identity setup
- [CONFIGURATION.md](./CONFIGURATION.md) — Configuration options including `BROWSER_PROFILE_DIR`
- [SETUP.md](./SETUP.md) — Local development setup and running the bot
- [OPERATIONS.md](./OPERATIONS.md) — Kubernetes operations and troubleshooting


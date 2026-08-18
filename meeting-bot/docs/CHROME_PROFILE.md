# Chrome Profile Initialization

The `meeting-bot` uses a persistent Chrome profile to join Google Meet as a signed-in user, preserving session state and authentication across meetings.

## Overview

Chrome profiles are downloaded from Google Cloud Storage (GCS) at pod startup via a Kubernetes init container. The profile is extracted into a shared volume that the main `meeting-bot` container mounts at `/chrome-profile`.

### Flow

```
Pod Start
    ↓
[Init Container: chrome-profile-downloader]
    ↓
  Download chrome-profile.tar.gz from GCS
    ↓
  Extract archive to /chrome-profile volume
    ↓
  Exit successfully
    ↓
[Main Container: meeting-bot]
    ↓
  Mount /chrome-profile volume
    ↓
  Use profile at BROWSER_PROFILE_DIR=/chrome-profile
    ↓
  Join Google Meet as signed-in user
```

## Configuration

The GCS source is configured via two environment variables in `meeting-bot-config` ConfigMap:

- **`GCS_BUCKET`**: The GCS bucket name (e.g., `my-org-chrome-profiles`).
- **`GCS_OBJECT_PATH`**: The object path within the bucket (e.g., `profiles/chrome-profile.tar.gz`).

Example ConfigMap values:

```yaml
data:
  GCS_BUCKET: "my-org-chrome-profiles"
  GCS_OBJECT_PATH: "profiles/chrome-profile.tar.gz"
```

## GCS Access via Workload Identity

The init container authenticates to GCS using **Kubernetes Workload Identity** (not JSON keys):

1. **Bind the Kubernetes Service Account to a GCP Service Account:**
   ```bash
   gcloud iam service-accounts add-iam-policy-binding \
     <GCP_SERVICE_ACCOUNT>@<PROJECT_ID>.iam.gserviceaccount.com \
     --role roles/iam.workloadIdentityUser \
     --member "serviceAccount:<PROJECT_ID>.svc.id.goog[default/default]"
   ```

   Replace:
   - `<GCP_SERVICE_ACCOUNT>`: The GCP service account name (e.g., `meeting-bot-sa`).
   - `<PROJECT_ID>`: Your GCP project ID.
   - `default/default`: The Kubernetes namespace and service account name. Update if different.

2. **Annotate the Kubernetes Service Account:**
   ```bash
   kubectl annotate serviceaccount default \
     iam.gke.io/gcp-service-account=<GCP_SERVICE_ACCOUNT>@<PROJECT_ID>.iam.gserviceaccount.com
   ```

### Required GCP Permissions

The GCP Service Account bound to the Kubernetes Service Account must have the following IAM role:

- **`roles/storage.objectViewer`** on the GCS bucket.

Assign this role:

```bash
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:<GCP_SERVICE_ACCOUNT>@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

Alternatively, grant bucket-level permissions:

```bash
gcloud storage buckets add-iam-policy-binding gs://<GCS_BUCKET> \
  --member="serviceAccount:<GCP_SERVICE_ACCOUNT>@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

## Chrome Profile Archive Format

The GCS object must be a **tar.gz archive** containing the Chrome profile directory structure. The init container extracts it to `/chrome-profile`, so the archive should have this structure:

```
chrome-profile.tar.gz
├── Bookmarks
├── Cache/
├── Cookies
├── Local State
├── Preferences
├── Default/
│   ├── Cookies
│   ├── Cache/
│   └── ... (other profile subdirectories)
└── ... (other top-level Chrome profile files)
```

Create the archive:

```bash
tar -czf chrome-profile.tar.gz -C /path/to/chrome/profile .
```

Upload to GCS:

```bash
gsutil cp chrome-profile.tar.gz gs://<GCS_BUCKET>/<GCS_OBJECT_PATH>
```

## Initialization Lifecycle

1. **Pod Creation**: Kubernetes schedules the `meeting-bot` pod.
2. **Init Container Start**: The `chrome-profile-downloader` container starts.
3. **Download & Extract**: The init container runs:
   ```bash
   gsutil -m cp gs://${GCS_BUCKET}/${GCS_OBJECT_PATH} /tmp/chrome_profile.tar.gz
   tar -xzf /tmp/chrome_profile.tar.gz -C /chrome-profile/
   ```
4. **Init Success/Failure**: 
   - **Success**: The init container exits with code 0. The main `meeting-bot` container starts.
   - **Failure**: The init container exits with a non-zero code. The pod enters a `CrashLoopBackOff` state and must be manually investigated.
5. **Main Container Start**: The `meeting-bot` container mounts `/chrome-profile` and uses it for browser operations.

## Troubleshooting

### Init Container Fails to Download

**Error**: `gsutil: command not found` or `AccessDenied` (403)

**Solutions**:
1. Verify the init container image `google-cloud-cli:latest` is available in your cluster.
2. Verify Workload Identity is correctly configured (see "GCS Access via Workload Identity" above).
3. Check GCP Service Account permissions include `roles/storage.objectViewer`.
4. Verify the GCS bucket and object path in ConfigMap are correct.

### Init Container Fails to Extract

**Error**: `tar: error reading /tmp/chrome_profile.tar.gz: invalid header`

**Solutions**:
1. Verify the archive at `gs://<GCS_BUCKET>/<GCS_OBJECT_PATH>` is a valid tar.gz file.
2. Re-create and upload the archive (see "Chrome Profile Archive Format" above).

### Pod Stuck in CrashLoopBackOff

**Solutions**:
1. Describe the pod to see init container logs:
   ```bash
   kubectl describe pod <POD_NAME>
   ```
2. View init container logs:
   ```bash
   kubectl logs <POD_NAME> -c chrome-profile-downloader
   ```
3. Address any GCS authentication or file format issues shown in logs.

## Guest Fallback

If the Chrome profile is **not** available (init container fails but pod is allowed to proceed, or `BROWSER_PROFILE_DIR` points to a non-existent directory), the `meeting-bot` will join Google Meet as a **guest user**. In this mode:

- No persistent session state is available.
- The bot is prompted for admission by the meeting host.
- The bot displays the name configured in `BROWSER_GUEST_DISPLAY_NAME` (default: `Stormee.Ai`).

See [CONFIGURATION.md](./CONFIGURATION.md) for more details on guest and signed-in join flows.

## Migration from Secret-Based Profiles

Previous deployments may have used Kubernetes Secrets to mount Chrome profiles. The init container approach is superior because:

- **Scalability**: Profiles are version-controlled in GCS, not replicated as Kubernetes secrets.
- **Flexibility**: Profiles can be updated independently of the deployment manifest.
- **Security**: Workload Identity avoids hardcoding JSON keys in the cluster.

To migrate:

1. Extract the Chrome profile from the existing secret:
   ```bash
   kubectl get secret meeting-bot-browser-profile -o jsonpath='{.data.profile}' | base64 -d > profile.tar.gz
   ```
2. Upload the profile to GCS:
   ```bash
   gsutil cp profile.tar.gz gs://<GCS_BUCKET>/<GCS_OBJECT_PATH>
   ```
3. Update `meeting-bot-config` ConfigMap with `GCS_BUCKET` and `GCS_OBJECT_PATH`.
4. Deploy the updated Deployment (which includes the init container).
5. Delete the old secret:
   ```bash
   kubectl delete secret meeting-bot-browser-profile
   ```


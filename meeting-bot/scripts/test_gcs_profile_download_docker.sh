#!/bin/bash
#
# Test Chrome profile download from GCS using Docker.
#
# This script runs the GCS download test inside a Docker container with the
# Google Cloud SDK pre-installed, eliminating the need to install gcloud/gsutil
# locally.
#
# Usage:
#
#   1. Ensure you have Docker installed and running.
#
#   2. Authenticate with GCP:
#      gcloud auth application-default login
#
#   3. Set your GCS bucket details:
#      export GCS_BUCKET="meeting-bot"
#      export GCS_OBJECT_PATH="profiles/chrome_profile.tar.gz"
#
#   4. Run this script:
#      bash scripts/test_gcs_profile_download_docker.sh
#
#   5. The profile will be extracted to chrome_profile/ in your project.
#

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Chrome Profile GCS Download Test (Docker) ===${NC}"

# ---------------------------------------------------------------------------
# 1. Validate environment variables
# ---------------------------------------------------------------------------

echo -e "\n${YELLOW}[1] Checking environment variables...${NC}"

if [ -z "$GCS_BUCKET" ]; then
    echo -e "${RED}ERROR: GCS_BUCKET is not set${NC}"
    echo "Set it with: export GCS_BUCKET=\"your-bucket-name\""
    exit 1
fi

if [ -z "$GCS_OBJECT_PATH" ]; then
    echo -e "${RED}ERROR: GCS_OBJECT_PATH is not set${NC}"
    echo "Set it with: export GCS_OBJECT_PATH=\"profiles/chrome_profile.tar.gz\""
    exit 1
fi

echo -e "${GREEN}✓ GCS_BUCKET: $GCS_BUCKET${NC}"
echo -e "${GREEN}✓ GCS_OBJECT_PATH: $GCS_OBJECT_PATH${NC}"

# ---------------------------------------------------------------------------
# 2. Check Docker
# ---------------------------------------------------------------------------

echo -e "\n${YELLOW}[2] Checking Docker availability...${NC}"

if ! command -v docker &> /dev/null; then
    echo -e "${RED}ERROR: Docker is not installed or not in PATH${NC}"
    echo "Install Docker: https://docs.docker.com/install/"
    exit 1
fi

echo -e "${GREEN}✓ Docker is available${NC}"
docker --version

# ---------------------------------------------------------------------------
# 3. Check GCP credentials
# ---------------------------------------------------------------------------

echo -e "\n${YELLOW}[3] Checking GCP credentials...${NC}"

GCLOUD_CONFIG_DIR="$HOME/.config/gcloud"
ADC_FILE="$GCLOUD_CONFIG_DIR/application_default_credentials.json"

if [ ! -f "$ADC_FILE" ]; then
    echo -e "${RED}ERROR: Application Default Credentials not found${NC}"
    echo ""
    echo "Expected:"
    echo "  $ADC_FILE"
    echo ""
    echo "Run:"
    echo "  gcloud auth application-default login"
    exit 1
fi

echo -e "${GREEN}✓ Application Default Credentials found${NC}"

# ---------------------------------------------------------------------------
# 4. Create temporary directory
# ---------------------------------------------------------------------------

echo -e "\n${YELLOW}[4] Creating temporary download directory...${NC}"

TMP_DIR="/tmp/chrome_profile_test_$$"
mkdir -p "$TMP_DIR"

TMP_ARCHIVE="$TMP_DIR/chrome_profile.tar.gz"

echo -e "${GREEN}✓ Temporary directory: $TMP_DIR${NC}"

# Always clean up temporary files when the script exits.
cleanup() {
    rm -rf "$TMP_DIR"
}

trap cleanup EXIT

# ---------------------------------------------------------------------------
# 5. Run GCS test inside Docker
# ---------------------------------------------------------------------------

echo -e "\n${YELLOW}[5] Running GCS test inside Docker container...${NC}"

echo "GCS_BUCKET: $GCS_BUCKET"
echo "GCS_OBJECT_PATH: $GCS_OBJECT_PATH"
echo ""

docker run --rm \
    -v "$GCLOUD_CONFIG_DIR:/root/.config/gcloud:ro" \
    -v "$TMP_DIR:/tmp/gcs-test" \
    google-cloud-sdk:latest \
    bash -c '
        set -e

        RED="\033[0;31m"
        GREEN="\033[0;32m"
        YELLOW="\033[1;33m"
        NC="\033[0m"

        ARCHIVE="/tmp/gcs-test/chrome_profile.tar.gz"

        echo -e "${YELLOW}[Docker] Checking gcloud storage...${NC}"

        if ! gcloud storage --help > /dev/null 2>&1; then
            echo -e "${RED}ERROR: gcloud storage is not available${NC}"
            exit 1
        fi

        echo -e "${GREEN}✓ gcloud storage is available${NC}"

        # -------------------------------------------------------------------
        # Test bucket access
        # -------------------------------------------------------------------

        echo -e "\n${YELLOW}[Docker] Validating GCS access...${NC}"

        if ! gcloud storage ls "gs://$GCS_BUCKET" > /dev/null; then
            echo -e "${RED}ERROR: Cannot access gs://$GCS_BUCKET${NC}"
            echo ""
            echo "Troubleshooting:"
            echo "  1. Verify credentials:"
            echo "     gcloud auth application-default login"
            echo ""
            echo "  2. Verify the bucket:"
            echo "     gcloud storage ls gs://$GCS_BUCKET"
            echo ""
            echo "  3. Verify you have storage.objects.get permission"
            exit 1
        fi

        echo -e "${GREEN}✓ GCS bucket is accessible${NC}"

        # -------------------------------------------------------------------
        # Verify object
        # -------------------------------------------------------------------

        echo -e "\n${YELLOW}[Docker] Verifying object exists in GCS...${NC}"

        if ! gcloud storage ls "gs://$GCS_BUCKET/$GCS_OBJECT_PATH" > /dev/null; then
            echo -e "${RED}ERROR: Cannot find gs://$GCS_BUCKET/$GCS_OBJECT_PATH${NC}"
            exit 1
        fi

        echo -e "${GREEN}✓ Object exists in GCS${NC}"

        gcloud storage ls -l \
            "gs://$GCS_BUCKET/$GCS_OBJECT_PATH"

        # -------------------------------------------------------------------
        # Download
        # -------------------------------------------------------------------

        echo -e "\n${YELLOW}[Docker] Downloading Chrome profile from GCS...${NC}"

        echo "Source:"
        echo "  gs://$GCS_BUCKET/$GCS_OBJECT_PATH"

        echo ""
        echo "Destination:"
        echo "  $ARCHIVE"

        if ! gcloud storage cp \
            "gs://$GCS_BUCKET/$GCS_OBJECT_PATH" \
            "$ARCHIVE"; then

            echo -e "${RED}ERROR: Failed to download from GCS${NC}"
            exit 1
        fi

        echo -e "${GREEN}✓ Download successful${NC}"
        ls -lh "$ARCHIVE"

        # -------------------------------------------------------------------
        # Validate archive
        # -------------------------------------------------------------------

        echo -e "\n${YELLOW}[Docker] Validating archive format...${NC}"

        if ! file "$ARCHIVE" | grep -q "gzip compressed data"; then
            echo -e "${RED}ERROR: File is not a valid gzip archive${NC}"
            file "$ARCHIVE"
            exit 1
        fi

        echo -e "${GREEN}✓ Archive is valid gzip${NC}"
        file "$ARCHIVE"

        # -------------------------------------------------------------------
        # Validate tar
        # -------------------------------------------------------------------

        echo -e "\n${YELLOW}[Docker] Listing archive contents...${NC}"

        if ! tar -tzf "$ARCHIVE" | head -10; then
            echo -e "${RED}ERROR: Archive listing failed${NC}"
            exit 1
        fi

        # -------------------------------------------------------------------
        # Extract
        # -------------------------------------------------------------------

        echo -e "\n${YELLOW}[Docker] Extracting Chrome profile...${NC}"

        mkdir -p /tmp/gcs-test/chrome_profile_extracted

        if ! tar -xzf \
            "$ARCHIVE" \
            -C /tmp/gcs-test/chrome_profile_extracted; then

            echo -e "${RED}ERROR: Failed to extract archive${NC}"
            exit 1
        fi

        echo -e "${GREEN}✓ Extraction successful${NC}"

        # -------------------------------------------------------------------
        # Validate extracted profile
        # -------------------------------------------------------------------

        echo -e "\n${YELLOW}[Docker] Validating profile structure...${NC}"

        EXTRACT_DIR="/tmp/gcs-test/chrome_profile_extracted"

        if [ ! -d "$EXTRACT_DIR" ] || [ -z "$(ls -A "$EXTRACT_DIR")" ]; then
            echo -e "${RED}ERROR: Extracted directory is empty${NC}"
            exit 1
        fi

        echo -e "${GREEN}✓ Profile directory contains files${NC}"

        du -sh "$EXTRACT_DIR"

        echo ""
        echo "Contents:"
        ls -la "$EXTRACT_DIR" | head -15

        echo ""
        echo "Checking for typical Chrome profile files:"

        for file in "Preferences" "Local State" "Default" "chrome_debug.log"; do
            if [ -e "$EXTRACT_DIR/$file" ]; then
                echo -e "  ${GREEN}✓ $file${NC}"
            else
                echo -e "  ${YELLOW}✗ $file (not found)${NC}"
            fi
        done
    '

# ---------------------------------------------------------------------------
# 6. Verify Docker test succeeded
# ---------------------------------------------------------------------------

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo -e "\n${RED}Test failed inside Docker container${NC}"
    exit $EXIT_CODE
fi

# ---------------------------------------------------------------------------
# 7. Copy extracted profile to local project
# ---------------------------------------------------------------------------

echo -e "\n${YELLOW}[6] Copying profile to local directory...${NC}"

PROFILE_EXTRACT_DIR="$TMP_DIR/chrome_profile_extracted"

if [ ! -d "$PROFILE_EXTRACT_DIR" ]; then
    echo -e "${RED}ERROR: Extracted profile directory not found${NC}"
    exit 1
fi

# The archive contains a top-level chrome_profile/ directory.
# Copy its contents directly into ./chrome_profile/
SOURCE_PROFILE="$PROFILE_EXTRACT_DIR"

if [ -d "$PROFILE_EXTRACT_DIR/chrome_profile" ]; then
    SOURCE_PROFILE="$PROFILE_EXTRACT_DIR/chrome_profile"
fi

if [ -z "$(ls -A "$SOURCE_PROFILE")" ]; then
    echo -e "${RED}ERROR: Profile directory is empty${NC}"
    exit 1
fi

if [ -d "chrome_profile" ]; then
    echo "Existing chrome_profile/ directory found. Backing up..."

    mv \
        chrome_profile \
        "chrome_profile.bak.$(date +%s)"
fi

mkdir -p chrome_profile

# Copy CONTENTS, not the chrome_profile directory itself.
cp -a "$SOURCE_PROFILE/." chrome_profile/

echo -e "${GREEN}✓ Profile copied to: $(pwd)/chrome_profile${NC}"

echo ""
echo "Profile contents:"
ls -la chrome_profile | head -15

# ---------------------------------------------------------------------------
# 8. Success
# ---------------------------------------------------------------------------

echo -e "\n${GREEN}=== SUCCESS ===${NC}"
echo ""
echo "The Chrome profile has been successfully:"
echo ""
echo "  ✓ Located in GCS"
echo "  ✓ Downloaded using gcloud storage"
echo "  ✓ Validated as a gzip archive"
echo "  ✓ Extracted inside Docker"
echo "  ✓ Copied to the local project"
echo ""
echo "Profile location:"
echo "  $(pwd)/chrome_profile"
echo ""
echo "Next steps:"
echo ""
echo "  1. Run the meeting bot:"
echo "     make run"
echo ""
echo "  2. Or with Docker:"
echo "     make docker-run"
echo ""
echo "  3. Local profile:"
echo "     BROWSER_PROFILE_DIR=./chrome_profile"
echo ""
echo "  4. Kubernetes:"
echo "     BROWSER_PROFILE_DIR=/chrome-profile"
echo ""
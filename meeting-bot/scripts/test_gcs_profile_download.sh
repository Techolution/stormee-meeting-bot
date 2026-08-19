#!/bin/bash
#
# Test Chrome profile download from GCS locally.
#
# This script simulates the Kubernetes init container behavior and validates
# that the Chrome profile can be successfully downloaded, extracted, and used.
#
# Usage:
#
#   1. Set up your local environment:
     export GCS_BUCKET="meeting-bot"
     export GCS_OBJECT_PATH="profiles/chrome_profile.tar.gz"
#      gcloud auth application-default login
#
#   2. Run this script:
#      bash scripts/test_gcs_profile_download.sh
#
#   3. If successful, the profile is extracted to chrome_profile/ and ready to use.

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Chrome Profile GCS Download Test ===${NC}"

# 1. Validate environment variables
echo -e "\n${YELLOW}[1] Checking environment variables...${NC}"

if [ -z "$GCS_BUCKET" ]; then
    echo -e "${RED}ERROR: GCS_BUCKET is not set${NC}"
    echo "Set it with: export GCS_BUCKET=\"your-bucket-name\""
    exit 1
fi

if [ -z "$GCS_OBJECT_PATH" ]; then
    echo -e "${RED}ERROR: GCS_OBJECT_PATH is not set${NC}"
    echo "Set it with: export GCS_OBJECT_PATH=\"profiles/chrome-profile.tar.gz\""
    exit 1
fi

echo -e "${GREEN}✓ GCS_BUCKET: $GCS_BUCKET${NC}"
echo -e "${GREEN}✓ GCS_OBJECT_PATH: $GCS_OBJECT_PATH${NC}"

# 2. Validate gsutil is available
echo -e "\n${YELLOW}[2] Checking gcloud storage availability...${NC}"

if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}ERROR: gcloud is not installed or not in PATH${NC}"
    echo "Install Google Cloud CLI: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

if ! gcloud storage --help > /dev/null 2>&1; then
    echo -e "${RED}ERROR: gcloud storage is not available${NC}"
    exit 1
fi

echo -e "${GREEN}✓ gcloud storage is available${NC}"
gcloud version

# 3. Validate GCS access
echo -e "\n${YELLOW}[3] Testing GCS access...${NC}"

if ! gcloud storage ls "gs://$GCS_BUCKET" > /dev/null; then
    echo -e "${RED}ERROR: Cannot access gs://$GCS_BUCKET${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Verify credentials: gcloud auth application-default login"
    echo "  2. Verify the bucket: gcloud storage ls gs://$GCS_BUCKET"
    echo "  3. Verify you have storage.objects.get permission"
    exit 1
fi

echo -e "${GREEN}✓ GCS bucket is accessible${NC}"

# 4. Verify the object exists in GCS
echo -e "\n${YELLOW}[4] Verifying object exists in GCS...${NC}"

if ! gcloud storage ls "gs://$GCS_BUCKET/$GCS_OBJECT_PATH" > /dev/null; then
    echo -e "${RED}ERROR: Cannot find gs://$GCS_BUCKET/$GCS_OBJECT_PATH${NC}"
    echo ""
    echo "Available objects in $GCS_BUCKET:"
    gcloud storage ls --recursive "gs://$GCS_BUCKET/" | head -20
    exit 1
fi

echo -e "${GREEN}✓ Object exists in GCS${NC}"
gcloud storage ls -l "gs://$GCS_BUCKET/$GCS_OBJECT_PATH"

# 5. Set up temporary directories
echo -e "\n${YELLOW}[5] Setting up directories...${NC}"

TMP_DIR="/tmp/chrome_profile_test_$$"
mkdir -p "$TMP_DIR"
echo -e "${GREEN}✓ Temporary directory: $TMP_DIR${NC}"

PROFILE_ARCHIVE="$TMP_DIR/chrome_profile.tar.gz"
PROFILE_EXTRACT_DIR="$TMP_DIR/chrome_profile_extracted"
mkdir -p "$PROFILE_EXTRACT_DIR"

# 6. Download the profile from GCS
echo -e "\n${YELLOW}[6] Downloading Chrome profile from GCS...${NC}"
echo "    Source: gs://$GCS_BUCKET/$GCS_OBJECT_PATH"
echo "    Destination: $PROFILE_ARCHIVE"

if ! gcloud storage cp \
    "gs://$GCS_BUCKET/$GCS_OBJECT_PATH" \
    "$PROFILE_ARCHIVE"; then
    echo -e "${RED}ERROR: Failed to download from GCS${NC}"
    rm -rf "$TMP_DIR"
    exit 1
fi

echo -e "${GREEN}✓ Download successful${NC}"
ls -lh "$PROFILE_ARCHIVE"

# 7. Validate the archive is a valid tar.gz
echo -e "\n${YELLOW}[7] Validating archive format...${NC}"

if ! file "$PROFILE_ARCHIVE" | grep -q "gzip compressed data"; then
    echo -e "${RED}ERROR: File is not a valid gzip archive${NC}"
    file "$PROFILE_ARCHIVE"
    rm -rf "$TMP_DIR"
    exit 1
fi

echo -e "${GREEN}✓ Archive is valid gzip${NC}"
file "$PROFILE_ARCHIVE"

# 8. Extract the profile
echo -e "\n${YELLOW}[8] Extracting Chrome profile...${NC}"
echo "    Destination: $PROFILE_EXTRACT_DIR"

if ! tar -tzf "$PROFILE_ARCHIVE" | head -10; then
    echo -e "${RED}ERROR: Archive listing failed${NC}"
    rm -rf "$TMP_DIR"
    exit 1
fi

echo ""
if ! tar -xzf "$PROFILE_ARCHIVE" -C "$PROFILE_EXTRACT_DIR"; then
    echo -e "${RED}ERROR: Failed to extract archive${NC}"
    rm -rf "$TMP_DIR"
    exit 1
fi

echo -e "${GREEN}✓ Extraction successful${NC}"

# 9. Validate the extracted profile structure
echo -e "\n${YELLOW}[9] Validating profile structure...${NC}"

if [ ! -d "$PROFILE_EXTRACT_DIR" ] || [ -z "$(ls -A "$PROFILE_EXTRACT_DIR")" ]; then
    echo -e "${RED}ERROR: Extracted directory is empty${NC}"
    rm -rf "$TMP_DIR"
    exit 1
fi

echo -e "${GREEN}✓ Profile directory contains files${NC}"
du -sh "$PROFILE_EXTRACT_DIR"
echo ""
echo "Contents:"
ls -la "$PROFILE_EXTRACT_DIR" | head -15

# Check for key Chrome profile files
echo ""
echo "Checking for typical Chrome profile files:"
for file in "Preferences" "Local State" "Default" "chrome_debug.log"; do
    if [ -e "$PROFILE_EXTRACT_DIR/$file" ] || [ -d "$PROFILE_EXTRACT_DIR/$file" ]; then
        echo -e "  ${GREEN}✓ $file${NC}"
    else
        echo -e "  ${YELLOW}✗ $file (not found)${NC}"
    fi
done

# 10. Copy to local chrome_profile directory for testing
echo -e "\n${YELLOW}[10] Copying profile for local testing...${NC}"

# The tar archive may contain a top-level chrome_profile/ directory.
# Detect it and copy its contents directly into ./chrome_profile/.
SOURCE_PROFILE="$PROFILE_EXTRACT_DIR"

if [ -d "$PROFILE_EXTRACT_DIR/chrome_profile" ]; then
    SOURCE_PROFILE="$PROFILE_EXTRACT_DIR/chrome_profile"
fi

if [ ! -d "$SOURCE_PROFILE" ] || [ -z "$(ls -A "$SOURCE_PROFILE")" ]; then
    echo -e "${RED}ERROR: Extracted Chrome profile is empty${NC}"
    rm -rf "$TMP_DIR"
    exit 1
fi

if [ -d "chrome_profile" ]; then
    echo "Existing chrome_profile/ directory found. Backing up..."
    mv chrome_profile "chrome_profile.bak.$(date +%s)"
fi

mkdir -p chrome_profile

# Copy the CONTENTS of the profile, not the profile directory itself.
cp -a "$SOURCE_PROFILE/." chrome_profile/

echo -e "${GREEN}✓ Profile copied to: $(pwd)/chrome_profile${NC}"

echo ""
echo "Profile contents:"
ls -la chrome_profile | head -15

# 11. Clean up temp directory
echo -e "\n${YELLOW}[11] Cleaning up temporary files...${NC}"
rm -rf "$TMP_DIR"
echo -e "${GREEN}✓ Temporary files removed${NC}"

# 12. Success summary
echo -e "\n${GREEN}=== SUCCESS ===${NC}"
echo ""
echo "The Chrome profile has been successfully downloaded and extracted."
echo ""
echo "Profile location:"
echo "  $(pwd)/chrome_profile"
echo ""
echo "Next steps for local testing:"
echo ""
echo "  1. Run the meeting bot with the profile:"
echo "     make run"
echo ""
echo "  2. Or with Docker:"
echo "     make docker-run"
echo ""
echo "Environment:"
echo "  BROWSER_PROFILE_DIR=/chrome-profile (in Kubernetes)"
echo "  BROWSER_PROFILE_DIR=./chrome_profile (locally)"
echo ""
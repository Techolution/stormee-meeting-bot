#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Chrome Profile GCS Upload ===${NC}"

# ---------------------------------------------------------------------------
# 1. Validate environment variables
# ---------------------------------------------------------------------------

if [ -z "$GCS_BUCKET" ]; then
    echo -e "${RED}ERROR: GCS_BUCKET is not set${NC}"
    echo "Set it with:"
    echo "  export GCS_BUCKET=\"meeting-bot\""
    exit 1
fi

if [ -z "$GCS_OBJECT_PATH" ]; then
    echo -e "${RED}ERROR: GCS_OBJECT_PATH is not set${NC}"
    echo "Set it with:"
    echo "  export GCS_OBJECT_PATH=\"profiles/chrome_profile.tar.gz\""
    exit 1
fi

echo -e "${GREEN}✓ GCS_BUCKET: $GCS_BUCKET${NC}"
echo -e "${GREEN}✓ GCS_OBJECT_PATH: $GCS_OBJECT_PATH${NC}"

# ---------------------------------------------------------------------------
# 2. Validate chrome_profile directory
# ---------------------------------------------------------------------------

echo -e "\n${YELLOW}[1] Checking Chrome profile...${NC}"

if [ ! -d "chrome_profile" ]; then
    echo -e "${RED}ERROR: chrome_profile/ directory does not exist${NC}"
    exit 1
fi

if [ -z "$(ls -A chrome_profile)" ]; then
    echo -e "${RED}ERROR: chrome_profile/ directory is empty${NC}"
    exit 1
fi

echo -e "${GREEN}✓ chrome_profile/ exists${NC}"
du -sh chrome_profile

# ---------------------------------------------------------------------------
# 3. Check gcloud
# ---------------------------------------------------------------------------

echo -e "\n${YELLOW}[2] Checking gcloud storage...${NC}"

if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}ERROR: gcloud is not installed or not in PATH${NC}"
    exit 1
fi

if ! gcloud storage --help > /dev/null 2>&1; then
    echo -e "${RED}ERROR: gcloud storage is not available${NC}"
    exit 1
fi

echo -e "${GREEN}✓ gcloud storage is available${NC}"

# ---------------------------------------------------------------------------
# 4. Create archive
# ---------------------------------------------------------------------------

echo -e "\n${YELLOW}[3] Creating Chrome profile archive...${NC}"

ARCHIVE="chrome_profile.tar.gz"

rm -f "$ARCHIVE"

tar -czvf "$ARCHIVE" chrome_profile

echo -e "${GREEN}✓ Archive created${NC}"
ls -lh "$ARCHIVE"

# ---------------------------------------------------------------------------
# 5. Validate archive
# ---------------------------------------------------------------------------

echo -e "\n${YELLOW}[4] Validating archive...${NC}"

if ! tar -tzf "$ARCHIVE" > /dev/null; then
    echo -e "${RED}ERROR: Created archive is invalid${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Archive is valid${NC}"

echo ""
echo "Archive contents:"
tar -tzf "$ARCHIVE" | head -15

# ---------------------------------------------------------------------------
# 6. Upload to GCS
# ---------------------------------------------------------------------------

echo -e "\n${YELLOW}[5] Uploading archive to GCS...${NC}"

GCS_URI="gs://$GCS_BUCKET/$GCS_OBJECT_PATH"

echo "Source:"
echo "  $ARCHIVE"
echo ""
echo "Destination:"
echo "  $GCS_URI"
echo ""

if ! gcloud storage cp \
    "$ARCHIVE" \
    "$GCS_URI"; then

    echo -e "${RED}ERROR: Failed to upload archive to GCS${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Upload successful${NC}"

# ---------------------------------------------------------------------------
# 7. Verify uploaded object
# ---------------------------------------------------------------------------

echo -e "\n${YELLOW}[6] Verifying uploaded object...${NC}"

if ! gcloud storage ls "$GCS_URI"; then
    echo -e "${RED}ERROR: Uploaded object could not be found${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Object exists in GCS${NC}"

gcloud storage ls -l "$GCS_URI"

# ---------------------------------------------------------------------------
# 8. Cleanup local archive
# ---------------------------------------------------------------------------

echo -e "\n${YELLOW}[7] Cleaning up local archive...${NC}"

if [ -f "$ARCHIVE" ]; then
    rm -f "$ARCHIVE"
    echo -e "${GREEN}✓ Removed local archive: $ARCHIVE${NC}"
else
    echo -e "${YELLOW}⚠ Local archive not found (may have been cleaned up already)${NC}"
fi

echo ""
echo "Remaining disk space:"
du -sh . | awk '{print "  Current directory: " $0}'

# ---------------------------------------------------------------------------
# 9. Success
# ---------------------------------------------------------------------------

echo -e "\n${GREEN}=== SUCCESS ===${NC}"
echo ""
echo "Chrome profile uploaded successfully and local archive cleaned up."
echo ""
echo "GCS object:"
echo "  $GCS_URI"
echo ""
echo "Download from GCS with:"
echo "  gcloud storage cp $GCS_URI ."
echo ""
echo "Or use the local test script:"
echo "  bash scripts/test_gcs_profile_download.sh"
echo ""
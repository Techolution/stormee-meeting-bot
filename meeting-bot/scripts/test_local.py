from datetime import datetime, timezone
from pathlib import Path
import json

from fastapi import FastAPI, Request

app = FastAPI()

OUTPUT_DIR = Path("meeting_status_logs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/meetings/{meeting_id}/status")
async def meeting_status(meeting_id: str, request: Request):
    payload = await request.json()

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "meeting_id": meeting_id,
        "payload": payload,
    }

    # Print exactly what came in
    print(json.dumps(result, indent=2), flush=True)

    # One JSON file per request
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_file = OUTPUT_DIR / f"{meeting_id}_{timestamp}.json"

    output_file.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "meeting_id": meeting_id,
    }

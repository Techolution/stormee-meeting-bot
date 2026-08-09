from pathlib import Path
from typing import Optional, Dict, Any

import httpx


class CWCaller:
    def __init__(
        self,
        base_url: str = "https://dev.appmod.ai",
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        
        self.timeout = timeout

    async def upload_file(
        self,
        file_path: str,
        project_id: str,
        display_name: str = "string",
        is_ai: bool = True,
    ) -> Dict[str, Any]:

        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not path.is_file():
            raise ValueError(f"Not a file: {file_path}")

        # Determine MIME type
        content_type = "application/pdf"
        if path.suffix.lower() == ".pdf":
            content_type = "application/pdf"

        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if path.suffix.lower() == ".docx":
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

        data = {
            "project_id": project_id,
            "displayName": display_name,
            "isAI": is_ai,
        }

        with path.open("rb") as file:
            files = {
                "files": (
                    path.name,
                    file,
                    content_type,
                )
            }

            headers = {
                "accept": "application/json",
            }
            endpoint = f"{self.base_url}/backend/gcs/upload-files/"
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.put(
                    endpoint,
                    headers=headers,
                    data=data,
                    files=files,
                )

        response.raise_for_status()

        return response.json()
    
    


cw_caller = CWCaller()
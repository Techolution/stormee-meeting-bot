import logging
from pathlib import Path
from typing import Optional, Dict, Any
from utilities.env_config import config
from utilities.logging_context import RequestContext
import httpx

logger = logging.getLogger(__name__)

class CWCaller:
    def __init__(
        self,
        base_url: str = config.get("BACKEND_URL"),
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        
        self.timeout = timeout

    async def upload_file(
        self,
        file_path: str,
        project_id: str,
        display_name: Optional[str] = None,
        is_ai: bool = True,
    ) -> Dict[str, Any]:
        """Upload a file to the backend API.
        
        Args:
            file_path: Path to the file to upload
            project_id: Project ID for the file
            display_name: Display name for the file
            is_ai: Whether this is an AI-processed file
            
        Returns:
            API response as dictionary
            
        Raises:
            FileNotFoundError: If file does not exist
            ValueError: If path is not a file
            httpx.HTTPStatusError: If API returns error status
        """
        context = RequestContext.get_context()
        
        logger.debug(
            f"Initiating file upload [file={Path(file_path).name}, "
            f"project_id={project_id}, request_id={context.get('request_id', 'N/A')}]"
        )
        
        path = Path(file_path)

        if not path.exists():
            logger.error(
                f"File not found for upload [file_path={file_path}, "
                f"project_id={project_id}, request_id={context.get('request_id', 'N/A')}]"
            )
            raise FileNotFoundError(f"File not found: {file_path}")

        if not path.is_file():
            logger.error(
                f"Path is not a file [file_path={file_path}, "
                f"project_id={project_id}, request_id={context.get('request_id', 'N/A')}]"
            )
            raise ValueError(f"Not a file: {file_path}")

        data = {
            "project_id": project_id,
            "displayName": display_name,
            "isAI": is_ai,
        }
        if display_name:
            data['displayName'] = display_name

        try:
            with path.open("rb") as file:
                files = {
                    "files": (
                        path.name,
                        file,
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
            result = response.json()
            
            logger.info(
                f"File upload succeeded [file={path.name}, "
                f"project_id={project_id}, status={response.status_code}, "
                f"request_id={context.get('request_id', 'N/A')}, "
                f"uploaded_files={len(result.get('uploaded', []))}]"
            )
            
            return result
            
        except httpx.HTTPStatusError as e:
            logger.error(
                f"API returned error status for file upload [file_path={file_path}, "
                f"project_id={project_id}, status={e.response.status_code}, "
                f"error={e.response.text[:200]}, "
                f"request_id={context.get('request_id', 'N/A')}]"
            )
            raise
        except Exception as e:
            logger.error(
                f"File upload failed [file_path={file_path}, "
                f"project_id={project_id}, error_type={type(e).__name__}, "
                f"error_msg={str(e)[:200]}, "
                f"request_id={context.get('request_id', 'N/A')}]"
            )
            raise

    async def fetch_resumable_url_from_backend(self, payload: dict) -> str:
        """Hits your existing FastAPI router to get the Resumable Signed URL"""
        url = f"{self.base_url}/backend/gcs/generate-upload-signed-urls"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=10.0)
                if response.status_code == 200:
                    data = response.json()
                    files = data.get("files", [])
                    if files and files[0].get("status") == "ready":
                        return files[0].get("signed_url")
                    else:
                        logger.error(f"Backend returned bad status: {files}")
                else:
                    logger.error(f"Backend API failed with status {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Failed to connect to backend router: {e}")
        return ""
    
    


cw_caller = CWCaller()
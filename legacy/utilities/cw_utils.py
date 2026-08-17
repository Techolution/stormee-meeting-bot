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
                        return files[0].get("signed_url"), files[0].get("public_url")
                    else:
                        logger.error(f"Backend returned bad status: {files}")
                else:
                    logger.error(f"Backend API failed with status {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Failed to connect to backend router: {e}")
        return ""
    
    async def confirm_upload(
        self,
        project_id: str,
        files: list,
        is_ai: bool = False,
        artifact_user_name: str = "",
        artifact_user_email: str = "",
        auto_ingest: bool = False,
    ) -> Dict[str, Any]:
        """Confirm completed audio upload to trigger processing.
        
        Notifies backend that all chunks for a meeting have been uploaded,
        triggering final processing, file finalization, and optional auto-ingest.
        
        Args:
            project_id: Project ID associated with the upload
            files: List of file dictionaries with 'filename' and 'url' keys
                   Example: [{"filename": "audio_1.wav", "url": "creative-workspace/projects/..."}]
            is_ai: Whether this is AI-processed content (default False for audio)
            artifact_user_name: Name of user who created the artifact
            artifact_user_email: Email of user who created the artifact
            auto_ingest: Whether to trigger automatic ingestion (default True)
            
        Returns:
            API response as dictionary
            
        Raises:
            ValueError: If required parameters are missing
            httpx.HTTPStatusError: If API returns error status
        """
        context = RequestContext.get_context()
        
        if not project_id or not files:
            logger.error(
                f"Missing required parameters for confirm upload [project_id={project_id}, "
                f"files_count={len(files) if files else 0}, "
                f"request_id={context.get('request_id', 'N/A')}]"
            )
            raise ValueError("project_id and files are required for confirm upload")
        
        logger.info(
            f"Initiating confirm upload [project_id={project_id}, "
            f"files_count={len(files)}, auto_ingest={auto_ingest}, "
            f"request_id={context.get('request_id', 'N/A')}]"
        )
        
        # Build request payload
        payload = {
            "project_id": project_id,
            "files": files,
            "isAI": is_ai,
            "auto_ingest": auto_ingest,
        }
        
        if artifact_user_name:
            payload["artifactUserName"] = artifact_user_name
        
        if artifact_user_email:
            payload["artifactUserEmail"] = artifact_user_email
        
        try:
            endpoint = f"{self.base_url}/backend/gcs/confirm-upload"
            params = {"auto_ingest": "true" if auto_ingest else "false"}
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    endpoint,
                    json=payload,
                    params=params,
                )
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(
                f"Confirm upload succeeded [project_id={project_id}, "
                f"files_count={len(files)}, status={response.status_code}, "
                f"request_id={context.get('request_id', 'N/A')}]"
            )
            
            return result
            
        except httpx.HTTPStatusError as e:
            logger.error(
                f"API returned error status for confirm upload [project_id={project_id}, "
                f"status={e.response.status_code}, "
                f"error={e.response.text[:200]}, "
                f"request_id={context.get('request_id', 'N/A')}]"
            )
            raise
        except Exception as e:
            logger.error(
                f"Confirm upload failed [project_id={project_id}, "
                f"error_type={type(e).__name__}, "
                f"error_msg={str(e)[:200]}, "
                f"request_id={context.get('request_id', 'N/A')}]"
            )
            raise

    async def generate_meeting_mode_artifact(
        self,
        audio_name: str,
        project_id: str,
        display_name: str,
        user_email: str,
        user_name: str,
        model_type: str = "google",
        large_language_model: str = "claude-3.5-sonnet",
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a meeting mode artifact from audio.
        
        Sends audio and metadata to the backend meeting mode artifact generation endpoint
        to process and generate a meeting artifact.
        
        Args:
            audio_name: Name of the audio file (e.g., "mbn-izwe-vuw_ad71b2ac-0d1f-46a7-ac9f-2ec73ebf2efc.webm")
            project_id: Project ID for the artifact generation
            display_name: Display name for the artifact
            user_email: Email of the user creating the artifact
            user_name: Name of the user creating the artifact
            model_type: Type of model to use (default "google")
            large_language_model: LLM model to use (default "claude-3.5-sonnet")
            request_id: Optional request ID for tracking
            
        Returns:
            API response as dictionary
            
        Raises:
            ValueError: If required parameters are missing
            httpx.HTTPStatusError: If API returns error status
        """
        context = RequestContext.get_context()
        
        # Use provided request_id or get from context
        req_id = request_id or context.get('request_id', 'N/A')
        
        if not all([audio_name, project_id, display_name, user_email, user_name]):
            logger.error(
                f"Missing required parameters for meeting mode artifact generation "
                f"[audio_name={audio_name}, project_id={project_id}, "
                f"display_name={display_name}, user_email={user_email}, "
                f"user_name={user_name}, request_id={req_id}]"
            )
            raise ValueError("audio_name, project_id, display_name, user_email, and user_name are required")
        
        logger.info(
            f"Initiating meeting mode artifact generation [audio_name={audio_name}, "
            f"project_id={project_id}, display_name={display_name}, "
            f"model_type={model_type}, llm={large_language_model}, "
            f"request_id={req_id}]"
        )
        
        # Build request payload
        payload = {
            "audio_name": audio_name,
            "project_id": project_id,
            "display_name": display_name,
            "user_email": user_email,
            "user_name": user_name,
            "model_type": model_type,
            "large_language_model": large_language_model,
            "request_id": req_id,
        }
        
        try:
            endpoint = f"{self.base_url}/backend/meeting_mode_artifact/gen_mm_artifact_latest"
            headers = {
                "accept": "application/json",
                "Content-Type": "application/json",
            }
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                )
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(
                f"Meeting mode artifact generation succeeded [audio_name={audio_name}, "
                f"project_id={project_id}, status={response.status_code}, "
                f"request_id={req_id}]"
            )
            
            return result
            
        except httpx.HTTPStatusError as e:
            logger.error(
                f"API returned error status for meeting mode artifact generation "
                f"[audio_name={audio_name}, project_id={project_id}, "
                f"status={e.response.status_code}, "
                f"error={e.response.text[:200]}, "
                f"request_id={req_id}]"
            )
            raise
        except Exception as e:
            logger.error(
                f"Meeting mode artifact generation failed [audio_name={audio_name}, "
                f"project_id={project_id}, error_type={type(e).__name__}, "
                f"error_msg={str(e)[:200]}, "
                f"request_id={req_id}]"
            )
            raise


cw_caller = CWCaller()
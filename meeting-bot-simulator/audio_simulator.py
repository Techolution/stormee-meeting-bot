#!/usr/bin/env python3
"""Upload audio parts and request incremental meeting artifacts from CW."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import os
import ssl
import subprocess
import certifi
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure logging with INFO level and console output."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )


def download_audio(source: str, output_dir: str, insecure_download: bool = False) -> str:
    """Download a gs:// object or HTTP(S) URL to the output directory."""
    os.makedirs(output_dir, exist_ok=True)
    parsed = urlparse(source)
    suffix = Path(parsed.path).suffix or ".audio"
    destination = os.path.join(output_dir, f"source_audio{suffix}")

    if source.startswith("gs://"):
        try:
            subprocess.run(
                ["gsutil", "cp", source, destination],
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as error:
            raise RuntimeError("gsutil is required to download gs:// audio sources") from error
        except subprocess.CalledProcessError as error:
            raise RuntimeError(f"gsutil could not download the audio source: {error.stderr.strip()}") from error
    elif parsed.scheme in ("http", "https"):
        request = Request(source, headers={"User-Agent": "meeting-bot-audio-simulator/1.0"})
        if insecure_download:
            logger.warning("TLS certificate verification is disabled for the audio download")
            context = ssl._create_unverified_context()
        else:
            try:
                context = ssl.create_default_context(cafile=certifi.where())
            except (AttributeError, OSError) as error:
                logger.warning("Could not load certifi CA bundle; using system TLS certificates: %s", error)
                context = ssl.create_default_context()
        with urlopen(request, timeout=120, context=context) as response, open(destination, "wb") as output:
            while data := response.read(1024 * 1024):
                output.write(data)
    else:
        raise ValueError("Audio source must be a gs:// URI or an HTTP(S) signed URL")

    logger.info("Downloaded audio source to %s", destination)
    return destination


def validate_and_get_duration(audio_file: str) -> float:
    """Validate input audio file and extract duration using ffprobe.
    
    Probes the audio file using ffprobe to determine total duration in seconds.
    
    Args:
        audio_file: Path to the input audio file (MP3, WAV, FLAC, OGG, etc.)
        
    Returns:
        Duration in seconds as a float
        
    Raises:
        FileNotFoundError: If the audio file does not exist
        ValueError: If ffprobe cannot determine duration or probe fails
    """
    logger.debug("Validating audio file: %s", audio_file)
    
    # Check if file exists
    if not os.path.exists(audio_file):
        logger.error("Audio file not found: %s", audio_file)
        raise FileNotFoundError(f"Audio file not found: {audio_file}")
    
    try:
        # Use ffprobe to inspect the media container without decoding the audio.
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_file,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode != 0:
            logger.error(
                "ffprobe failed for %s: %s",
                audio_file,
                result.stderr,
            )
            raise ValueError("Invalid audio file: ffprobe could not determine duration")
        
        duration = float(result.stdout.strip())
        logger.info("Audio file duration: %.2f seconds (%.2f minutes)", duration, duration / 60)
        return duration
    
    except subprocess.TimeoutExpired:
        logger.error("ffprobe timed out for %s", audio_file)
        raise ValueError("Invalid audio file: ffprobe probe timed out")
    except ValueError as e:
        logger.error("Invalid audio file: %s", str(e))
        raise


def calculate_chunks(
    total_duration_seconds: float,
    target_duration_minutes: int,
    chunk_size_seconds: int = None,
) -> List[Tuple[float, float]]:
    """Calculate chunk boundaries based on duration ratio.
    
    Given total audio duration and a target playback duration, calculates
    the start and end times for each chunk to be extracted.
    
    For example: 15-minute audio with 5-minute target duration results in
    3 chunks of 5 minutes each: [(0, 300), (300, 600), (600, 900)].
    
    Args:
        total_duration_seconds: Total audio duration in seconds
        target_duration_minutes: Target playback duration in minutes
        chunk_size_seconds: (Optional) Duration of each chunk in seconds.
            If None, calculated as target_duration_minutes * 60
            
    Returns:
        List of tuples (start_time, end_time) for each chunk in seconds
        
    Raises:
        ValueError: If duration or target values are invalid (<=0)
    """
    logger.debug(
        "Calculating chunks: total_duration=%.2f sec, target_duration=%d min",
        total_duration_seconds,
        target_duration_minutes,
    )
    
    if total_duration_seconds <= 0:
        raise ValueError(f"Total duration must be > 0, got {total_duration_seconds}")
    
    if target_duration_minutes <= 0:
        raise ValueError(f"Target duration must be > 0, got {target_duration_minutes}")
    
    # If chunk_size not specified, use target duration
    if chunk_size_seconds is None:
        chunk_size_seconds = target_duration_minutes * 60
    
    if chunk_size_seconds <= 0:
        raise ValueError(f"Chunk size must be > 0, got {chunk_size_seconds}")
    
    chunks: List[Tuple[float, float]] = []
    current_start = 0.0
    
    while current_start < total_duration_seconds:
        current_end = min(current_start + chunk_size_seconds, total_duration_seconds)
        chunks.append((current_start, current_end))
        current_start = current_end
    
    logger.info(
        "Calculated %d chunks of %.2f seconds each",
        len(chunks),
        chunk_size_seconds,
    )
    
    for i, (start, end) in enumerate(chunks, 1):
        logger.debug("Chunk %d: [%.2f - %.2f] seconds", i, start, end)
    
    return chunks


def split_audio_into_chunks(
    audio_file: str,
    chunks: List[Tuple[float, float]],
    output_dir: str,
) -> List[Dict[str, Any]]:
    """Split audio into standalone MP3 parts using ffmpeg.
    
    For each chunk boundary, uses ffmpeg to extract the audio segment
    and saves it with a sequential name (chunk_001.mp3, chunk_002.mp3, etc.)
    
    Args:
        audio_file: Path to the input audio file
        chunks: List of (start_time, end_time) tuples in seconds
        output_dir: Directory to save chunk files
        
    Returns:
        List of chunk metadata dictionaries with keys:
        chunk_id, start_time, end_time, duration, file_path, sent_at
        
    Raises:
        RuntimeError: If ffmpeg fails to extract any chunk
    """
    logger.debug("Creating output directory: %s", output_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    chunk_metadata: List[Dict[str, Any]] = []
    
    for i, (start_time, end_time) in enumerate(chunks, 1):
        chunk_id = i
        duration = end_time - start_time
        chunk_filename = f"chunk_{chunk_id:03d}.mp3"
        chunk_path = os.path.join(output_dir, chunk_filename)
        
        logger.info(
            "Extracting chunk %d/%d: [%.2f - %.2f] seconds → %s",
            chunk_id,
            len(chunks),
            start_time,
            end_time,
            chunk_filename,
        )
        
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-ss", str(start_time),
                    "-i", audio_file,
                    "-t", str(duration),
                    "-vn",
                    "-c:a", "libmp3lame",
                    "-q:a", "4",
                    "-y",
                    chunk_path,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            if result.returncode != 0:
                logger.error(
                    "ffmpeg extraction failed for chunk %d: %s",
                    chunk_id,
                    result.stderr,
                )
                raise RuntimeError(
                    f"Failed to extract chunk {chunk_id}: ffmpeg error"
                )
            
            chunk_metadata.append({
                "chunk_id": chunk_id,
                "start_time": start_time,
                "end_time": end_time,
                "duration": duration,
                "file_path": chunk_path,
                "sent_at": None,
                "artifact_id": str(uuid.uuid4()),
                "premade_artifact_id": None,
            })
            
            logger.debug("Chunk %d extracted successfully", chunk_id)
        
        except subprocess.TimeoutExpired:
            logger.error("ffmpeg extraction timed out for chunk %d", chunk_id)
            raise RuntimeError(f"Chunk extraction timeout for chunk {chunk_id}")
    
    logger.info("Successfully extracted %d chunks", len(chunk_metadata))
    return chunk_metadata


async def simulate_incremental_replay(
    chunks: List[Dict[str, Any]],
    target_duration_minutes: int,
    cw_client: Any,
    project_id: str,
    meeting_id: str,
    display_name: str,
    user_email: str,
    user_name: str,
    participants: List[str],
    agenda: str,
    time_span_minutes: int = None,
) -> None:
    """Upload each part and request its artifact on a paced wall-clock schedule.
    
    Timeline: Each chunk is scheduled to send at an evenly-distributed time point
    across the configured time span. For N chunks and M minutes:
    - Chunk 1 sends at 0 minutes
    - Chunk 2 sends at M/(N-1) minutes
    - Chunk N sends at M minutes (approximately)
    
    Total wall-clock span for all incremental transcription requests: time_span_minutes
    (or target_duration_minutes if time_span_minutes is not specified)
    
    Args:
        chunks: List of chunk metadata dictionaries
        target_duration_minutes: Target duration in minutes (used for chunk size calculation)
        cw_client: CW utilities client for uploading and requesting artifacts
        project_id: CW project ID
        meeting_id: Meeting identifier
        display_name: Display name for the meeting
        user_email: User email address
        user_name: User display name
        participants: List of participant names
        agenda: Meeting agenda text
        time_span_minutes: Wall-clock time span in minutes for distributing chunks.
                          If None, defaults to target_duration_minutes.
    
    Concrete Examples:
    
    1. Duration=5 minutes, Chunks=6, TimeSpan=5 minutes:
       Total span: 5 min = 300 seconds
       Interval between chunks: 300 / (6-1) = 60 seconds
       Send times:
         - Chunk 1: 0 seconds (start)
         - Chunk 2: 60 seconds (~1.0 min)
         - Chunk 3: 120 seconds (~2.0 min)
         - Chunk 4: 180 seconds (~3.0 min)
         - Chunk 5: 240 seconds (~4.0 min)
         - Chunk 6: 300 seconds (~5.0 min, end)
    
    2. Duration=10 minutes, Chunks=4, TimeSpan=10 minutes:
       Total span: 10 min = 600 seconds
       Interval between chunks: 600 / (4-1) = 200 seconds
       Send times:
         - Chunk 1: 0 seconds (start)
         - Chunk 2: 200 seconds (~3.3 min)
         - Chunk 3: 400 seconds (~6.7 min)
         - Chunk 4: 600 seconds (~10.0 min, end)
    
    3. Duration=3 minutes, Chunks=2, TimeSpan=3 minutes:
       Total span: 3 min = 180 seconds
       Interval between chunks: 180 / (2-1) = 180 seconds
       Send times:
         - Chunk 1: 0 seconds (start)
         - Chunk 2: 180 seconds (~3.0 min, end)
    
    4. Duration=10 minutes, Chunks=4, TimeSpan=20 minutes:
       Total span: 20 min = 1200 seconds
       Interval between chunks: 1200 / (4-1) = 400 seconds
       Send times:
         - Chunk 1: 0 seconds (start)
         - Chunk 2: 400 seconds (~6.7 min)
         - Chunk 3: 800 seconds (~13.3 min)
         - Chunk 4: 1200 seconds (~20.0 min, end)
    """
    total_chunks = len(chunks)
    # Use time_span_minutes if provided, otherwise default to target_duration_minutes
    effective_span_minutes = time_span_minutes if time_span_minutes is not None else target_duration_minutes
    target_span = effective_span_minutes * 60
    replay_start = time.monotonic()
    processed_duration = 0.0

    logger.info(
        "Starting incremental upload: %d parts over %d minutes",
        total_chunks,
        effective_span_minutes,
    )
    
    # Log the timing schedule for transparency
    print(f"\n[INFO] Incremental Transcription Timeline")
    print(f"  Total wall-clock span: {effective_span_minutes} minutes")
    print(f"  Number of parts to send: {total_chunks}")
    if total_chunks > 1:
        print(f"  Chunk distribution: Even spacing across {effective_span_minutes} minutes")
        chunk_interval = target_span / (total_chunks - 1)
        print(f"  Interval between chunks: {chunk_interval:.1f} seconds")
        # Show example send times for clarity
        print(f"\n  Example send times (minutes):")
        example_indices = [0] + [i for i in range(1, min(total_chunks - 1, 3))] + [total_chunks - 1]
        example_indices = sorted(set(example_indices))  # Remove duplicates and sort
        for idx in example_indices:
            send_time_sec = chunk_interval * idx
            send_time_min = send_time_sec / 60
            print(f"    Part {idx + 1}: {send_time_min:.2f} min ({send_time_sec:.0f} sec)")
    else:
        print(f"  Single part: will send immediately")
    print()

    for chunk_index, chunk in enumerate(chunks):
        chunk_number = chunk_index + 1
        if total_chunks > 1:
            scheduled_elapsed = target_span * chunk_index / (total_chunks - 1)
            delay = scheduled_elapsed - (time.monotonic() - replay_start)
            if delay > 0:
                await asyncio.sleep(delay)

        start_time = chunk["start_time"]
        end_time = chunk["end_time"]
        part_name = Path(chunk["file_path"]).name
        part_display_name = f"{display_name} (Part {chunk_number})"
        status_msg = (
            f"[{timedelta(seconds=int(start_time))}-"
            f"{timedelta(seconds=int(end_time))}] Uploading part {chunk_number}/{total_chunks}"
        )
        print(status_msg)
        logger.info(status_msg)

        await cw_client.upload_file(
            file_path=Path(chunk["file_path"]),
            project_id=project_id,
            display_name=part_display_name,
            is_ai=False,
        )

        incremental_metadata = {
            "meeting_id": meeting_id,
            "segment_number": chunk_number,
            "last_duration": processed_duration,
            "is_final": chunk_number == total_chunks,
            "participants": participants,
            "agenda": agenda,
        }
        request_id = f"{meeting_id}-segment-{chunk_number}"
        result = await cw_client.generate_meeting_artifact(
            audio_name=part_name,
            project_id=project_id,
            display_name=part_display_name,
            user_email=user_email,
            user_name=user_name,
            request_id=request_id,
            incremental_mh_metadata=incremental_metadata,
            participants=participants,
        )

        chunk["sent_at"] = time.time()
        chunk["artifact_request_id"] = result.get("request_id", request_id)
        chunk["premade_artifact_id"] = result.get("premade_artifact_id")
        print(f"  Artifact generation requested for {part_name}")
        processed_duration = end_time

    elapsed_time = time.monotonic() - replay_start
    logger.info("Incremental upload completed in %.2f seconds", elapsed_time)
    print(f"\n[INFO] Incremental upload completed in {elapsed_time:.2f} seconds")


def export_metadata_to_json(
    chunks: List[Dict[str, Any]],
    output_dir: str,
) -> str:
    """Export chunk metadata to JSON file.
    
    Creates a JSON file containing metadata for all chunks including
    timing, duration, file paths, and sent timestamps.
    
    Args:
        chunks: List of chunk metadata dictionaries
        output_dir: Directory where JSON file will be saved
        
    Returns:
        Full path to the created JSON file
        
    Raises:
        IOError: If JSON file cannot be written
    """
    json_filename = "chunks_metadata.json"
    json_path = os.path.join(output_dir, json_filename)
    
    logger.info("Exporting metadata to: %s", json_path)
    
    try:
        with open(json_path, "w") as f:
            json.dump(chunks, f, indent=2, default=str)
        
        logger.info("Metadata exported successfully: %s", json_path)
        return json_path
    
    except IOError as e:
        logger.error("Failed to write metadata to JSON: %s", str(e))
        raise IOError(f"Failed to write JSON file: {json_path}") from e


def main() -> None:
    """Download, split, upload, and request incremental artifacts for an audio source."""
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Upload audio parts and request incremental meeting artifacts from CW.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python audio_simulator.py --audio-url 'gs://bucket/meeting.mp3' --duration 10 --project-id abc123
  python audio_simulator.py --audio-url 'https://signed-url...' --duration 5 --time-span 10 --project-id abc123
  python audio_simulator.py --audio-file meeting.mp3 --duration 10 --chunk-size 120 --project-id abc123
  python audio_simulator.py --audio-file meeting.mp3 --duration 10 --time-span 20 --project-id abc123
        """,
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--audio-file",
        help="Local audio file (MP3, WAV, FLAC, OGG, etc.)",
    )
    source_group.add_argument(
        "--audio-url",
        "--gsutil-url",
        "--signed-url",
        dest="audio_url",
        help="gs:// object URI or HTTP(S) signed download URL",
    )
    parser.add_argument(
        "--duration",
        type=int,
        required=True,
        help="Source-audio duration per part, in minutes (used for chunk size calculation)",
    )
    parser.add_argument(
        "--time-span",
        type=int,
        default=None,
        help="Wall-clock span for part uploads and artifact requests, in minutes (default: same as --duration)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="Source-audio duration per part, in seconds (default: --duration in seconds)",
    )
    parser.add_argument(
        "--output-dir",
        default="./audio_chunks",
        help="Directory for downloaded source, parts, and metadata",
    )
    parser.add_argument(
        "--insecure-download",
        action="store_true",
        help="Skip TLS certificate verification for HTTP(S) audio download only",
    )
    parser.add_argument(
        "--backend-url",
        default=os.getenv("CW_UTILS_URL") or os.getenv("BACKEND_URL"),
        help="CW backend URL (default: CW_UTILS_URL/BACKEND_URL from environment)",
    )
    parser.add_argument(
        "--project-id",
        default=os.getenv("PROJECT_ID") or os.getenv("DEFAULT_PROJECT_ID"),
        help="CW project ID (default: PROJECT_ID from environment/.env)",
    )
    parser.add_argument("--display-name", default="Audio simulation")
    parser.add_argument("--meeting-id", default=f"audio-simulation-{uuid.uuid4()}")
    parser.add_argument("--user-name")
    parser.add_argument("--user-email")
    parser.add_argument("--agenda", default="")
    parser.add_argument("--participant", action="append", default=[], dest="participants")

    args = parser.parse_args()

    logger.info("Audio Simulator starting...")
    logger.info("Source type: %s", "URL" if args.audio_url else "local file")
    logger.info("Target duration: %d minutes", args.duration)
    logger.info("Output directory: %s", args.output_dir)

    if args.duration <= 0:
        logger.error("Duration must be > 0, got %d", args.duration)
        sys.exit(1)

    if args.time_span is not None and args.time_span <= 0:
        logger.error("Time span must be > 0, got %d", args.time_span)
        sys.exit(1)

    if args.chunk_size is not None and args.chunk_size <= 0:
        logger.error("Chunk size must be > 0, got %d", args.chunk_size)
        sys.exit(1)

    try:
        meeting_bot_root = Path(__file__).resolve().parents[1] / "meeting-bot"
        sys.path.insert(0, str(meeting_bot_root))
        cw_module = importlib.import_module("app.clients.cw_utils")
        config_module = importlib.import_module("app.core.config")
        CWUtilsClient = cw_module.CWUtilsClient
        settings = config_module.get_settings()
        if args.backend_url:
            settings.cw_utils.base_url = args.backend_url
        project_id = args.project_id or settings.project.default_project_id
        user_name = args.user_name or settings.project.default_user_name
        user_email = args.user_email or settings.project.default_user_email
        if not settings.cw_utils.enabled:
            raise ValueError("Set CW_UTILS_URL (or pass --backend-url) to enable backend requests")
        if not project_id:
            raise ValueError("Set PROJECT_ID (or pass --project-id) to upload audio parts")

        audio_file = args.audio_file or download_audio(
            args.audio_url,
            args.output_dir,
            insecure_download=args.insecure_download,
        )
        if not os.path.isfile(audio_file):
            raise FileNotFoundError(f"Audio file not found: {audio_file}")

        total_duration = validate_and_get_duration(audio_file)
        chunks = calculate_chunks(
            total_duration,
            args.duration,
            args.chunk_size,
        )
        chunk_metadata = split_audio_into_chunks(
            audio_file,
            chunks,
            args.output_dir,
        )

        async def run_simulation() -> None:
            async with CWUtilsClient(settings.cw_utils) as cw_client:
                await simulate_incremental_replay(
                    chunk_metadata,
                    args.duration,
                    cw_client,
                    project_id,
                    args.meeting_id,
                    args.display_name,
                    user_email,
                    user_name,
                    args.participants,
                    args.agenda,
                    time_span_minutes=args.time_span,
                )

        asyncio.run(run_simulation())
        json_path = export_metadata_to_json(chunk_metadata, args.output_dir)

        effective_time_span = args.time_span if args.time_span is not None else args.duration
        print("\n" + "=" * 60)
        print("Audio Simulation Summary")
        print("=" * 60)
        print(f"Total chunks created: {len(chunk_metadata)}")
        print(f"Original duration: {total_duration / 60:.2f} minutes")
        print(f"Chunk duration target: {args.duration} minutes")
        print(f"Wall-clock time span: {effective_time_span} minutes")
        print(f"Source audio: {audio_file}")
        print(f"Output directory: {args.output_dir}")
        print(f"Metadata file: {json_path}")
        print("-" * 60)
        print("INCREMENTAL TRANSCRIPTION TIMING:")
        print(f"  Total wall-clock time span: {effective_time_span} minutes")
        print(f"  All {len(chunk_metadata)} parts will be sent over this span")
        print(f"  Check {json_path} for detailed timing of each part")
        print("=" * 60)

        logger.info("Audio simulation completed successfully")

    except Exception as error:
        logger.error("Audio simulation failed: %s", str(error))
        print(f"\n[ERROR] {str(error)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()


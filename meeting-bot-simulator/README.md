# Incremental Audio Artifact Simulator

This utility downloads or reads a long audio recording, cuts it into standalone MP3 parts, uploads each part to CW, then calls `gen_mm_artifact_latest_bg` with incremental meeting metadata. Calls are paced across the requested wall-clock duration to exercise the same part-by-part artifact flow used by the meeting bot.

## Requirements

- Python 3.10+ and the dependencies from `meeting-bot/requirements.txt`
- `ffmpeg`/`ffprobe` on `PATH`
- `gsutil` on `PATH` for `gs://` sources; HTTP(S) signed URLs need no cloud CLI
- CW backend configuration: `CW_UTILS_URL`, `PROJECT_ID`, and `JWT_SECRET` (or the equivalent settings in `meeting-bot/.env`)

Run with the Python environment used by `meeting-bot` so its CW client and dependencies are available. Install the simulator dependencies before testing: `python -m pip install -r meeting-bot/requirements.txt`. Verify the environment with `ffmpeg -version` and `ffprobe -version`.

## How the simulation works

The simulator runs this pipeline:

1. Resolve the audio source from `--audio-file`, an HTTP(S) signed URL, or a `gs://` URI. HTTPS certificate verification is enabled by default; use `--insecure-download` only for a trusted local test when certificate verification cannot be established.
2. Run `ffprobe` to validate the file and read its duration.
3. Calculate sequential source-time ranges from `--chunk-size` (or `--duration * 60` when omitted).
4. Run `ffmpeg` to create standalone `chunk_NNN.mp3` files.
5. Pace each upload across the requested `--duration`, upload the part through `CWUtilsClient`, then request artifact generation with incremental metadata.
6. Write `chunks_metadata.json` after all parts complete so the team can inspect timing, request IDs, and returned artifact IDs.

A successful run therefore validates both media preparation and the incremental CW artifact path; it does not evaluate final transcript or summary quality by itself.

## Quality-check example

Use a short local recording first so the team can validate the complete flow without waiting ten minutes or depending on a signed URL:

```bash
python meeting-bot-simulator/audio_simulator.py \
  --audio-file ./fixtures/quality-check.mp3 \
  --duration 1 \
  --chunk-size 30 \
  --output-dir ./audio_chunks/quality-check \
  --backend-url "$CW_UTILS_URL" \
  --project-id "$PROJECT_ID" \
  --meeting-id quality-check-$(date +%Y%m%d-%H%M%S) \
  --display-name "Quality check recording" \
  --participant "QA Reviewer" \
  --agenda "Validate incremental audio artifact generation"
```

Expected checks:

- Startup logs show the expected source type, duration, and output directory.
- `ffprobe` succeeds and the number of generated MP3 files matches `ceil(audio_duration / 30)`.
- Each part is uploaded before its artifact request, and the final part is sent with `is_final: true`.
- `audio_chunks/quality-check/chunks_metadata.json` contains contiguous `start_time`/`end_time` ranges, `sent_at`, `artifact_request_id`, and any returned `premade_artifact_id`.
- The command ends with `Incremental upload completed` and an `Audio Simulation Summary`.
- Confirm the resulting artifacts in CW and compare transcript, speaker attribution, and summary quality with the source recording; the simulator only records request completion and IDs.

For a signed URL, keep the complete URL inside single quotes so `&` characters are passed to Python rather than interpreted by the shell. Do not paste signed URLs into shared tickets or documentation because they contain temporary credentials.

## Usage

```bash
python meeting-bot-simulator/audio_simulator.py \
  --audio-url 'gs://bucket/path/long-meeting.mp3' \
  --duration 10
```

Or provide a signed URL:

```bash
python meeting-bot-simulator/audio_simulator.py \
  --audio-url 'https://storage.example.com/audio.mp3?signature=...' \
  --duration 5 \
  --project-id project-123
```

Local files are also supported with `--audio-file recording.mp3`. Quote signed URLs so the shell does not interpret query-string characters.

`--duration` is the total wall-clock span, in minutes, over which part upload and artifact requests are paced. By default, source audio is cut into parts of that many seconds. For example, a 30-minute file with `--duration 5` produces six 5-minute parts, with requests spread from the start through the end of the five-minute run. Set `--chunk-size` to change source audio duration per part.

## Options

- `--audio-url` (`--gsutil-url` or `--signed-url`): `gs://` object URI or HTTP(S) signed download URL. Mutually exclusive with `--audio-file`.
- `--audio-file`: local input audio.
- `--duration`: required simulated run span in minutes.
- `--chunk-size`: source audio seconds per uploaded part; defaults to `--duration * 60`.
- `--output-dir`: downloaded source, generated MP3 parts, and metadata directory; defaults to `./audio_chunks`.
- `--insecure-download`: skip TLS certificate verification for HTTP(S) audio download only. Use only for a trusted URL/network; normal certificate verification remains enabled by default. If the local Python environment reports `CERTIFICATE_VERIFY_FAILED`, install the requirements (including `certifi`) and retry before using this flag.
- `--backend-url`: CW base URL; defaults to `CW_UTILS_URL` or `BACKEND_URL`.
- `--project-id`: CW project; defaults to `PROJECT_ID`/`DEFAULT_PROJECT_ID`.
- `--meeting-id`, `--display-name`, `--user-name`, `--user-email`: metadata for artifact generation.
- `--agenda`: optional agenda metadata.
- `--participant`: participant name; may be supplied multiple times.

The simulator reuses `CWUtilsClient` from `meeting-bot`, so backend authorization follows that project’s JWT configuration. It uploads each MP3 part first, then sends a request with `segment_number`, `last_duration`, and `is_final` under `incremental_mh_metadata`. The last part is marked final.

Generated files include `chunk_NNN.mp3` and `chunks_metadata.json`. The JSON records each source time range, local part path, request ID, and premade artifact ID when returned by CW.


Example

python3 meeting-bot-simulator/audio_simulator.py \
  --audio-url 'https://storage.googleapis.com/creative-workspace/projects/6aeb5ca45acc8a332ebbf017/owy-tsjr-zne_dsm_4th_2026_031a32e0-dc92-40cf-a084-4b8b424a6f2e.mp3?X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Credential=deploy-genie%40proposal-auto-ai-internal.iam.gserviceaccount.com%2F20261104%2Fauto%2Fstorage%2Fgoog4_request&X-Goog-Date=20261104T182715Z&X-Goog-Expires=10800&X-Goog-SignedHeaders=host&X-Goog-Signature=5982fe718cad98726ce6542548120c05411dbd1abf14fa5d806234b08cc679b8b8397750aef6d53438f4f72696aec7fa2d11feb8a5eb7be0243859999a1ffaaca643ea9cef4cd4a9c9e2edb14558a6b4338db215ec1a09a311dd29559c331b954a661bb44f086b0bdd0016647dcd219fce0fd8162fb58b2f402d32e5847e9d2e4e7d056b1d4b18ad980d1a11e1bd0a2de22acb60aa932b539a63014ff51d9ef1a87571d903ca091a13f3510e248f8f2726e9bcb94c62f20cee347d277d76d7061136163dd627b87e08e20c56d8039d6b662e69909a69951d79aeeaf842c75bee3ce98f9c04f406abb96b627c340300e0c84174a2430563aacddade255f23eac2' \
  --duration 3 \
  --project-id 6aeb5ca45acc8a332ebbf017 \
--meeting-id owy-tsjr-zne_dsm_4th_2026_local \
--user-email "mehul.singh@techolution.com" \
  --agenda "Requirement AI DSM begins with a productivity review, focusing on individual ECG scores, overall app usage versus VS Code time, and active coding hours. Team members with lower VS Code or ECG metrics will briefly share context on their blockers or non-coding tasks for the day. Right after the productivity review, we will review Solution Advantage slides—a concise overview outlining core problems, target metrics, proposed solutions, solution KPIs, and identified gaps. Following this, we will dive into project-specific roadmap updates, UX reviews, and feature demos. Depending on daily priority, we will cover Requirement AI 3.0—focusing on User Story processing—and Meeting Advantage AI / MeetingBot, covering updates across meeting transcription, classification, analytics, and contextualization"
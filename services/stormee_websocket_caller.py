import asyncio
import json
import uuid

import msgpack
import websockets


WS_URL = "wss://devllmstudio.creativeworkspace.ai/stormee-asgi-server/ws"


async def call_stormee(
    session_id: str,
    user_query: str,
    chat_history: list,
    config: dict,
):
    url = f"{WS_URL}/{session_id}"

    async with websockets.connect(url) as websocket:

        request_id = f"requestId-{uuid.uuid4()}"

        payload = {
            "concierge_name": config["concierge_name"],

            "request_id": request_id,

            "agent_arguments": {
                "user_query": user_query,
            },

            "chat_history": chat_history,

            "metadata": json.dumps({
                "chat_history": chat_history,
                "rlef_id": config.get("rlef_id", ""),
                "mode_parameters": config.get("mode_parameters", {}),
                "mongo_db_id": config.get("mongo_db_id", ""),
                "template_name": config["template_name"],
                "context": config.get("context", ""),
                "user_id": config["user_id"],
                "project_id": config["project_id"],
                "delay_on_initial_message": config.get(
                    "delay_on_initial_message", 0
                ),
                "query_number": "-1",
                "userEmailId": config["userEmailId"],
                "userName": config["userName"],
                "modeName": config["modeName"],
            }),

            "session_id": session_id,

            "query_number": "-1",

            # Empty for a new request
            "resumption_token": "",
        }

        print("Sending payload:")
        print(json.dumps(payload, indent=2))

        await websocket.send(json.dumps(payload))

        async for message in websocket:

            # Server sends binary MessagePack
            if isinstance(message, bytes):

                frame = msgpack.unpackb(
                    message,
                    raw=False,
                )

                if not isinstance(frame, list) or len(frame) < 2:
                    continue

                token_id = frame[0]
                chunk = frame[1]

                print("\n--- CHUNK ---")
                print("Token:", token_id)

                # ACK the frame
                if token_id:
                    await websocket.send(
                        json.dumps({
                            "ack": token_id
                        })
                    )

                # Transcription
                transcription = chunk.get("transcription")

                if transcription:
                    print("Transcription:", transcription)

                # Custom content / thinking
                custom_content = (
                    chunk.get("custom_content")
                    or chunk.get("custom_event")
                )

                if custom_content:
                    print("Custom content:", custom_content)

                # Header
                header_message = chunk.get("header_message")

                if header_message:
                    print("Header:", header_message)

                # Audio
                audio_data = chunk.get("audio_data")

                if audio_data:
                    print(
                        "Received audio:",
                        type(audio_data),
                    )

                    # Do whatever you need with audio_data here.
                    # For example:
                    #
                    # save_audio(audio_data)

                # End of response
                if chunk.get("isEnd") is True:
                    print("Stream finished")
                    break

            # Some servers may send JSON text messages
            elif isinstance(message, str):

                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue

                print("JSON:", data)
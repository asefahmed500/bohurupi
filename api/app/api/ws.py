"""WebSocket chat streaming (PRD §2.8): /ws/chat/{conv_id}?token=<jwt>.

Inbound frames:
  {"type":"chat","text":...,"out_lang":...,"voice_id":...,"speed":...}
  {"type":"respeak","message_id":...,"voice_id":...,"lang":...,"speed":...}
  {"type":"ping"}

Outbound: status/lang/text_token/sentence_start/audio/sentence_end/done/error.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlmodel import Session

from app.db.models import Conversation, Message
from app.db.session import get_session
from app.deps import get_current_user_ws
from app.services import cache as cache_svc
from app.services.chat import stream_chat, stream_respeak

logger = logging.getLogger("bohurupi.api.ws")

router = APIRouter(tags=["ws"])


@router.websocket("/ws/chat/{conv_id}")
async def ws_chat(
    websocket: WebSocket,
    conv_id: str,
    token: str = Query(...),
    session: Session = Depends(get_session),
):
    try:
        user = get_current_user_ws(websocket, session, token=token)
    except HTTPException:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    conv = session.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        await websocket.close(code=4404, reason="Conversation not found")
        return

    await websocket.accept()
    await websocket.send_json({"type": "ready", "conversation_id": conv.id})

    busy = False

    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            break

        try:
            data = json.loads(raw)
        except ValueError:
            await websocket.send_json({"type": "error", "message": "Invalid JSON frame"})
            continue

        frame_type = data.get("type")
        if frame_type == "ping":
            await websocket.send_json({"type": "pong"})
            continue
        if busy:
            await websocket.send_json(
                {"type": "error", "message": "A response is already streaming."}
            )
            continue

        if frame_type == "chat":
            text = (data.get("text") or "").strip()
            if not text:
                await websocket.send_json({"type": "error", "message": "Empty message"})
                continue
            if not cache_svc.allow_rate(user.id, "chat", 60, 60):
                await websocket.send_json({"type": "error", "message": "Too many messages"})
                continue
            if not cache_svc.check_quota(user.id, user.plan, len(text)):
                await websocket.send_json(
                    {"type": "error", "message": "Daily quota reached. Upgrade to continue."}
                )
                continue

            busy = True
            try:
                async for frame in stream_chat(
                    session,
                    conv,
                    user.id,
                    text,
                    out_lang=data.get("out_lang") or conv.default_lang or "auto",
                    voice_id=data.get("voice_id") or conv.default_voice_id or "",
                    speed=float(data.get("speed") or 1.0),
                    style=data.get("style"),
                    effect=data.get("effect"),
                ):
                    await websocket.send_json(frame)
            except Exception:
                logger.exception("WS chat failed")
                await websocket.send_json(
                    {"type": "error", "message": "Something went wrong. Please try again."}
                )
            finally:
                busy = False

        elif frame_type == "speak":
            # Direct TTS preview (Voice Studio) — no LLM round trip
            text = (data.get("text") or "").strip()
            if not text:
                await websocket.send_json({"type": "error", "message": "Empty text"})
                continue
            if not cache_svc.check_quota(user.id, user.plan, len(text)):
                await websocket.send_json(
                    {"type": "error", "message": "Daily quota reached. Upgrade to continue."}
                )
                continue
            busy = True
            try:
                import base64 as b64mod

                from app.services import storage
                from app.services.tts import synthesize_to_wav_file

                asset, meta = await synthesize_to_wav_file(
                    session,
                    text=text,
                    lang=data.get("lang") or "en",
                    voice_id=data.get("voice_id") or "",
                    message_id=None,
                    user_id=user.id,
                    speed=float(data.get("speed") or 1.0),
                    style=data.get("style"),
                    effect=data.get("effect"),
                    pitch_semitones=float(data.get("pitch_semitones") or 0.0),
                )
                await websocket.send_json(
                    {
                        "type": "sentence_start",
                        "text": text,
                        "lang": asset.lang,
                        "engine": meta.engine,
                        "voice_id": meta.voice_id,
                        "fallback": meta.fallback_used,
                    }
                )
                pcm, sr = storage.read_wav(storage.audio_path(asset.id))
                step = sr // 5 * 2
                seq = 0
                for i in range(0, len(pcm), step):
                    seq += 1
                    await websocket.send_json(
                        {
                            "type": "audio",
                            "seq": seq,
                            "sr": sr,
                            "b64": b64mod.b64encode(pcm[i : i + step]).decode(),
                        }
                    )
                await websocket.send_json(
                    {
                        "type": "done",
                        "message_id": "",
                        "audio_id": asset.id,
                        "lang": asset.lang,
                        "text": text,
                        "engine": meta.engine,
                        "voice_id": meta.voice_id,
                        "fallback": meta.fallback_used,
                        "duration": asset.duration,
                    }
                )
            except Exception:
                logger.exception("WS speak failed")
                await websocket.send_json(
                    {"type": "error", "message": "Could not synthesize this preview."}
                )
            finally:
                busy = False

        elif frame_type == "respeak":
            message = session.get(Message, data.get("message_id") or "")
            if message is None or message.role != "assistant":
                await websocket.send_json({"type": "error", "message": "Message not found"})
                continue
            msg_conv = session.get(Conversation, message.conversation_id)
            if msg_conv is None or msg_conv.user_id != user.id:
                await websocket.send_json({"type": "error", "message": "Message not found"})
                continue

            busy = True
            try:
                async for frame in stream_respeak(
                    session,
                    message,
                    user.id,
                    voice_id=data.get("voice_id") or "",
                    lang=data.get("lang") or "",
                    speed=float(data.get("speed") or 1.0),
                    style=data.get("style"),
                    effect=data.get("effect"),
                    pitch_semitones=float(data.get("pitch_semitones") or 0.0),
                ):
                    await websocket.send_json(frame)
            except Exception:
                logger.exception("WS respeak failed")
                await websocket.send_json(
                    {"type": "error", "message": "Re-speak failed. Please try again."}
                )
            finally:
                busy = False
        else:
            await websocket.send_json({"type": "error", "message": f"Unknown frame '{frame_type}'"})

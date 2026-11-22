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
from starlette.websockets import WebSocketDisconnected

from app.db.models import Conversation, Message
from app.db.session import get_session
from app.deps import get_current_user_ws
from app.services import cache as cache_svc
from app.services.chat import stream_chat, stream_respeak

logger = logging.getLogger("bohurupi.api.ws")

router = APIRouter(tags=["ws"])


async def _ws_send(websocket: WebSocket, frame: dict) -> None:
    """Send a frame, ignoring a client that vanished mid-stream.

    Otherwise send_json raises WebSocketDisconnect and bubbles through the
    ASGI stack as a noisy 500 (audit: failure handling)."""
    try:
        await websocket.send_json(frame)
    except (WebSocketDisconnect, WebSocketDisconnected, RuntimeError):
        pass  # the receive loop will notice the closed socket


def _clamp_speed(value: object) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 1.0
    return min(2.0, max(0.5, v))


def _clamp_pitch(value: object) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(6.0, max(-6.0, v))


def _clean_text(value: object) -> str:
    text = (value or "").strip()
    return text[:8000]


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
    await _ws_send(websocket,{"type": "ready", "conversation_id": conv.id})

    busy = False

    while True:
        try:
            raw = await websocket.receive_text()
        except (WebSocketDisconnect, WebSocketDisconnected):
            break

        try:
            data = json.loads(raw)
        except ValueError:
            await _ws_send(websocket,{"type": "error", "message": "Invalid JSON frame"})
            continue

        frame_type = data.get("type")
        if frame_type == "ping":
            await _ws_send(websocket,{"type": "pong"})
            continue
        if busy:
            await _ws_send(websocket,
                {"type": "error", "message": "A response is already streaming."}
            )
            continue

        if frame_type == "chat":
            text = _clean_text(data.get("text"))
            if not text:
                await _ws_send(websocket,{"type": "error", "message": "Empty message"})
                continue
            if not cache_svc.allow_rate(user.id, "chat", 60, 60):
                await _ws_send(websocket,{"type": "error", "message": "Too many messages"})
                continue
            if not cache_svc.check_quota(user.id, user.plan, len(text)):
                await _ws_send(websocket,
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
                    speed=_clamp_speed(data.get("speed")),
                    style=data.get("style"),
                    effect=data.get("effect"),
                ):
                    await _ws_send(websocket,frame)
            except Exception:
                logger.exception("WS chat failed")
                await _ws_send(websocket,
                    {"type": "error", "message": "Something went wrong. Please try again."}
                )
            finally:
                busy = False

        elif frame_type == "speak":
            # Direct TTS preview (Voice Studio) — no LLM round trip
            text = _clean_text(data.get("text"))
            if not text:
                await _ws_send(websocket,{"type": "error", "message": "Empty text"})
                continue
            if not cache_svc.check_quota(user.id, user.plan, len(text)):
                await _ws_send(websocket,
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
                    speed=_clamp_speed(data.get("speed")),
                    style=data.get("style"),
                    effect=data.get("effect"),
                    pitch_semitones=_clamp_pitch(data.get("pitch_semitones")),
                )
                await _ws_send(websocket,
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
                    await _ws_send(websocket,
                        {
                            "type": "audio",
                            "seq": seq,
                            "sr": sr,
                            "b64": b64mod.b64encode(pcm[i : i + step]).decode(),
                        }
                    )
                await _ws_send(websocket,
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
                await _ws_send(websocket,
                    {"type": "error", "message": "Could not synthesize this preview."}
                )
            finally:
                busy = False

        elif frame_type == "respeak":
            message = session.get(Message, data.get("message_id") or "")
            if message is None or message.role != "assistant":
                await _ws_send(websocket,{"type": "error", "message": "Message not found"})
                continue
            msg_conv = session.get(Conversation, message.conversation_id)
            if msg_conv is None or msg_conv.user_id != user.id:
                await _ws_send(websocket,{"type": "error", "message": "Message not found"})
                continue

            busy = True
            try:
                async for frame in stream_respeak(
                    session,
                    message,
                    user.id,
                    voice_id=data.get("voice_id") or "",
                    lang=data.get("lang") or "",
                    speed=_clamp_speed(data.get("speed")),
                    style=data.get("style"),
                    effect=data.get("effect"),
                    pitch_semitones=_clamp_pitch(data.get("pitch_semitones")),
                ):
                    await _ws_send(websocket,frame)
            except Exception:
                logger.exception("WS respeak failed")
                await _ws_send(websocket,
                    {"type": "error", "message": "Re-speak failed. Please try again."}
                )
            finally:
                busy = False
        else:
            await _ws_send(websocket,{"type": "error", "message": f"Unknown frame '{frame_type}'"})

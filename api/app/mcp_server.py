"""Bohurupi MCP server — exposes real app capabilities to MCP clients.

Mounted at /mcp (Streamable HTTP). Requires X-MCP-API-Key when MCP_API_KEY is
configured; when unset the endpoint is not mounted at all (fail closed).
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from mcp.server.mcpserver import MCPServer
from sqlmodel import Session, select

from app.agent.llm import get_llm, llm_ready
from app.db.models import Business, Conversation, Message, SupportTicket, User
from app.db.session import engine
from app.i18n import language_list
from app.services import knowledge
from app.services.tts import synthesize_to_wav_file

logger = logging.getLogger("bohurupi.mcp")

MCP_SERVICE_EMAIL = "mcp-service@bohurupi.local"


def _service_user(session: Session) -> User:
    user = session.exec(select(User).where(User.email == MCP_SERVICE_EMAIL)).first()
    if user is None:
        user = User(email=MCP_SERVICE_EMAIL, name="MCP service", password_hash=None, role="user")
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


def create_mcp_server() -> MCPServer:
    server = MCPServer(
        name="bohurupi",
        instructions=(
            "Multilingual voice agent: languages, voices, TTS, knowledge "
            "search, support tickets and chat."
        ),
    )

    @server.tool()
    def list_languages() -> list[dict]:
        """List every language supported by the voice library."""
        return language_list()

    @server.tool()
    def list_voices(lang: str = "", gender: str = "") -> list[dict]:
        """List available voices, optionally filtered by ISO language code and gender."""
        from app.db.models import Voice

        with Session(engine) as session:
            rows = session.exec(select(Voice).where(Voice.status == "ready")).all()
        return [
            {
                "id": v.id,
                "name": v.name,
                "engine": v.engine,
                "languages": v.languages,
                "gender": v.gender,
                "styles": v.styles,
            }
            for v in rows
            if (not lang or lang in v.languages) and (not gender or v.gender == gender)
        ]

    @server.tool()
    async def synthesize_speech(text: str, lang: str = "en", voice_id: str = "") -> dict:
        """Synthesize text into a WAV asset; returns audio_id for /audio/{id}."""
        with Session(engine) as session:
            user = _service_user(session)
            asset, meta = await synthesize_to_wav_file(
                session,
                text=text[:8000],
                lang=lang,
                voice_id=voice_id,
                message_id=None,
                user_id=user.id,
            )
            return {
                "audio_id": asset.id,
                "duration": asset.duration,
                "engine": meta.engine,
                "voice_id": meta.voice_id,
                "fallback": meta.fallback_used,
            }

    @server.tool()
    def search_knowledge(business_slug: str, query: str, top_k: int = 4) -> list[dict]:
        """Search a business's knowledge base with real lexical retrieval."""
        with Session(engine) as session:
            biz = session.exec(select(Business).where(Business.slug == business_slug)).first()
            if biz is None:
                return []
            return knowledge.search(session, biz.id, query, top_k=min(10, max(1, top_k)))

    @server.tool()
    def create_support_ticket(
        business_slug: str, subject: str, message: str, customer_email: str = ""
    ) -> dict:
        """Create a real escalation ticket for a business."""
        with Session(engine) as session:
            biz = session.exec(select(Business).where(Business.slug == business_slug)).first()
            if biz is None:
                return {"error": "business not found"}
            ticket = SupportTicket(
                business_id=biz.id,
                customer_email=customer_email,
                subject=subject[:160],
                message=message[:4000],
            )
            session.add(ticket)
            session.commit()
            session.refresh(ticket)
            return {"ticket_id": ticket.id, "status": ticket.status}

    @server.tool()
    async def chat(message: str, business_slug: str = "", lang: str = "auto") -> dict:
        """Ask the AI agent (optionally grounded in a business knowledge base)."""
        if not llm_ready():
            return {"error": "AI engine not configured"}
        with Session(engine) as session:
            context = ""
            if business_slug:
                biz = session.exec(select(Business).where(Business.slug == business_slug)).first()
                if biz:
                    context = knowledge.context_for(biz.id, message, session)
            system = (
                "You are Bohurupi, a concise multilingual support assistant. "
                + (f"Reply in {lang}. " if lang != "auto" else "Reply in the user's language. ")
                + "Use the knowledge below; never invent facts.\n\nKNOWLEDGE:\n"
                + (context or "(none)")
            )
            result = await get_llm(temperature=0.3).ainvoke(
                [SystemMessage(content=system), HumanMessage(content=message)]
            )
            return {
                "reply": result.content if isinstance(result.content, str) else str(result.content)
            }

    @server.tool()
    def create_conversation(title: str = "MCP conversation", lang: str = "auto") -> dict:
        """Create a persisted conversation for the MCP service account."""
        with Session(engine) as session:
            user = _service_user(session)
            conv = Conversation(user_id=user.id, title=title[:120], default_lang=lang)
            session.add(conv)
            session.commit()
            session.refresh(conv)
            return {"conversation_id": conv.id}

    @server.tool()
    def get_conversation(conversation_id: str) -> dict:
        """Read messages from a conversation created through MCP."""
        with Session(engine) as session:
            conv = session.get(Conversation, conversation_id)
            if conv is None:
                return {"error": "not found"}
            msgs = session.exec(select(Message).where(Message.conversation_id == conv.id)).all()
            return {
                "id": conv.id,
                "title": conv.title,
                "messages": [{"role": m.role, "text": m.text} for m in msgs],
            }

    return server

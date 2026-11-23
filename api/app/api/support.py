"""Customer-support agent: businesses, knowledge base, RAG chat, tickets."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.agent.llm import get_llm, llm_ready
from app.db.models import Business, Conversation, KnowledgeDocument, Message, SupportTicket, User
from app.db.session import get_session
from app.deps import require_admin
from app.services import cache as cache_svc
from app.services import knowledge

logger = logging.getLogger("bohurupi.support")
router = APIRouter(prefix="/support", tags=["support"])

SUPPORT_SERVICE_EMAIL = "support-service@bohurupi.local"


def _service_user(session: Session) -> User:
    user = session.exec(select(User).where(User.email == SUPPORT_SERVICE_EMAIL)).first()
    if user is None:
        user = User(
            email=SUPPORT_SERVICE_EMAIL,
            name="Support service",
            password_hash=None,
            role="user",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


def _business(session: Session, slug: str) -> Business:
    biz = session.exec(select(Business).where(Business.slug == slug)).first()
    if biz is None or not biz.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found")
    return biz


# ---- schemas ----


class BusinessIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=2, max_length=60, pattern=r"^[a-z0-9-]+$")
    system_prompt: str | None = None
    languages: list[str] = ["en"]


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=10, max_length=200_000)
    source: str = ""


class ChatIn(BaseModel):
    business_slug: str
    message: str = Field(min_length=1, max_length=8000)
    email: str = ""
    conversation_id: str | None = None


class TicketPatch(BaseModel):
    status: str  # open | escalated | closed


# ---- admin: businesses + knowledge ----


@router.post("/businesses", status_code=201)
def create_business(
    body: BusinessIn, _admin: User = Depends(require_admin), session: Session = Depends(get_session)
):
    if session.exec(select(Business).where(Business.slug == body.slug)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Slug already exists")
    biz = Business(
        name=body.name,
        slug=body.slug,
        system_prompt=body.system_prompt
        or f"You are the customer-support agent for {body.name}. Be concise and helpful.",
        languages=body.languages,
    )
    session.add(biz)
    session.commit()
    session.refresh(biz)
    return biz


@router.get("/businesses/public")
def public_businesses(session: Session = Depends(get_session)):
    """Slug/name only — lets customers pick a business without admin access."""
    rows = session.exec(
        select(Business).where(Business.is_active == True)  # noqa: E712
    ).all()
    return {"businesses": [{"slug": b.slug, "name": b.name} for b in rows]}


@router.get("/businesses")
def list_businesses(_admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    return {"businesses": session.exec(select(Business)).all()}


@router.get("/businesses/{slug}")
def get_business(
    slug: str, _admin: User = Depends(require_admin), session: Session = Depends(get_session)
):
    return _business(session, slug)


@router.post("/businesses/{slug}/documents", status_code=201)
def add_document(
    slug: str,
    body: DocumentIn,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    biz = _business(session, slug)
    doc = knowledge.ingest_document(session, biz.id, body.title, body.content, body.source)
    return {"id": doc.id, "title": doc.title, "chunks": len(knowledge.split_text(body.content))}


@router.get("/businesses/{slug}/documents")
def list_documents(
    slug: str, _admin: User = Depends(require_admin), session: Session = Depends(get_session)
):
    biz = _business(session, slug)
    docs = session.exec(
        select(KnowledgeDocument).where(KnowledgeDocument.business_id == biz.id)
    ).all()
    return {"documents": docs}


@router.delete("/businesses/{slug}/documents/{doc_id}", status_code=204)
def delete_document(
    slug: str,
    doc_id: str,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    _business(session, slug)  # validate ownership
    if not knowledge.delete_document(session, doc_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")


@router.get("/businesses/{slug}/search")
def search_knowledge(
    slug: str,
    q: str,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    biz = _business(session, slug)
    return {"hits": knowledge.search(session, biz.id, q)}


# ---- public support chat ----


@router.post("/chat")
async def support_chat(
    body: ChatIn,
    request: Request,
    session: Session = Depends(get_session),
):
    host = request.client.host if request.client else "unknown"
    if not cache_svc.allow_rate(f"support:{host}", "chat", 30, 60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests")
    if not llm_ready():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI engine not configured")

    biz = _business(session, body.business_slug)
    service = _service_user(session)

    if body.conversation_id:
        conv = session.get(Conversation, body.conversation_id)
        if conv is None or conv.user_id != service.id or conv.business_id != biz.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    else:
        conv = Conversation(
            user_id=service.id,
            business_id=biz.id,
            title=f"Support: {body.message[:50]}",
        )
        session.add(conv)
        session.commit()
        session.refresh(conv)

    session.add(Message(conversation_id=conv.id, role="user", text=body.message))
    session.commit()

    context = knowledge.context_for(biz.id, body.message, session)

    def make_ticket(subject: str, message: str, email: str = "") -> dict:
        """Create a support ticket for human escalation."""
        ticket = SupportTicket(
            business_id=biz.id,
            conversation_id=conv.id,
            customer_email=email or body.email,
            subject=subject[:160],
            message=message[:4000],
        )
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        return {"ticket_id": ticket.id, "status": ticket.status}

    escalate = StructuredTool.from_function(
        func=make_ticket,
        name="create_support_ticket",
        description=(
            "Escalate to a human when you cannot resolve the issue or the "
            "customer asks for a person. Requires subject and message."
        ),
    )

    system = (
        f"{biz.system_prompt}\n"
        "Reply in the customer's language. Use the knowledge below when relevant; "
        "never invent policies or facts not in it. Keep replies short.\n\n"
        f"KNOWLEDGE:\n{context or '(no matching knowledge)'}"
    )
    llm = get_llm(temperature=0.3).bind_tools([escalate])
    messages = [SystemMessage(content=system), HumanMessage(content=body.message)]
    result = await llm.ainvoke(messages)
    ticket_id = None
    if getattr(result, "tool_calls", None):
        for call in result.tool_calls:
            if call["name"] == "create_support_ticket":
                output = escalate.invoke(call["args"])
                ticket_id = output.get("ticket_id")
                messages.append(result)
                messages.append(ToolMessage(content=str(output), tool_call_id=call["id"]))
        result = await llm.ainvoke(messages)

    reply = result.content if isinstance(result.content, str) else str(result.content)
    session.add(Message(conversation_id=conv.id, role="assistant", text=reply))
    session.commit()
    return {
        "conversation_id": conv.id,
        "reply": reply,
        "ticket_id": ticket_id,
        "knowledge_hits": len(knowledge.search(session, biz.id, body.message)),
    }


# ---- tickets ----


@router.get("/tickets")
def list_tickets(
    status: str | None = None,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    stmt = select(SupportTicket)
    if status:
        stmt = stmt.where(SupportTicket.status == status)
    return {"tickets": session.exec(stmt.order_by(SupportTicket.created_at.desc())).all()}


@router.patch("/tickets/{ticket_id}")
def patch_ticket(
    ticket_id: str,
    body: TicketPatch,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    if body.status not in ("open", "escalated", "closed"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid status")
    ticket = session.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    ticket.status = body.status
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return {
        "id": ticket.id,
        "business_id": ticket.business_id,
        "subject": ticket.subject,
        "status": ticket.status,
    }

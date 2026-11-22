"""Schema-level guarantees for the DB layer (db/architect ownership).

Covers: unique email enforcement, FK declarations on every relationship,
indexes on all FK columns, UTC created_at defaults, EngineState defaults,
and SQLite FK enforcement (the pragma session.py installs on connect).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.db import models  # noqa: F401  (register tables)
from app.db.models import (
    AudioAsset,
    Consent,
    Conversation,
    EngineState,
    Message,
    Setting,
    UsageEvent,
    User,
    Voice,
)
from app.db.session import _enable_sqlite_foreign_keys


@pytest.fixture(name="engine")
def engine_fixture():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


# ---- uniqueness ----


def test_user_email_unique_enforced(engine):
    with Session(engine) as s:
        s.add(User(email="dup@example.com"))
        s.commit()
    with Session(engine) as s, pytest.raises(IntegrityError):
        s.add(User(email="dup@example.com"))
        s.commit()


def test_user_email_unique_in_metadata():
    email = User.__table__.c.email
    assert email.unique is True
    assert email.index is True


# ---- FK declarations (every relationship must be backed by a real FK) ----


def test_fk_constraints_declared():
    expected = {
        "conversation": {("user_id", "user", "id")},
        "message": {("conversation_id", "conversation", "id")},
        "audioasset": {("message_id", "message", "id"), ("user_id", "user", "id")},
        "voice": {("owner_id", "user", "id")},
        "consent": {("voice_id", "voice", "id"), ("user_id", "user", "id")},
        "setting": {("user_id", "user", "id")},
        "usageevent": {("user_id", "user", "id")},
    }
    for table_name, wanted in expected.items():
        table = SQLModel.metadata.tables[table_name]
        got = {
            (fk.parent.name, fk.column.table.name, fk.column.name)
            for fk in table.foreign_keys
        }
        assert got == wanted, f"{table_name}: FKs {got} != expected {wanted}"


def test_fk_nullability():
    # ownership/links that may be absent
    nullable = {
        ("audioasset", "message_id"),
        ("audioasset", "user_id"),  # legacy rows + studio previews
        ("voice", "owner_id"),  # preset voices have no owner
        ("user", "password_hash"),  # OAuth-only accounts
    }
    # links the app always sets
    required = {
        ("conversation", "user_id"),
        ("message", "conversation_id"),
        ("voice", None),  # placeholder kept for symmetry
        ("consent", "user_id"),
        ("consent", "voice_id"),
        ("setting", "user_id"),
        ("usageevent", "user_id"),
    }
    required.discard(("voice", None))
    for table_name, col_name in nullable:
        assert SQLModel.metadata.tables[table_name].c[col_name].nullable is True, (
            f"{table_name}.{col_name} must stay nullable"
        )
    for table_name, col_name in required:
        assert SQLModel.metadata.tables[table_name].c[col_name].nullable is False, (
            f"{table_name}.{col_name} must stay NOT NULL"
        )


# ---- FK indexes (every FK column the app filters/joins on) ----


def test_fk_columns_are_indexed(engine):
    expected = {
        "audioasset": {"message_id", "user_id"},
        "conversation": {"user_id"},
        "message": {"conversation_id"},
        "usageevent": {"user_id"},
        "voice": {"owner_id"},
        "consent": {"user_id", "voice_id"},
    }
    insp = inspect(engine)
    for table_name, cols in expected.items():
        indexed: set[str] = set()
        for ix in insp.get_indexes(table_name):
            indexed.update(ix["column_names"])
        for col in cols:
            assert col in indexed, f"{table_name}.{col} has no index"


# ---- timestamps ----


def _default_value(col):
    default = col.default
    assert default is not None and default.is_callable, (
        f"{col.table.name}.{col.name} has no Python-side default"
    )
    try:
        return default.arg(None)  # context-taking callable
    except TypeError:
        return default.arg()  # zero-arg callable


def test_created_at_defaults_are_utc():
    models_with_created_at = (
        User,
        Conversation,
        Message,
        AudioAsset,
        Voice,
        UsageEvent,
    )
    for model in models_with_created_at:
        value = _default_value(model.__table__.c.created_at)
        assert isinstance(value, datetime), model.__name__
        assert value.tzinfo is UTC, f"{model.__name__}.created_at default not UTC"


def test_consent_accepted_at_default_is_utc():
    # Consent logs the acceptance moment itself (no created_at by design)
    value = _default_value(Consent.__table__.c.accepted_at)
    assert isinstance(value, datetime) and value.tzinfo is UTC


def test_setting_and_enginestate_have_no_created_at():
    # config/toggle rows: no timestamp column by design — guard against drift
    assert not hasattr(Setting.__table__.c, "created_at")
    assert not hasattr(EngineState.__table__.c, "created_at")


def test_conversation_updated_at_default():
    value = _default_value(Conversation.__table__.c.updated_at)
    assert isinstance(value, datetime) and value.tzinfo is UTC


# ---- EngineState (FR-9 persistence) ----


def test_engine_state_defaults_enabled(engine):
    row = EngineState(name="kokoro")
    assert row.enabled is True
    with Session(engine) as s:
        s.add(row)
        s.commit()
        s.refresh(row)
        assert row.enabled is True


# ---- SQLite FK enforcement (the pragma session.py installs) ----


def test_sqlite_fk_pragma_blocks_orphans():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(eng, "connect", _enable_sqlite_foreign_keys)
    SQLModel.metadata.create_all(eng)

    with Session(eng) as s, pytest.raises(IntegrityError):
        s.add(AudioAsset(message_id="no-such-message"))
        s.commit()

    # and valid writes still pass
    with Session(eng) as s:
        u = User(email="fk@example.com")
        s.add(u)
        s.commit()
        s.refresh(u)
        s.add(Conversation(user_id=u.id))
        s.commit()

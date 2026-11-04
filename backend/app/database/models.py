import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

class UserSession(Base):
    __tablename__ = "user_sessions"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    token: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

class Conversation(Base):
    __tablename__ = "conversations"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255), default="New Conversation")
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )

class Message(Base):
    __tablename__ = "messages"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(50))  # user, assistant, system, tool
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    
    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")

class MemoryItem(Base):
    __tablename__ = "memories"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    category: Mapped[str] = mapped_column(String(100), index=True)  # preference, fact, alias, device_mapping
    key: Mapped[str] = mapped_column(String(255), index=True)
    value: Mapped[str] = mapped_column(Text)
    context_metadata: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

class SmartDevice(Base):
    __tablename__ = "smart_devices"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), index=True)
    room: Mapped[str] = mapped_column(String(100), index=True)
    device_type: Mapped[str] = mapped_column(String(100))  # light, fan, ac, tv, plug, camera
    protocol: Mapped[str] = mapped_column(String(50))  # mqtt, http, ir, esp32
    status: Mapped[str] = mapped_column(String(50), default="offline")
    capabilities: Mapped[Any | None] = mapped_column(JSON, default=dict)
    state: Mapped[Any | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

class CameraSource(Base):
    __tablename__ = "camera_sources"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    location: Mapped[str] = mapped_column(String(100))
    stream_url: Mapped[str] = mapped_column(String(512))
    camera_type: Mapped[str] = mapped_column(String(50))  # usb, webcam, rtsp, ip
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

class ToolPermission(Base):
    __tablename__ = "tool_permissions"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tool_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    permission_level: Mapped[int] = mapped_column(Integer, default=1)  # 0 to 4
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

class ToolExecutionLog(Base):
    __tablename__ = "tool_execution_logs"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    arguments: Mapped[Any | None] = mapped_column(JSON)
    result_data: Mapped[Any | None] = mapped_column(JSON)
    success: Mapped[bool] = mapped_column(Boolean)
    verified: Mapped[bool] = mapped_column(Boolean)
    duration_ms: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

class Project(Base):
    __tablename__ = "projects"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    project_type: Mapped[str] = mapped_column(String(50))  # 3d_workspace, circuit
    data: Mapped[Any | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

class VoiceProfile(Base):
    __tablename__ = "voice_profiles"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(100))
    voice_id: Mapped[str] = mapped_column(String(255))
    pitch: Mapped[float] = mapped_column(Float, default=1.0)
    speaking_rate: Mapped[float] = mapped_column(Float, default=1.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

class Contact(Base):
    __tablename__ = "contacts"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), index=True)
    alias: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


# ---------------------------------------------------------------------------
# Brain persistence (new tables; the legacy tables above are left untouched so
# no existing data is dropped or rewritten).
# ---------------------------------------------------------------------------

class TaskRun(Base):
    __tablename__ = "brain_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(64), index=True, default="default_session")
    user_query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="CREATED", index=True)
    stage: Mapped[str] = mapped_column(String(32), default="CREATED")
    understanding: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    plan: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    routing: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    context_trace: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(60), nullable=True)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    stages: Mapped[list["RunStage"]] = relationship(
        "RunStage", back_populates="run", cascade="all, delete-orphan"
    )


class RunStage(Base):
    __tablename__ = "brain_run_stages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("brain_runs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    run: Mapped["TaskRun"] = relationship("TaskRun", back_populates="stages")


class Approval(Base):
    """A single-use, parameter-bound permission grant."""

    __tablename__ = "brain_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    step_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool: Mapped[str] = mapped_column(String(120), index=True)
    params: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    param_hash: Mapped[str] = mapped_column(String(64), index=True)
    permission_level: Mapped[int] = mapped_column(Integer, default=2)
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEntry(Base):
    __tablename__ = "brain_audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    actor: Mapped[str] = mapped_column(String(80), default="user")
    run_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    tool: Mapped[str | None] = mapped_column(String(120), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    sanitized_params: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    permission_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    outcome: Mapped[str] = mapped_column(String(30), default="allowed")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class BrainMemory(Base):
    """Long-term memory. Nothing becomes active without user confirmation."""

    __tablename__ = "brain_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    category: Mapped[str] = mapped_column(String(60), index=True)
    key: Mapped[str] = mapped_column(String(200), index=True)
    value: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    scope: Mapped[str] = mapped_column(String(20), default="global")
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_session: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UndoRecord(Base):
    __tablename__ = "brain_undo_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tool: Mapped[str] = mapped_column(String(120))
    target: Mapped[str] = mapped_column(Text)
    snapshot_dir: Mapped[str] = mapped_column(Text)
    # What the world looked like before the action, so reversal is a fact and not a hope.
    detail: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="available")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

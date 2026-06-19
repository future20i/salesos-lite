from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Enum as SAEnum, create_engine
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session
import enum


class Base(DeclarativeBase):
    pass


# ── Enums ──────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "mgr"
    REP = "rep"


class ConvSource(str, enum.Enum):
    WEB = "web"
    API = "api"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"


class ConvStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ── Tables ─────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.REP)

    assigned_convs = relationship("Conversation", back_populates="assignee",
                                  foreign_keys="Conversation.assigned_to")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_name = Column(String(128), nullable=False)
    source = Column(SAEnum(ConvSource), nullable=False, default=ConvSource.WEB)
    source_ref = Column(String(256), nullable=True)          # e.g. Telegram chat_id
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(SAEnum(ConvStatus), nullable=False, default=ConvStatus.OPEN)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    assignee = relationship("User", back_populates="assigned_convs",
                            foreign_keys=[assigned_to])
    messages = relationship("Message", back_populates="conversation",
                            order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    sender = Column(String(64), nullable=False)        # "customer" | username | "system"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    conversation = relationship("Conversation", back_populates="messages")


class Approval(Base):
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(SAEnum(ApprovalStatus), nullable=False, default=ApprovalStatus.PENDING)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    conversation = relationship("Conversation")

"""Subscription model — trial, payment, plan management."""

import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.models.base import Base
import enum


class SubscriptionStatus(str, enum.Enum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"


class Plan(str, enum.Enum):
    STARTER = "starter"
    GROWTH = "growth"
    PRO = "pro"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    plan: Mapped[Plan] = mapped_column(
        SAEnum(Plan), nullable=False, default=Plan.STARTER
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        SAEnum(SubscriptionStatus),
        nullable=False,
        default=SubscriptionStatus.TRIALING,
    )
    trial_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    trial_ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc) + timedelta(days=14),
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # PayJs order ID or similar
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def is_access_granted(self) -> bool:
        """Check if this subscription still grants access."""
        if self.status in (SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE):
            return True
        if self.status == SubscriptionStatus.PAST_DUE:
            # 7-day grace period from period end
            if self.current_period_end:
                grace_end = self.current_period_end + timedelta(days=7)
                return datetime.now(timezone.utc) < grace_end
            return False
        if self.status == SubscriptionStatus.CANCELED:
            # Access until period end
            if self.current_period_end:
                return datetime.now(timezone.utc) < self.current_period_end
            return False
        # EXPIRED — no access
        return False

    def check_trial_expired(self) -> bool:
        """Returns True if trial has expired. Caller should transition to EXPIRED."""
        if self.status == SubscriptionStatus.TRIALING:
            return datetime.now(timezone.utc) > self.trial_ends_at
        return False


class OnboardingStep(int, enum.Enum):
    START = 0
    EMAIL_SETUP = 1
    WIDGET_INSTALLED = 2
    INVITE_SENT = 3
    DONE = 4  # all steps complete, transition to inbox

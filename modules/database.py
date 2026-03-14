"""
database.py — SQLAlchemy models and DB initialization
"""

from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Boolean,
    DateTime, Text, Integer, Float
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import IntegrityError
import logging

Base = declarative_base()
logger = logging.getLogger(__name__)


class LeatherRequirement(Base):
    """Stores each discovered LinkedIn post/requirement."""
    __tablename__ = "leather_requirements"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    post_url      = Column(String(500), unique=True, nullable=False, index=True)
    post_id       = Column(String(100), unique=True)
    content       = Column(Text)
    company_name  = Column(String(200))
    poster_name   = Column(String(200))
    location      = Column(String(200))
    region        = Column(String(50))
    country_code  = Column(String(5))
    date_posted   = Column(DateTime)
    date_crawled  = Column(DateTime, default=datetime.utcnow)
    keyword_match = Column(String(200))

    # Contact fields
    contact_email   = Column(String(200))
    linkedin_profile = Column(String(300))
    company_website  = Column(String(300))
    email_valid      = Column(Boolean, default=False)

    # Email tracking
    email_sent      = Column(Boolean, default=False)
    email_sent_at   = Column(DateTime)
    email_opened    = Column(Boolean, default=False)
    email_bounced   = Column(Boolean, default=False)

    # Compliance
    opted_out       = Column(Boolean, default=False)
    data_purge_due  = Column(DateTime)

    def __repr__(self):
        return (
            f"<LeatherRequirement(id={self.id}, "
            f"company='{self.company_name}', "
            f"region='{self.region}')>"
        )


class EmailLog(Base):
    """Tracks every email attempt."""
    __tablename__ = "email_logs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    requirement_id   = Column(Integer, nullable=False)
    recipient_email  = Column(String(200))
    recipient_name   = Column(String(200))
    subject          = Column(String(300))
    status           = Column(String(50))   # sent, failed, bounced, opted_out
    error_message    = Column(Text)
    sent_at          = Column(DateTime, default=datetime.utcnow)
    message_id       = Column(String(200))  # SMTP/SendGrid message ID


class OptOutList(Base):
    """GDPR/CCPA opt-out registry."""
    __tablename__ = "opt_out_list"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    email        = Column(String(200), unique=True, nullable=False)
    opted_out_at = Column(DateTime, default=datetime.utcnow)
    reason       = Column(String(200))


class CrawlSession(Base):
    """Tracks each crawl run for monitoring."""
    __tablename__ = "crawl_sessions"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    started_at     = Column(DateTime, default=datetime.utcnow)
    completed_at   = Column(DateTime)
    keywords_used  = Column(Text)
    regions_crawled = Column(Text)
    posts_found    = Column(Integer, default=0)
    emails_sent    = Column(Integer, default=0)
    errors_count   = Column(Integer, default=0)
    status         = Column(String(50))  # running, completed, failed


def init_db(db_url: str = "sqlite:///./data/linkedin_bot.db"):
    """Initialize database and create all tables."""
    import os
    os.makedirs("./data", exist_ok=True)
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    logger.info(f"✅ Database initialized at: {db_url}")
    return engine, Session

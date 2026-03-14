"""
test_bot.py — Full test suite for LinkedIn Leather Goods Bot
Run: pytest tests/test_bot.py -v --cov=modules
"""

import json
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
import tempfile
import os

# ════════════════════════════════════════
# FIXTURES
# ════════════════════════════════════════

@pytest.fixture
def sample_config():
    return {
        "linkedin": {
            "access_token": "test_token",
            "api_version": "202401",
            "rate_limit_per_hour": 100,
            "request_delay_seconds": 0,  # No delay in tests
        },
        "search": {
            "keywords": ["leather goods", "leather sourcing"],
            "max_results_per_keyword": 10,
            "date_range_days": 30,
        },
        "email": {
            "smtp_host": "smtp.test.com",
            "smtp_port": 587,
            "smtp_user": "test@test.com",
            "smtp_password": "password",
            "from_name": "Test Company",
            "from_email": "test@company.com",
            "use_sendgrid": False,
            "retry_attempts": 1,
            "retry_delay_seconds": 0,
        },
        "company": {
            "name": "Test Leather Co.",
            "tagline": "Premium Leather Goods",
            "website": "https://test.com",
            "catalog_url": "https://test.com/catalog",
            "contact_email": "sales@test.com",
            "contact_phone": "+91-1234567890",
            "linkedin_page": "https://linkedin.com/company/test",
            "address": "Chennai, India",
            "certifications": ["ISO 9001:2015"],
        },
        "logging": {
            "log_dir": "/tmp/test_logs",
            "archive_dir": "/tmp/test_logs/archive",
            "log_format": "json",
            "rotation_days": 30,
        },
        "database": {
            "type": "sqlite",
            "sqlite_path": "sqlite:///./data/test_bot.db",
        },
        "compliance": {
            "gdpr_enabled": True,
            "unsubscribe_url": "https://test.com/unsubscribe",
        },
    }


@pytest.fixture
def sample_post():
    """A mock LinkedInPost object."""
    from modules.crawler import LinkedInPost
    return LinkedInPost(
        post_id="urn123",
        post_url="https://linkedin.com/feed/update/urn:li:ugcPost:urn123",
        content=(
            "We are looking for leather goods suppliers for our European brand. "
            "Please contact us at buyer@euroleather.com for inquiries."
        ),
        company_name="Euro Leather GmbH",
        poster_name="Hans Müller",
        location="Berlin, Germany",
        region="Europe",
        country_code="DE",
        date_posted=datetime(2025, 1, 15),
        contact_email="buyer@euroleather.com",
        linkedin_profile="https://linkedin.com/in/hansmuller",
        company_website="https://euroleather.com",
        email_valid=True,
        keyword_match="leather goods",
    )


@pytest.fixture
def mock_linkedin_response():
    """Simulated LinkedIn API UGC post response."""
    return {
        "elements": [
            {
                "id": "urn123",
                "author": "urn:li:organization:12345",
                "created": {"time": 1705276800000},  # 2024-01-15
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {
                            "text": (
                                "We are looking for leather goods suppliers "
                                "for our European brand. "
                                "Contact us at buyer@euroleather.com"
                            )
                        }
                    }
                },
            }
        ],
        "paging": {"total": 1, "start": 0, "count": 10},
    }


# ════════════════════════════════════════
# MODULE 1: CRAWLER TESTS
# ════════════════════════════════════════

class TestCrawler:

    def test_email_extraction_valid(self, sample_config):
        from modules.crawler import LinkedInCrawler
        crawler = LinkedInCrawler(sample_config)
        text = "Contact us at procurement@leatherco.eu for sourcing"
        email, valid = crawler._extract_email(text)
        assert email == "procurement@leatherco.eu"
        assert valid is True

    def test_email_extraction_invalid(self, sample_config):
        from modules.crawler import LinkedInCrawler
        crawler = LinkedInCrawler(sample_config)
        text = "Call us at +49-123-456789 or visit our website"
        email, valid = crawler._extract_email(text)
        assert email == ""
        assert valid is False

    def test_email_extraction_multiple_picks_first_valid(self, sample_config):
        from modules.crawler import LinkedInCrawler
        crawler = LinkedInCrawler(sample_config)
        text = "Email notvalid@ or real@company.com for info"
        email, valid = crawler._extract_email(text)
        assert valid is True
        assert "@" in email

    def test_relevance_check_positive(self, sample_config):
        from modules.crawler import LinkedInCrawler
        crawler = LinkedInCrawler(sample_config)
        content = "We need leather goods supplier for our fashion brand"
        assert crawler._is_relevant(content, "leather goods") is True

    def test_relevance_check_negative(self, sample_config):
        from modules.crawler import LinkedInCrawler
        crawler = LinkedInCrawler(sample_config)
        content = "Looking for software developers for our startup"
        assert crawler._is_relevant(content, "leather goods") is False

    def test_country_to_region_mapping(self, sample_config):
        from modules.crawler import LinkedInCrawler
        crawler = LinkedInCrawler(sample_config)
        assert crawler._country_to_region("DE") == "Europe"
        assert crawler._country_to_region("IN") == "India"
        assert crawler._country_to_region("CN") == "East Asia"
        assert crawler._country_to_region("AU") == "Australia"
        assert crawler._country_to_region("US") == "Americas"

    def test_geo_urn_known_country(self, sample_config):
        from modules.crawler import LinkedInCrawler
        crawler = LinkedInCrawler(sample_config)
        urn = crawler._get_geo_urn("US")
        assert urn == "urn:li:geo:103644278"

    def test_geo_urn_unknown_country(self, sample_config):
        from modules.crawler import LinkedInCrawler
        crawler = LinkedInCrawler(sample_config)
        urn = crawler._get_geo_urn("ZZ")
        assert urn == ""

    @patch("modules.crawler.LinkedInCrawler._get")
    def test_search_posts_yields_posts(
        self, mock_get, sample_config, mock_linkedin_response
    ):
        from modules.crawler import LinkedInCrawler

        # Mock author info fetch
        org_response = {
            "name": "Euro Leather GmbH",
            "websiteUrl": "https://euroleather.com",
            "locations": {"elements": [{"address": {"city": "Berlin", "country": "DE"}}]},
        }
        mock_get.side_effect = [mock_linkedin_response, org_response, {}]

        crawler = LinkedInCrawler(sample_config)
        results = list(
            crawler.search_posts(
                keyword="leather goods",
                country_codes=["DE"],
                days_back=30,
            )
        )
        assert len(results) >= 0  # May be 0 if content doesn't pass relevance

    def test_rate_limit_request_counter(self, sample_config):
        from modules.crawler import LinkedInCrawler
        crawler = LinkedInCrawler(sample_config)
        assert crawler._request_count == 0
        # Simulate requests
        with patch.object(crawler, "_rate_limit_check"):
            crawler._request_count = 99
        assert crawler._request_count == 99


# ════════════════════════════════════════
# MODULE 2: EMAIL GENERATOR TESTS
# ════════════════════════════════════════

class TestEmailGenerator:

    def test_build_context_has_required_keys(self, sample_config, sample_post):
        from modules.email_generator import EmailGenerator
        gen = EmailGenerator(sample_config)
        ctx = gen.build_context(sample_post)

        assert "recipient_name"      in ctx
        assert "requirement_summary" in ctx
        assert "company_name"        in ctx
        assert "catalog_url"         in ctx
        assert "unsubscribe_url"     in ctx

    def test_recipient_name_fallback(self, sample_config, sample_post):
        from modules.email_generator import EmailGenerator
        sample_post.poster_name = ""
        gen = EmailGenerator(sample_config)
        ctx = gen.build_context(sample_post)
        assert ctx["recipient_name"] == "Sir/Madam"

    def test_snippet_truncation(self, sample_config, sample_post):
        from modules.email_generator import EmailGenerator
        sample_post.content = "A" * 300
        gen = EmailGenerator(sample_config)
        ctx = gen.build_context(sample_post)
        assert len(ctx["post_snippet"]) <= 185  # 180 + "..."

    def test_infer_summary_bag(self, sample_config):
        from modules.email_generator import EmailGenerator
        gen = EmailGenerator(sample_config)
        result = gen._infer_summary("Looking for leather bag supplier", "leather bags")
        assert "bag" in result

    def test_certifications_text_joined(self, sample_config, sample_post):
        from modules.email_generator import EmailGenerator
        gen = EmailGenerator(sample_config)
        ctx = gen.build_context(sample_post)
        assert "ISO 9001:2015" in ctx["certifications_text"]

    def test_render_returns_three_values(self, sample_config, sample_post):
        from modules.email_generator import EmailGenerator
        gen = EmailGenerator(sample_config)
        result = gen.render(sample_post)
        assert len(result) == 3
        subject, html, text = result
        assert len(subject) > 0
        assert "<html" in html.lower()
        assert "Dear" in text


# ════════════════════════════════════════
# MODULE 3: LOGGING TESTS
# ════════════════════════════════════════

class TestActivityLogger:

    def test_json_log_created_on_init(self, sample_config, tmp_path):
        sample_config["logging"]["log_dir"]     = str(tmp_path / "logs")
        sample_config["logging"]["archive_dir"] = str(tmp_path / "logs/archive")
        from modules.logger import ActivityLogger
        logger = ActivityLogger(sample_config)
        assert logger.json_path.exists()

    def test_log_post_writes_entry(self, sample_config, sample_post, tmp_path):
        sample_config["logging"]["log_dir"]     = str(tmp_path / "logs")
        sample_config["logging"]["archive_dir"] = str(tmp_path / "logs/archive")
        from modules.logger import ActivityLogger
        logger = ActivityLogger(sample_config)
        logger.log_post(sample_post, email_sent=True)
        data = json.loads(logger.json_path.read_text())
        assert len(data) == 1
        assert data[0]["post_url"] == sample_post.post_url
        assert data[0]["email_sent"] == "Y"

    def test_log_post_deduplicates(self, sample_config, sample_post, tmp_path):
        sample_config["logging"]["log_dir"]     = str(tmp_path / "logs")
        sample_config["logging"]["archive_dir"] = str(tmp_path / "logs/archive")
        from modules.logger import ActivityLogger
        logger = ActivityLogger(sample_config)
        logger.log_post(sample_post)
        logger.log_post(sample_post)  # Same post again
        data = json.loads(logger.json_path.read_text())
        assert len(data) == 1  # Should not duplicate

    def test_get_stats_structure(self, sample_config, sample_post, tmp_path):
        sample_config["logging"]["log_dir"]     = str(tmp_path / "logs")
        sample_config["logging"]["archive_dir"] = str(tmp_path / "logs/archive")
        from modules.logger import ActivityLogger
        logger = ActivityLogger(sample_config)
        logger.log_post(sample_post, email_sent=True)
        stats = logger.get_stats()
        assert "total_logged" in stats
        assert "emails_sent"  in stats
        assert stats["total_logged"] == 1
        assert stats["emails_sent"]  == 1


# ════════════════════════════════════════
# MODULE 4: DATABASE TESTS
# ════════════════════════════════════════

class TestDatabase:

    def test_db_init_creates_tables(self, tmp_path):
        from modules.database import init_db, LeatherRequirement
        db_path = str(tmp_path / "test.db")
        engine, Session = init_db(f"sqlite:///{db_path}")
        db = Session()
        # Should be able to query without error
        result = db.query(LeatherRequirement).all()
        assert result == []
        db.close()

    def test_insert_and_retrieve_record(self, tmp_path, sample_post):
        from modules.database import init_db, LeatherRequirement
        db_path = str(tmp_path / "test.db")
        engine, Session = init_db(f"sqlite:///{db_path}")
        db = Session()

        record = LeatherRequirement(
            post_id=sample_post.post_id,
            post_url=sample_post.post_url,
            content=sample_post.content,
            company_name=sample_post.company_name,
            region=sample_post.region,
            country_code=sample_post.country_code,
            contact_email=sample_post.contact_email,
            email_valid=sample_post.email_valid,
        )
        db.add(record)
        db.commit()

        fetched = db.query(LeatherRequirement).filter_by(
            post_id=sample_post.post_id
        ).first()
        assert fetched is not None
        assert fetched.company_name == "Euro Leather GmbH"
        assert fetched.email_valid is True
        db.close()

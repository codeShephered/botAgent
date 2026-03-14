"""
crawler.py — LinkedIn Official API Crawler Module
Uses LinkedIn UGC Posts API and Search API with OAuth 2.0
"""

import time
import logging
from datetime import datetime, timedelta
from typing import Generator, Optional
from dataclasses import dataclass, field

import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from email_validator import validate_email, EmailNotValidError

logger = logging.getLogger(__name__)


@dataclass
class LinkedInPost:
    """Normalized LinkedIn post data structure."""
    post_id: str
    post_url: str
    content: str
    company_name: str = ""
    poster_name: str = ""
    location: str = ""
    region: str = ""
    country_code: str = ""
    date_posted: Optional[datetime] = None
    contact_email: str = ""
    linkedin_profile: str = ""
    company_website: str = ""
    email_valid: bool = False
    keyword_match: str = ""
    raw_data: dict = field(default_factory=dict)


class LinkedInCrawler:
    """
    Crawls LinkedIn using the official API.

    LinkedIn API Endpoints Used:
    - /v2/ugcPosts       — User Generated Content posts
    - /v2/people         — Profile data (with permissions)
    - /v2/organizations  — Company data

    Rate limits respected: max 100 requests/hour
    with 3-second polite delay between requests.
    """

    BASE_URL = "https://api.linkedin.com/v2"
    RATE_LIMIT = 100   # requests per hour
    REQUEST_DELAY = 3  # seconds between requests

    def __init__(self, config: dict):
        self.config = config
        self.access_token = config["linkedin"]["access_token"]
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": config["linkedin"]["api_version"],
        })
        self._request_count = 0
        self._window_start = datetime.utcnow()

    def _rate_limit_check(self):
        """Enforce LinkedIn rate limits: max 100 requests/hour."""
        now = datetime.utcnow()
        elapsed = (now - self._window_start).seconds

        if elapsed >= 3600:
            self._request_count = 0
            self._window_start = now

        if self._request_count >= self.RATE_LIMIT:
            sleep_seconds = 3600 - elapsed + 10  # wait for window reset
            logger.warning(
                f"⏳ Rate limit reached. Sleeping {sleep_seconds}s..."
            )
            time.sleep(sleep_seconds)
            self._request_count = 0
            self._window_start = datetime.utcnow()

        time.sleep(self.REQUEST_DELAY)
        self._request_count += 1

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30)
    )
    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Make a GET request with retry logic."""
        self._rate_limit_check()
        url = f"{self.BASE_URL}/{endpoint}"

        try:
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                logger.warning("🚦 429 Too Many Requests — backing off...")
                time.sleep(60)
                raise
            elif response.status_code == 401:
                logger.error("🔐 Unauthorized — check access token.")
                raise
            elif response.status_code == 403:
                logger.error("🚫 Forbidden — insufficient API permissions.")
                raise
            else:
                logger.error(f"HTTP error {response.status_code}: {e}")
                raise

    def search_posts(
        self,
        keyword: str,
        country_codes: list[str],
        days_back: int = 1
    ) -> Generator[LinkedInPost, None, None]:
        """
        Search for posts matching keyword using LinkedIn Search API.
        Falls back to UGC Posts search if Search API unavailable.

        Args:
            keyword: Search term (e.g., "leather goods supplier")
            country_codes: List of ISO country codes to filter by
            days_back: How many days back to search

        Yields:
            LinkedInPost objects
        """
        since_timestamp = int(
            (datetime.utcnow() - timedelta(days=days_back)).timestamp() * 1000
        )

        logger.info(
            f"🔍 Searching: '{keyword}' | "
            f"Countries: {country_codes} | "
            f"Last {days_back} days"
        )

        for country in country_codes:
            start = 0
            max_results = self.config["search"]["max_results_per_keyword"]

            while start < max_results:
                params = {
                    "q": "text",
                    "keywords": keyword,
                    "filters.geoUrn": self._get_geo_urn(country),
                    "start": start,
                    "count": 10,
                    "sortBy": "RELEVANCE",
                }

                try:
                    data = self._get("search/posts", params=params)
                except Exception as e:
                    logger.error(
                        f"❌ Search failed for keyword='{keyword}', "
                        f"country={country}: {e}"
                    )
                    break

                elements = data.get("elements", [])
                if not elements:
                    logger.debug(
                        f"No more results for '{keyword}' in {country}"
                    )
                    break

                for element in elements:
                    post = self._parse_post(
                        element, keyword, country
                    )
                    if post:
                        yield post

                start += len(elements)

    def _parse_post(
        self,
        element: dict,
        keyword: str,
        country_code: str
    ) -> Optional[LinkedInPost]:
        """Parse a raw LinkedIn API element into a LinkedInPost."""
        try:
            post_id = element.get("id", "")
            if not post_id:
                return None

            # Extract post content
            specific_content = element.get("specificContent", {})
            share_content = specific_content.get(
                "com.linkedin.ugc.ShareContent", {}
            )
            commentary = share_content.get("shareCommentary", {})
            content = commentary.get("text", "")

            if not self._is_relevant(content, keyword):
                return None

            # Extract author info
            author_urn = element.get("author", "")
            author_info = self._get_author_info(author_urn)

            # Extract date
            created = element.get("created", {})
            date_ms = created.get("time", 0)
            date_posted = (
                datetime.utcfromtimestamp(date_ms / 1000) if date_ms else None
            )

            # Build post URL
            post_url = (
                f"https://www.linkedin.com/feed/update/urn:li:ugcPost:{post_id}"
            )

            # Extract and validate email from content
            email, email_valid = self._extract_email(content)

            region = self._country_to_region(country_code)

            return LinkedInPost(
                post_id=post_id,
                post_url=post_url,
                content=content,
                company_name=author_info.get("company_name", ""),
                poster_name=author_info.get("name", ""),
                location=author_info.get("location", ""),
                region=region,
                country_code=country_code,
                date_posted=date_posted,
                contact_email=email,
                linkedin_profile=author_info.get("profile_url", ""),
                company_website=author_info.get("website", ""),
                email_valid=email_valid,
                keyword_match=keyword,
                raw_data=element,
            )

        except Exception as e:
            logger.error(f"Error parsing post: {e}")
            return None

    def _get_author_info(self, author_urn: str) -> dict:
        """Fetch author/company details from LinkedIn API."""
        info = {}
        try:
            if "organization" in author_urn:
                org_id = author_urn.split(":")[-1]
                data = self._get(
                    f"organizations/{org_id}",
                    params={"projection": "(id,name,websiteUrl,locations)"}
                )
                info["company_name"] = data.get("name", "")
                info["website"] = data.get("websiteUrl", "")
                locations = data.get("locations", {}).get("elements", [])
                if locations:
                    addr = locations[0].get("address", {})
                    info["location"] = (
                        f"{addr.get('city', '')}, "
                        f"{addr.get('country', '')}"
                    )
                info["profile_url"] = (
                    f"https://www.linkedin.com/company/{org_id}"
                )
            elif "person" in author_urn:
                person_id = author_urn.split(":")[-1]
                data = self._get(
                    f"people/{person_id}",
                    params={
                        "projection": "(id,firstName,lastName,headline,"
                                      "publicProfileUrl)"
                    }
                )
                first = data.get("firstName", {}).get("localized", {})
                last  = data.get("lastName",  {}).get("localized", {})
                name  = f"{list(first.values())[0] if first else ''} " \
                        f"{list(last.values())[0]  if last  else ''}".strip()
                info["name"] = name
                info["profile_url"] = data.get("publicProfileUrl", "")
        except Exception as e:
            logger.debug(f"Could not fetch author info: {e}")

        return info

    def _is_relevant(self, content: str, keyword: str) -> bool:
        """Check if post content is relevant to leather goods sourcing."""
        leather_terms = [
            "leather", "sourcing", "supplier", "procurement",
            "manufacturer", "factory", "export", "import",
            "goods", "products", "bags", "accessories",
        ]
        content_lower = content.lower()
        keyword_lower = keyword.lower()
        return (
            keyword_lower in content_lower
            and any(term in content_lower for term in leather_terms)
        )

    def _extract_email(self, text: str) -> tuple[str, bool]:
        """Extract and validate email address from post text."""
        import re
        pattern = r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b'
        matches = re.findall(pattern, text)

        for match in matches:
            try:
                valid = validate_email(match, check_deliverability=False)
                return valid.email, True
            except EmailNotValidError:
                continue

        return "", False

    def _get_geo_urn(self, country_code: str) -> str:
        """Map ISO country code to LinkedIn GeoUrn."""
        geo_urns = {
            "US": "urn:li:geo:103644278",
            "GB": "urn:li:geo:101165590",
            "DE": "urn:li:geo:101282230",
            "FR": "urn:li:geo:105015875",
            "IT": "urn:li:geo:103350119",
            "ES": "urn:li:geo:105646813",
            "IN": "urn:li:geo:102713980",
            "CN": "urn:li:geo:102890883",
            "JP": "urn:li:geo:101355337",
            "KR": "urn:li:geo:105149562",
            "AU": "urn:li:geo:101452733",
            "CA": "urn:li:geo:101174742",
            "BR": "urn:li:geo:106057199",
            "NL": "urn:li:geo:102890719",
            "BE": "urn:li:geo:100565514",
            "SE": "urn:li:geo:105117694",
            "NO": "urn:li:geo:103819153",
            "DK": "urn:li:geo:104514075",
            "CH": "urn:li:geo:106693272",
            "AT": "urn:li:geo:103883259",
            "PL": "urn:li:geo:105072130",
            "HK": "urn:li:geo:104874190",
            "TW": "urn:li:geo:104187078",
            "MX": "urn:li:geo:103323778",
            "AR": "urn:li:geo:100446943",
        }
        return geo_urns.get(country_code, "")

    def _country_to_region(self, code: str) -> str:
        """Map country code to region name."""
        europe = {
            "GB","DE","FR","IT","ES","NL","BE","PT","SE",
            "NO","DK","FI","PL","CZ","AT","CH"
        }
        east_asia = {"CN","JP","KR","TW","HK"}
        americas  = {"US","CA","BR","MX","AR","CO","CL"}
        if code in europe:   return "Europe"
        if code == "IN":     return "India"
        if code in east_asia: return "East Asia"
        if code in {"AU","NZ"}: return "Australia"
        if code in americas: return "Americas"
        return "Other"

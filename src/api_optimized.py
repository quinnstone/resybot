"""
Resy API Client - Optimized for stability and performance

Key optimizations:
- Connection pooling with limits to prevent memory leaks
- Automatic retry with exponential backoff
- Proper session cleanup
- Reduced timeouts for faster failure detection
- Memory-efficient response handling
"""
import gc
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from src.config import Config


class ResyAPIError(Exception):
    """Custom exception for Resy API errors"""
    pass


class ResyAPI:
    BASE_URL = "https://api.resy.com"
    API_KEY = "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"

    def __init__(self):
        self.config = Config
        self.auth_token = None
        self._cached_headers = None
        self._setup_session()

    def _setup_session(self):
        """Configure session with connection pooling and retry logic"""
        self.session = requests.Session()

        # Retry only on connection errors, NOT on 5xx (we handle those ourselves
        # to keep polling fast - urllib3 retries add hidden backoff delays)
        retry_strategy = Retry(
            total=1,
            backoff_factor=0.1,
            status_forcelist=[502, 503],
            allowed_methods=["GET", "POST"]
        )

        # Configure connection pooling (limit connections to prevent memory issues)
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=2,
            pool_maxsize=5,
            pool_block=False
        )

        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def reset_session(self):
        """Reset session to clear any stale connections"""
        try:
            self.session.close()
        except:
            pass
        self._cached_headers = None
        self._setup_session()
        gc.collect()

    def cleanup(self):
        """Cleanup resources"""
        try:
            self.session.close()
        except:
            pass

    @property
    def headers(self):
        """Build headers for API requests (cached, rebuilt only when token changes)"""
        if self._cached_headers is None or self._cached_headers.get("X-Resy-Auth-Token") != self.auth_token:
            h = {
                "Authorization": f'ResyAPI api_key="{self.API_KEY}"',
                "Origin": "https://resy.com",
                "Referer": "https://resy.com/",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Connection": "keep-alive",
            }
            if self.auth_token:
                h["X-Resy-Auth-Token"] = self.auth_token
            self._cached_headers = h
        return self._cached_headers

    def login(self):
        """Authenticate with Resy"""
        url = f"{self.BASE_URL}/3/auth/password"
        data = {
            "email": self.config.RESY_EMAIL,
            "password": self.config.RESY_PASSWORD,
        }

        try:
            resp = self.session.post(url, headers=self.headers, data=data, timeout=8)

            if resp.status_code in (401, 419):
                raise ResyAPIError("Invalid email or password")
            elif resp.status_code == 429:
                raise ResyAPIError("Rate limited")
            elif resp.status_code != 200:
                raise ResyAPIError(f"Login failed: {resp.status_code}")

            self.auth_token = resp.json().get("token")
            if not self.auth_token:
                raise ResyAPIError("No token in response")

            return self.auth_token

        except requests.RequestException as e:
            raise ResyAPIError(f"Network error: {e}")

    def resolve_venue(self, url):
        """Resolve a Resy venue URL to (venue_id, venue_name).

        Accepts formats:
          https://resy.com/cities/ny/torrisi
          resy.com/cities/ny/torrisi
          ny/torrisi
        """
        # Extract city and slug from URL
        url = url.split('?')[0].rstrip('/')  # strip query params first
        if '/cities/' in url:
            parts = url.split('/cities/')[1].split('/')
        else:
            parts = url.split('/')

        # Skip "venues" segment if present: cities/{city}/venues/{slug}
        if 'venues' in parts:
            parts.remove('venues')

        if len(parts) < 2:
            raise ResyAPIError(f"Can't parse venue URL: {url} (expected city/slug)")

        city = parts[0]
        slug = parts[1]

        try:
            resp = self.session.get(
                f"{self.BASE_URL}/3/venue",
                headers=self.headers,
                params={"url_slug": slug, "location": city},
                timeout=8
            )
            if resp.status_code != 200:
                raise ResyAPIError(f"Venue lookup failed: {resp.status_code}")

            data = resp.json()
            venue_id = data.get("id", {}).get("resy")
            venue_name = data.get("name", slug.title())

            if not venue_id:
                raise ResyAPIError(f"No venue ID found for {city}/{slug}")

            return venue_id, venue_name

        except requests.RequestException as e:
            raise ResyAPIError(f"Network error resolving venue: {e}")

    def is_authenticated(self):
        return self.auth_token is not None

    def get_payment_methods(self):
        """Get payment methods"""
        if not self.is_authenticated():
            raise ResyAPIError("Not authenticated")

        try:
            resp = self.session.get(
                f"{self.BASE_URL}/2/user",
                headers=self.headers,
                timeout=8
            )

            if resp.status_code != 200:
                raise ResyAPIError(f"Failed: {resp.status_code}")

            methods = []
            for pm in resp.json().get("payment_methods", []):
                methods.append({
                    "id": pm.get("id"),
                    "type": pm.get("type"),
                    "display": pm.get("display"),
                    "is_default": pm.get("is_default", False),
                })
            return methods

        except requests.RequestException as e:
            raise ResyAPIError(f"Network error: {e}")

    def get_default_payment_method_id(self):
        """Get default payment method ID"""
        methods = self.get_payment_methods()
        for m in methods:
            if m.get("is_default"):
                return m["id"]
        return methods[0]["id"] if methods else None

    def find_slots(self, venue_id, date, party_size):
        """Find available slots - optimized for speed and memory"""
        params = {
            "lat": 0,
            "long": 0,
            "day": date,
            "party_size": party_size,
            "venue_id": venue_id,
        }

        try:
            resp = self.session.get(
                f"{self.BASE_URL}/4/find",
                headers=self.headers,
                params=params,
                timeout=5  # Short timeout for fast polling
            )

            status = resp.status_code
            if status == 429:
                resp.close()
                raise ResyAPIError("Rate limited (429)")
            elif status != 200:
                body = ""
                try:
                    body = resp.text[:200]
                except Exception:
                    pass
                resp.close()
                raise ResyAPIError(f"Find failed: {status} | {body}")

            result = resp.json()
            resp.close()
            venues = result.get("results", {}).get("venues", [])
            slots = venues[0].get("slots", []) if venues else []
            del result
            return slots

        except requests.RequestException as e:
            raise ResyAPIError(f"Network error: {e}")

    def get_booking_details(self, config_id, date, party_size):
        """Get booking details"""
        params = {
            "config_id": config_id,
            "day": date,
            "party_size": party_size,
        }

        try:
            resp = self.session.get(
                f"{self.BASE_URL}/3/details",
                headers=self.headers,
                params=params,
                timeout=8
            )

            if resp.status_code == 412:
                raise ResyAPIError("Slot no longer available")
            elif resp.status_code != 200:
                raise ResyAPIError(f"Details failed: {resp.status_code}")

            result = resp.json()
            book_token = result.get("book_token", {}).get("value")
            if not book_token:
                raise ResyAPIError("No book_token")

            return {
                "book_token": book_token,
                "payment_required": result.get("payment", {}).get("is_required", False),
            }

        except requests.RequestException as e:
            raise ResyAPIError(f"Network error: {e}")

    def book(self, book_token, payment_method_id=None):
        """Complete booking"""
        data = {
            "book_token": book_token,
            "source_id": "resy.com-venue-details",
        }

        if payment_method_id:
            data["struct_payment_method"] = f'{{"id":{payment_method_id}}}'

        try:
            resp = self.session.post(
                f"{self.BASE_URL}/3/book",
                headers=self.headers,
                data=data,
                timeout=12
            )

            if resp.status_code == 412:
                raise ResyAPIError("Slot taken by someone else")
            elif resp.status_code == 402:
                raise ResyAPIError("Payment required")
            elif resp.status_code == 429:
                raise ResyAPIError("Rate limited")
            elif resp.status_code != 201:
                raise ResyAPIError(f"Booking failed: {resp.status_code}")

            result = resp.json()
            return {
                "resy_token": result.get("resy_token"),
                "reservation_id": result.get("reservation_id"),
            }

        except requests.RequestException as e:
            raise ResyAPIError(f"Network error: {e}")

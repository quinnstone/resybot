"""
Resy API Client

Handles authentication and API communication with Resy's backend.
"""
import requests
from src.config import Config
from src.utils import setup_logger

logger = setup_logger("ResyAPI")


class ResyAPIError(Exception):
    """Custom exception for Resy API errors"""
    pass


class ResyAPI:
    BASE_URL = "https://api.resy.com"
    API_KEY = "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"
    
    def __init__(self):
        self.config = Config
        self.auth_token = None
        self.session = requests.Session()
    
    @property
    def headers(self):
        """Build headers for API requests"""
        h = {
            "Authorization": f'ResyAPI api_key="{self.API_KEY}"',
            "Origin": "https://resy.com",
            "Referer": "https://resy.com/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        if self.auth_token:
            h["X-Resy-Auth-Token"] = self.auth_token
        return h
    
    def login(self):
        """
        Authenticate with Resy and obtain auth token.
        
        Returns:
            str: The authentication token
            
        Raises:
            ResyAPIError: If login fails
        """
        logger.info("Logging in to Resy...")
        url = f"{self.BASE_URL}/3/auth/password"
        
        data = {
            "email": self.config.RESY_EMAIL,
            "password": self.config.RESY_PASSWORD,
        }
        
        try:
            resp = self.session.post(
                url,
                headers=self.headers,
                data=data,
                timeout=10
            )
            
            if resp.status_code in (401, 419):
                raise ResyAPIError("Invalid email or password")
            elif resp.status_code == 429:
                raise ResyAPIError("Rate limited - too many login attempts")
            elif resp.status_code != 200:
                raise ResyAPIError(f"Login failed with status {resp.status_code}: {resp.text}")
            
            result = resp.json()
            self.auth_token = result.get("token")
            
            if not self.auth_token:
                raise ResyAPIError("Login response did not contain token")
            
            logger.info("Login successful!")
            return self.auth_token
            
        except requests.RequestException as e:
            raise ResyAPIError(f"Network error during login: {e}")
    
    def is_authenticated(self):
        """Check if we have a valid auth token"""
        return self.auth_token is not None
    
    def get_payment_methods(self):
        """
        Get saved payment methods from the user's Resy account.
        
        Returns:
            list: List of payment method dictionaries, each containing:
                - id: Payment method ID (needed for booking)
                - type: Card type (visa, mastercard, etc.)
                - display: Last 4 digits
                - is_default: Whether this is the default payment method
                
        Raises:
            ResyAPIError: If not authenticated or request fails
        """
        if not self.is_authenticated():
            raise ResyAPIError("Must be logged in to get payment methods")
        
        logger.info("Fetching payment methods...")
        url = f"{self.BASE_URL}/2/user"
        
        try:
            resp = self.session.get(url, headers=self.headers, timeout=10)
            
            if resp.status_code != 200:
                raise ResyAPIError(f"Failed to get user info: {resp.status_code}")
            
            user = resp.json()
            payment_methods = user.get("payment_methods", [])
            
            # Simplify the payment method objects
            methods = []
            for pm in payment_methods:
                methods.append({
                    "id": pm.get("id"),
                    "type": pm.get("type"),
                    "display": pm.get("display"),
                    "is_default": pm.get("is_default", False),
                })
            
            logger.info(f"Found {len(methods)} payment method(s)")
            return methods
            
        except requests.RequestException as e:
            raise ResyAPIError(f"Network error getting payment methods: {e}")
    
    def get_default_payment_method_id(self):
        """
        Get the ID of the default payment method.
        
        Returns:
            int: The payment method ID, or None if no default found
        """
        methods = self.get_payment_methods()
        for m in methods:
            if m.get("is_default"):
                return m["id"]
        # If no default, return the first one
        if methods:
            return methods[0]["id"]
        return None
    
    def find_slots(self, venue_id: int, date: str, party_size: int):
        """
        Find available reservation slots for a venue.
        
        Args:
            venue_id: The Resy venue ID
            date: Date in YYYY-MM-DD format
            party_size: Number of guests
            
        Returns:
            list: List of available slot dictionaries, each containing:
                - config.token: The config_id needed for booking
                - date.start: The reservation time
                - date.end: End time
                - type: Reservation type (e.g., "Dining Room")
                
        Raises:
            ResyAPIError: If the API request fails
        """
        logger.info(f"Searching for slots: venue={venue_id}, date={date}, party_size={party_size}")
        url = f"{self.BASE_URL}/4/find"
        
        params = {
            "lat": 0,
            "long": 0,
            "day": date,
            "party_size": party_size,
            "venue_id": venue_id,
        }
        
        try:
            resp = self.session.get(
                url,
                headers=self.headers,
                params=params,
                timeout=10
            )
            
            if resp.status_code == 400:
                raise ResyAPIError(f"Invalid request parameters: {resp.text}")
            elif resp.status_code == 404:
                raise ResyAPIError(f"Venue not found: {venue_id}")
            elif resp.status_code != 200:
                raise ResyAPIError(f"Find slots failed with status {resp.status_code}: {resp.text}")
            
            result = resp.json()
            
            # Extract slots from nested response structure
            venues = result.get("results", {}).get("venues", [])
            if not venues:
                logger.info("No availability found")
                return []
            
            slots = venues[0].get("slots", [])
            logger.info(f"Found {len(slots)} available slots")
            return slots
            
        except requests.RequestException as e:
            raise ResyAPIError(f"Network error finding slots: {e}")
    
    def get_booking_details(self, config_id: str, date: str, party_size: int):
        """
        Get booking details including the book_token needed to complete a reservation.
        
        Args:
            config_id: The config token from find_slots (slot['config']['token'])
            date: Date in YYYY-MM-DD format
            party_size: Number of guests
            
        Returns:
            dict: Booking details containing:
                - book_token: Token needed to complete the booking
                - cancellation_policy: Restaurant's cancellation policy
                - payment_required: Whether payment is required upfront
                
        Raises:
            ResyAPIError: If the API request fails or slot is no longer available
        """
        logger.info(f"Getting booking details for config_id: {config_id[:50]}...")
        url = f"{self.BASE_URL}/3/details"
        
        params = {
            "config_id": config_id,
            "day": date,
            "party_size": party_size,
        }
        
        try:
            resp = self.session.get(
                url,
                headers=self.headers,
                params=params,
                timeout=10
            )
            
            if resp.status_code == 412:
                raise ResyAPIError("Slot no longer available")
            elif resp.status_code != 200:
                raise ResyAPIError(f"Get details failed with status {resp.status_code}: {resp.text}")
            
            result = resp.json()
            
            # Extract the book_token
            book_token = result.get("book_token", {}).get("value")
            if not book_token:
                raise ResyAPIError("Response did not contain book_token")
            
            # Extract useful metadata
            cancellation = result.get("cancellation", {})
            payment = result.get("payment", {})
            
            details = {
                "book_token": book_token,
                "cancellation_policy": cancellation.get("display", {}).get("policy", ""),
                "payment_required": payment.get("is_required", False),
                "deposit_amount": payment.get("deposit_amount_min", 0),
            }
            
            logger.info("Got booking details successfully")
            return details
            
        except requests.RequestException as e:
            raise ResyAPIError(f"Network error getting booking details: {e}")
    
    def book(self, book_token: str, payment_method_id: int = None):
        """
        Complete a reservation booking.
        
        ⚠️  WARNING: This will create a REAL reservation on your account!
        
        Args:
            book_token: The token from get_booking_details()
            payment_method_id: Optional payment method ID (required for venues with deposits)
                              If not provided and payment is required, uses default payment method.
            
        Returns:
            dict: Confirmation details containing:
                - resy_token: Unique reservation identifier
                - reservation_id: Reservation ID for cancellation
                - confirmation: Human-readable confirmation
                
        Raises:
            ResyAPIError: If booking fails (slot taken, payment issue, etc.)
        """
        logger.info("🎯 Attempting to book reservation...")
        url = f"{self.BASE_URL}/3/book"
        
        data = {
            "book_token": book_token,
            "source_id": "resy.com-venue-details",
        }
        
        # Add payment method if provided
        if payment_method_id:
            data["struct_payment_method"] = f'{{"id":{payment_method_id}}}'
            logger.info(f"Using payment method ID: {payment_method_id}")
        
        try:
            resp = self.session.post(
                url,
                headers=self.headers,
                data=data,
                timeout=15  # Slightly longer timeout for booking
            )
            
            if resp.status_code == 412:
                raise ResyAPIError("Slot no longer available - someone else booked it")
            elif resp.status_code == 402:
                raise ResyAPIError("Payment required but not provided")
            elif resp.status_code == 429:
                raise ResyAPIError("Rate limited - too many booking attempts")
            elif resp.status_code != 201:
                raise ResyAPIError(f"Booking failed with status {resp.status_code}: {resp.text}")
            
            result = resp.json()
            
            # Extract confirmation details
            resy_token = result.get("resy_token")
            reservation_id = result.get("reservation_id")
            
            if not resy_token:
                raise ResyAPIError("Booking response did not contain resy_token")
            
            confirmation = {
                "resy_token": resy_token,
                "reservation_id": reservation_id,
                "venue": result.get("venue", {}).get("name", "Unknown"),
                "date": result.get("reservation", {}).get("day", ""),
                "time": result.get("reservation", {}).get("time_slot", ""),
                "party_size": result.get("reservation", {}).get("num_seats", 0),
            }
            
            logger.info(f"🎉 BOOKING CONFIRMED! Reservation ID: {reservation_id}")
            return confirmation
            
        except requests.RequestException as e:
            raise ResyAPIError(f"Network error during booking: {e}")

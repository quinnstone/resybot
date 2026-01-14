"""
Venue Resolver

Converts Resy URLs to venue information (ID, drop time, days advance).
"""
import json
import re
import requests
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


@dataclass
class VenueInfo:
    """Venue information needed for scheduling"""
    id: int
    name: str
    slug: str
    city: str
    drop_time: str  # HH:MM format
    days_advance: int
    timezone: str
    slot_interval: int = 30  # minutes between slots


class VenueResolverError(Exception):
    """Error resolving venue information"""
    pass


class VenueResolver:
    """Resolves Resy URLs to venue information"""

    VENUES_FILE = Path(__file__).parent.parent / "data" / "venues.json"

    def __init__(self):
        self.venues_db = self._load_venues()

    def _load_venues(self) -> dict:
        """Load known venues from JSON file"""
        if self.VENUES_FILE.exists():
            return json.loads(self.VENUES_FILE.read_text())
        return {}

    def _save_venues(self):
        """Save venues database back to file"""
        self.VENUES_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.VENUES_FILE.write_text(json.dumps(self.venues_db, indent=2))

    def parse_url(self, url: str) -> str:
        """
        Extract venue slug from Resy URL.

        Supports formats:
        - https://resy.com/cities/new-york-ny/venues/carbone
        - https://resy.com/cities/new-york-ny/carbone
        - resy.com/cities/new-york-ny/venues/carbone
        """
        # Normalize URL
        if not url.startswith('http'):
            url = 'https://' + url

        parsed = urlparse(url)
        path = parsed.path.strip('/')

        # Pattern: cities/{city}/venues/{slug} or cities/{city}/{slug}
        match = re.search(r'cities/[^/]+/(?:venues/)?([^/?]+)', path)
        if match:
            return match.group(1).lower()

        raise VenueResolverError(f"Could not parse venue slug from URL: {url}")

    def resolve(self, url: str, interactive: bool = True, require_schedule_info: bool = True) -> VenueInfo:
        """
        Resolve a Resy URL to full venue information.

        Args:
            url: Resy venue URL
            interactive: If True, prompt user for missing info
            require_schedule_info: If False, skip drop_time/days_advance prompts (for immediate testing)

        Returns:
            VenueInfo with all details needed for scheduling
        """
        slug = self.parse_url(url)

        # Check local database first
        if slug in self.venues_db:
            venue_data = self.venues_db[slug]
            return VenueInfo(
                id=venue_data['id'],
                name=venue_data['name'],
                slug=slug,
                city=venue_data.get('city', 'Unknown'),
                drop_time=venue_data['drop_time'],
                days_advance=venue_data['days_advance'],
                timezone=venue_data.get('timezone', 'America/New_York'),
                slot_interval=venue_data.get('slot_interval', 30)
            )

        # Not in database - try to fetch venue ID from Resy
        print(f"\nVenue '{slug}' not in database. Fetching from Resy...")
        venue_id, venue_name = self._fetch_venue_from_resy(url, slug)

        # For immediate testing, we don't need scheduling info
        if not require_schedule_info:
            return VenueInfo(
                id=venue_id,
                name=venue_name,
                slug=slug,
                city='Unknown',
                drop_time='00:00',  # Placeholder
                days_advance=30,     # Placeholder
                timezone='America/New_York',
                slot_interval=30
            )

        if not interactive:
            raise VenueResolverError(
                f"Venue '{slug}' not in database and interactive mode disabled"
            )

        # Prompt user for drop time and days advance
        print(f"\nFound: {venue_name} (ID: {venue_id})")
        print("I need some additional information about this restaurant's booking policy.\n")

        drop_time = self._prompt_drop_time(venue_name)
        days_advance = self._prompt_days_advance(venue_name)
        timezone = self._prompt_timezone()

        # Save to database for future use
        self.venues_db[slug] = {
            'id': venue_id,
            'name': venue_name,
            'city': 'Unknown',
            'drop_time': drop_time,
            'days_advance': days_advance,
            'timezone': timezone,
            'slot_interval': 30
        }
        self._save_venues()
        print(f"\nSaved {venue_name} to venue database for future use.")

        return VenueInfo(
            id=venue_id,
            name=venue_name,
            slug=slug,
            city='Unknown',
            drop_time=drop_time,
            days_advance=days_advance,
            timezone=timezone,
            slot_interval=30
        )

    def _fetch_venue_from_resy(self, url: str, slug: str) -> tuple[int, str]:
        """
        Fetch venue ID and name from Resy by scraping the venue page.

        Returns (venue_id, venue_name)
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }

        venue_id = None
        venue_name = slug.replace('-', ' ').title()

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()

            # Try multiple patterns to find venue ID
            patterns = [
                r'"venue_id"\s*:\s*(\d+)',
                r'"id"\s*:\s*(\d+)\s*,\s*"name"',
                r'venue[_-]?id[=:]\s*["\']?(\d+)',
                r'/venue/(\d+)',
                r'data-venue-id=["\'](\d+)',
                r'"objectID"\s*:\s*"(\d+)"',
                r'"resy_venue_id"\s*:\s*(\d+)',
            ]

            for pattern in patterns:
                match = re.search(pattern, resp.text, re.I)
                if match:
                    venue_id = int(match.group(1))
                    break

            # Try to extract venue name
            name_patterns = [
                r'"name"\s*:\s*"([^"]{2,50})"',
                r'<title>([^<|]+)',
                r'"venue_name"\s*:\s*"([^"]+)"',
            ]
            for pattern in name_patterns:
                match = re.search(pattern, resp.text)
                if match:
                    name = match.group(1).strip()
                    if name and len(name) > 1 and 'resy' not in name.lower():
                        venue_name = name
                        break

        except requests.RequestException as e:
            print(f"Warning: Could not fetch venue page: {e}")

        # If scraping failed, try the Resy search API
        if not venue_id:
            venue_id, venue_name = self._search_venue_api(slug, venue_name)

        # If we still couldn't find the venue ID, ask the user
        if not venue_id:
            print(f"\nCouldn't automatically find venue ID for '{slug}'.")
            print("You can find it manually:")
            print("  1. Open the restaurant page on resy.com")
            print("  2. Open DevTools (F12) -> Network tab")
            print("  3. Refresh the page and filter by 'find' or 'venue'")
            print("  4. Look for venue_id in the request URLs or responses")
            print()

            while True:
                id_input = input("Enter venue ID (or 'skip' to cancel): ").strip()
                if id_input.lower() == 'skip':
                    raise VenueResolverError("Venue ID not provided")
                try:
                    venue_id = int(id_input)
                    break
                except ValueError:
                    print("Please enter a valid number")

            # Ask for venue name too
            name_input = input(f"Enter venue name [{venue_name}]: ").strip()
            if name_input:
                venue_name = name_input

        return venue_id, venue_name

    def _search_venue_api(self, slug: str, default_name: str) -> tuple[Optional[int], str]:
        """
        Search for venue using Resy's search API.

        Returns (venue_id, venue_name) or (None, default_name) if not found.
        """
        search_term = slug.replace('-', ' ')

        headers = {
            'Authorization': 'ResyAPI api_key="VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"',
            'User-Agent': 'Mozilla/5.0',
            'Origin': 'https://resy.com',
            'Referer': 'https://resy.com/',
            'Content-Type': 'application/json',
        }

        try:
            resp = requests.post(
                'https://api.resy.com/3/venuesearch/search',
                headers=headers,
                json={'query': search_term},
                timeout=10
            )

            if resp.status_code == 200:
                data = resp.json()
                hits = data.get('search', {}).get('hits', [])

                # Find matching venue by slug
                for hit in hits:
                    if hit.get('url_slug') == slug:
                        venue_id = hit.get('id', {}).get('resy')
                        venue_name = hit.get('name', default_name)
                        if venue_id:
                            print(f"  Found via API: {venue_name} (ID: {venue_id})")
                            return venue_id, venue_name

                # If no exact match, return first result if it looks right
                if hits:
                    first = hits[0]
                    venue_id = first.get('id', {}).get('resy')
                    venue_name = first.get('name', default_name)
                    if venue_id:
                        print(f"  Found via API (best match): {venue_name} (ID: {venue_id})")
                        return venue_id, venue_name

        except Exception as e:
            print(f"  API search failed: {e}")

        return None, default_name

    def _prompt_drop_time(self, venue_name: str) -> str:
        """Prompt user for reservation drop time"""
        print(f"What time does {venue_name} release new reservations?")
        print("(Check their website or Resy page for this info)")
        print("Examples: 09:00, 10:00, 12:00, 00:00 (midnight)")

        while True:
            time_input = input("\nDrop time (HH:MM): ").strip()
            if re.match(r'^([01]?\d|2[0-3]):([0-5]\d)$', time_input):
                # Normalize to HH:MM
                parts = time_input.split(':')
                return f"{int(parts[0]):02d}:{parts[1]}"
            print("Invalid format. Please enter time as HH:MM (e.g., 09:00)")

    def _prompt_days_advance(self, venue_name: str) -> int:
        """Prompt user for days in advance"""
        print(f"\nHow many days in advance does {venue_name} release reservations?")
        print("(This is usually 14, 21, 28, 29, or 30 days)")

        while True:
            try:
                days = int(input("\nDays in advance: ").strip())
                if 1 <= days <= 90:
                    return days
                print("Please enter a number between 1 and 90")
            except ValueError:
                print("Please enter a valid number")

    def _prompt_timezone(self) -> str:
        """Prompt user for timezone"""
        print("\nWhat timezone is the restaurant in?")
        print("1. America/New_York (Eastern)")
        print("2. America/Chicago (Central)")
        print("3. America/Denver (Mountain)")
        print("4. America/Los_Angeles (Pacific)")

        timezones = {
            '1': 'America/New_York',
            '2': 'America/Chicago',
            '3': 'America/Denver',
            '4': 'America/Los_Angeles'
        }

        while True:
            choice = input("\nSelect timezone (1-4) [1]: ").strip() or '1'
            if choice in timezones:
                return timezones[choice]
            print("Please enter 1, 2, 3, or 4")

    def get_venue_by_id(self, venue_id: int) -> Optional[VenueInfo]:
        """Look up venue by ID (for job loading)"""
        for slug, data in self.venues_db.items():
            if data['id'] == venue_id:
                return VenueInfo(
                    id=data['id'],
                    name=data['name'],
                    slug=slug,
                    city=data.get('city', 'Unknown'),
                    drop_time=data['drop_time'],
                    days_advance=data['days_advance'],
                    timezone=data.get('timezone', 'America/New_York'),
                    slot_interval=data.get('slot_interval', 30)
                )
        return None


def generate_priority_times(start_time: str, end_time: str, interval: int = 30) -> list[str]:
    """
    Generate list of times from start to end at given interval.

    Args:
        start_time: Start time in HH:MM format
        end_time: End time in HH:MM format
        interval: Minutes between slots (default 30)

    Returns:
        List of times in HH:MM format, earliest first

    Example:
        generate_priority_times("19:00", "21:00", 30)
        -> ["19:00", "19:30", "20:00", "20:30", "21:00"]
    """
    def time_to_minutes(t: str) -> int:
        h, m = map(int, t.split(':'))
        return h * 60 + m

    def minutes_to_time(mins: int) -> str:
        return f"{mins // 60:02d}:{mins % 60:02d}"

    start_mins = time_to_minutes(start_time)
    end_mins = time_to_minutes(end_time)

    times = []
    current = start_mins
    while current <= end_mins:
        times.append(minutes_to_time(current))
        current += interval

    return times


if __name__ == "__main__":
    # Test the resolver
    resolver = VenueResolver()

    # Test URL parsing
    test_urls = [
        "https://resy.com/cities/new-york-ny/venues/carbone",
        "https://resy.com/cities/new-york-ny/carbone",
        "resy.com/cities/brooklyn-ny/venues/the-four-horsemen",
    ]

    for url in test_urls:
        try:
            slug = resolver.parse_url(url)
            print(f"{url} -> {slug}")
        except VenueResolverError as e:
            print(f"{url} -> ERROR: {e}")

    # Test priority time generation
    print("\nPriority times 19:00-21:00:")
    print(generate_priority_times("19:00", "21:00"))

"""
API Authentication Tests

Tests for ResyAPI login functionality.
Run with: pytest tests/test_api_auth.py -v -s
"""
import pytest
from src.api import ResyAPI, ResyAPIError


class TestResyAPIHeaders:
    """Unit tests for header construction"""
    
    def test_headers_contain_api_key(self):
        api = ResyAPI()
        headers = api.headers
        
        assert "Authorization" in headers
        assert "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5" in headers["Authorization"]
    
    def test_headers_have_required_fields(self):
        api = ResyAPI()
        headers = api.headers
        
        assert "Origin" in headers
        assert "Referer" in headers
        assert "User-Agent" in headers
        assert headers["Origin"] == "https://resy.com"
    
    def test_headers_include_auth_token_when_set(self):
        api = ResyAPI()
        api.auth_token = "test_token_123"
        headers = api.headers
        
        assert "X-Resy-Auth-Token" in headers
        assert headers["X-Resy-Auth-Token"] == "test_token_123"
    
    def test_headers_exclude_auth_token_when_not_set(self):
        api = ResyAPI()
        headers = api.headers
        
        assert "X-Resy-Auth-Token" not in headers


class TestResyAPIAuthentication:
    """Integration tests for login - requires real credentials"""
    
    @pytest.fixture
    def api(self):
        return ResyAPI()
    
    def test_is_authenticated_false_initially(self, api):
        assert api.is_authenticated() is False
    
    def test_is_authenticated_true_after_login(self, api):
        if not api.config.RESY_EMAIL or not api.config.RESY_PASSWORD:
            pytest.skip("No credentials configured in .env")
        
        api.login()
        assert api.is_authenticated() is True
    
    @pytest.mark.integration
    def test_login_returns_token(self, api):
        """Integration test - requires real credentials in .env"""
        if not api.config.RESY_EMAIL or not api.config.RESY_PASSWORD:
            pytest.skip("No credentials configured in .env")
        
        token = api.login()
        
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 20
        print(f"Got auth token: {token[:20]}...")
    
    def test_login_with_bad_credentials_raises(self, api, monkeypatch):
        """Test that bad credentials raise ResyAPIError"""
        monkeypatch.setattr(api.config, 'RESY_EMAIL', 'bad@email.com')
        monkeypatch.setattr(api.config, 'RESY_PASSWORD', 'wrongpassword')
        
        with pytest.raises(ResyAPIError) as exc_info:
            api.login()
        
        assert "Invalid email or password" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

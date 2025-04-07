import requests

# Custom exceptions for API error handling
class AuthenticationError(Exception):
    """Raised for 401 errors, indicating invalid credentials."""
    pass

class RateLimitError(Exception):
    """Raised for 429 errors, indicating API limit exceeded."""
    pass

class APIError(Exception):
    """Raised for 5xx server errors or other API-related issues."""
    pass

def handle_errors(response):
    """
    Checks the HTTP response status and raises custom exceptions for specific error codes.

    Args:
        response: The requests.Response object.

    Raises:
        AuthenticationError: If status code is 401.
        RateLimitError: If status code is 429.
        APIError: If status code is 5xx.
        requests.HTTPError: For other HTTP errors (4xx, etc.).
    """
    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        if e.response.status_code == 401:
            raise AuthenticationError("Invalid credentials") from e
        elif e.response.status_code == 429:
            raise RateLimitError("API limit exceeded") from e
        elif 500 <= e.response.status_code < 600:
            raise APIError(f"Server error ({e.response.status_code})") from e
        raise # Re-raise other HTTP errors
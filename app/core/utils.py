import secrets
import string

def generate_invite_code(length: int = 8) -> str:
    """Generate an uppercase alphanumeric invite code."""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

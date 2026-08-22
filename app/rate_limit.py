from slowapi import Limiter

from app.services.web_security import public_rate_limit_key


limiter = Limiter(key_func=public_rate_limit_key)

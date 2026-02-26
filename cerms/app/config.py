"""
CERMS - City Emergency Response Management System
Configuration module.
"""

import os

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cerms.db")

# JWT Auth
SECRET_KEY = os.getenv("SECRET_KEY", "cerms-super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# H3 Resolution (resolution 7 ≈ 5.16 km² hexagons — good for city zones)
H3_RESOLUTION = 7

# Event queue settings
EVENT_QUEUE_MAX_SIZE = 1000

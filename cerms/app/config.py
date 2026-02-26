import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cerms.db")

SECRET_KEY = os.getenv("SECRET_KEY", "cerms-super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

H3_RESOLUTION = 7

EVENT_QUEUE_MAX_SIZE = 1000

"""
FastAPI application setup for the lit-critic REST API server.
"""

from dotenv import load_dotenv
from fastapi import FastAPI

from . import __version__ as WEB_VERSION
from .routes import router

# Load .env file (if present) so ANTHROPIC_API_KEY is available via os.environ
load_dotenv()


# App
app = FastAPI(
    title="lit-critic",
    description="Multi-lens editorial review system for fiction manuscripts",
    version=WEB_VERSION,
)

# Include API routes
app.include_router(router)

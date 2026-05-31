"""Test configuration and shared fixtures."""
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set test environment
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("LOG_LEVEL", "WARNING")

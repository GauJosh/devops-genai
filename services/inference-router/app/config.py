import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL_DEFAULT = os.getenv("OPENAI_MODEL_DEFAULT", "gpt-4o-mini")

# Optional: a simple “routing policy” switch
ROUTER_DEFAULT_PROVIDER = os.getenv("ROUTER_DEFAULT_PROVIDER", "openai")
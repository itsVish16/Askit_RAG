import os 
from dotenv import load_dotenv

load_dotenv()

class Config:
    FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY")
    FIREWORKS_BASE_URL = os.getenv("FIREWORKS_BASE_URL")
    FIREWORKS_MODEL_NAME = os.getenv("FIREWORKS_MODEL_NAME")
    FIREWORKS_MODEL_NAME_EMBED = os.getenv("FIREWORKS_MODEL_NAME_EMBED")
    OPIK_PROJECT_NAME = os.getenv("OPIK_PROJECT_NAME")
    OPIK_API_KEY = os.getenv("OPIK_API_KEY")
    OPIK_WORKSPACE = os.getenv("OPIK_WORKSPACE")
    QDRANT_API_KEY=os.getenv("QDRANT_API_KEY")
    QDRANT_URL=os.getenv("QDRANT_URL")
    
    
settings = Config()

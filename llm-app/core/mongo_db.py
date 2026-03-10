
import os
import logging
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class MongoDatabaseManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MongoDatabaseManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.uri = os.getenv("MONGO_URI")
        if not self.uri:
            logger.error("MONGO_URI not found in environment variables")
            raise ValueError("MONGO_URI not set")
            
        try:
            self.client = MongoClient(self.uri)
            # Verify connection
            self.client.admin.command('ping')
            self.db = self.client.get_database("test")
            
            logger.info("Successfully connected to MongoDB")
            self._initialized = True
        except ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    def get_database(self):
        return self.db

    def close(self):
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")

# Global instance
mongo_db_manager = MongoDatabaseManager()

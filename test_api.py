import os
import pymongo
import certifi
from dotenv import load_dotenv

load_dotenv()
uri = os.getenv("MONGODB_URI")
print(f"Connecting to: {uri}")

try:
    client = pymongo.MongoClient(uri, tlsCAFile=certifi.where())
    client.admin.command('ping')
    print("Ping successful!")
except Exception as e:
    print(f"Error: {e}")

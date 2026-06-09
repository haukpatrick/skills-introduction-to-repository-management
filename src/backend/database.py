"""
MongoDB database configuration and setup for Mergington High School API
"""

import os

from pymongo import MongoClient
from pymongo.errors import PyMongoError
from argon2 import PasswordHasher, exceptions as argon2_exceptions

MONGO_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/")
MONGO_TIMEOUT_MS = int(os.environ.get("MONGO_TIMEOUT_MS", "2000"))

activities_collection = None
teachers_collection = None
use_in_memory_db = False


def _create_mongo_client():
    return MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=MONGO_TIMEOUT_MS,
        connectTimeoutMS=MONGO_TIMEOUT_MS,
        socketTimeoutMS=MONGO_TIMEOUT_MS
    )


class InMemoryCollection:
    def __init__(self, documents=None):
        self._documents = []
        if documents:
            for document in documents:
                self.insert_one(document.copy())

    def _match_value(self, value, condition):
        if isinstance(condition, dict):
            if "$in" in condition:
                return value in condition["$in"]
            if "$gte" in condition:
                return value >= condition["$gte"]
            if "$lte" in condition:
                return value <= condition["$lte"]
            return False
        return value == condition

    def _get_nested(self, document, field_path):
        current = document
        for part in field_path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    def _matches(self, document, query):
        for key, condition in query.items():
            value = self._get_nested(document, key)
            if not self._match_value(value, condition):
                return False
        return True

    def count_documents(self, query):
        return sum(1 for document in self._documents if self._matches(document, query))

    def find(self, query):
        for document in self._documents:
            if self._matches(document, query):
                yield document.copy()

    def find_one(self, query):
        for document in self._documents:
            if self._matches(document, query):
                return document.copy()
        return None

    def insert_one(self, document):
        self._documents.append(document.copy())
        return type("Result", (), {"inserted_id": document.get("_id")})

    def update_one(self, filter_query, update_query):
        modified_count = 0
        for document in self._documents:
            if self._matches(document, filter_query):
                if "$push" in update_query:
                    for field, value in update_query["$push"].items():
                        target = self._get_nested(document, field.rsplit(".", 1)[0]) if "." in field else document
                        key = field.rsplit(".", 1)[-1]
                        if target is not None:
                            target.setdefault(key, []).append(value)
                            modified_count = 1
                if "$pull" in update_query:
                    for field, value in update_query["$pull"].items():
                        target = self._get_nested(document, field.rsplit(".", 1)[0]) if "." in field else document
                        key = field.rsplit(".", 1)[-1]
                        if target is not None and isinstance(target.get(key), list):
                            before = len(target[key])
                            target[key] = [item for item in target[key] if item != value]
                            if len(target[key]) != before:
                                modified_count = 1
                break
        return type("Result", (), {"modified_count": modified_count})

    def aggregate(self, pipeline):
        documents = [document.copy() for document in self._documents]
        for stage in pipeline:
            if "$unwind" in stage:
                unwind_field = stage["$unwind"].lstrip("$")
                unwound = []
                for document in documents:
                    values = self._get_nested(document, unwind_field)
                    if isinstance(values, list):
                        for value in values:
                            new_document = document.copy()
                            target = new_document
                            parts = unwind_field.split(".")
                            for part in parts[:-1]:
                                target = target.setdefault(part, {})
                            target[parts[-1]] = value
                            unwound.append(new_document)
                documents = unwound
            elif "$group" in stage:
                group_id = stage["$group"]["_id"].lstrip("$")
                grouped = {}
                for document in documents:
                    key = self._get_nested(document, group_id)
                    grouped[key] = {"_id": key}
                documents = list(grouped.values())
            elif "$sort" in stage:
                sort_field, direction = next(iter(stage["$sort"].items()))
                documents.sort(key=lambda item: item.get(sort_field), reverse=direction < 0)
        return documents


def _initialize_collections():
    global activities_collection, teachers_collection, use_in_memory_db

    try:
        client = _create_mongo_client()
        client.admin.command("ping")
        db = client["mergington_high"]
        activities_collection = db["activities"]
        teachers_collection = db["teachers"]
        use_in_memory_db = False
    except PyMongoError:
        activities_collection = InMemoryCollection()
        teachers_collection = InMemoryCollection()
        use_in_memory_db = True


# Methods
def hash_password(password):
    """Hash password using Argon2"""
    ph = PasswordHasher()
    return ph.hash(password)


def verify_password(hashed_password: str, plain_password: str) -> bool:
    """Verify a plain password against an Argon2 hashed password.

    Returns True when the password matches, False otherwise.
    """
    ph = PasswordHasher()
    try:
        ph.verify(hashed_password, plain_password)
        return True
    except argon2_exceptions.VerifyMismatchError:
        return False
    except Exception:
        # For any other exception (e.g., invalid hash), treat as non-match
        return False

def init_database():
    """Initialize database if empty"""

    # Initialize activities if empty
    if activities_collection.count_documents({}) == 0:
        for name, details in initial_activities.items():
            activities_collection.insert_one({"_id": name, **details})
            
    # Initialize teacher accounts if empty
    if teachers_collection.count_documents({}) == 0:
        for teacher in initial_teachers:
            teachers_collection.insert_one({"_id": teacher["username"], **teacher})

# Initial database if empty
initial_activities = {
    "Chess Club": {
        "description": "Learn strategies and compete in chess tournaments",
        "schedule": "Mondays and Fridays, 3:15 PM - 4:45 PM",
        "schedule_details": {
            "days": ["Monday", "Friday"],
            "start_time": "15:15",
            "end_time": "16:45"
        },
        "max_participants": 12,
        "participants": ["michael@mergington.edu", "daniel@mergington.edu"]
    },
    "Programming Class": {
        "description": "Learn programming fundamentals and build software projects",
        "schedule": "Tuesdays and Thursdays, 7:00 AM - 8:00 AM",
        "schedule_details": {
            "days": ["Tuesday", "Thursday"],
            "start_time": "07:00",
            "end_time": "08:00"
        },
        "max_participants": 20,
        "participants": ["emma@mergington.edu", "sophia@mergington.edu"]
    },
    "Morning Fitness": {
        "description": "Early morning physical training and exercises",
        "schedule": "Mondays, Wednesdays, Fridays, 6:30 AM - 7:45 AM",
        "schedule_details": {
            "days": ["Monday", "Wednesday", "Friday"],
            "start_time": "06:30",
            "end_time": "07:45"
        },
        "max_participants": 30,
        "participants": ["john@mergington.edu", "olivia@mergington.edu"]
    },
    "Soccer Team": {
        "description": "Join the school soccer team and compete in matches",
        "schedule": "Tuesdays and Thursdays, 3:30 PM - 5:30 PM",
        "schedule_details": {
            "days": ["Tuesday", "Thursday"],
            "start_time": "15:30",
            "end_time": "17:30"
        },
        "max_participants": 22,
        "participants": ["liam@mergington.edu", "noah@mergington.edu"]
    },
    "Basketball Team": {
        "description": "Practice and compete in basketball tournaments",
        "schedule": "Wednesdays and Fridays, 3:15 PM - 5:00 PM",
        "schedule_details": {
            "days": ["Wednesday", "Friday"],
            "start_time": "15:15",
            "end_time": "17:00"
        },
        "max_participants": 15,
        "participants": ["ava@mergington.edu", "mia@mergington.edu"]
    },
    "Art Club": {
        "description": "Explore various art techniques and create masterpieces",
        "schedule": "Thursdays, 3:15 PM - 5:00 PM",
        "schedule_details": {
            "days": ["Thursday"],
            "start_time": "15:15",
            "end_time": "17:00"
        },
        "max_participants": 15,
        "participants": ["amelia@mergington.edu", "harper@mergington.edu"]
    },
    "Drama Club": {
        "description": "Act, direct, and produce plays and performances",
        "schedule": "Mondays and Wednesdays, 3:30 PM - 5:30 PM",
        "schedule_details": {
            "days": ["Monday", "Wednesday"],
            "start_time": "15:30",
            "end_time": "17:30"
        },
        "max_participants": 20,
        "participants": ["ella@mergington.edu", "scarlett@mergington.edu"]
    },
    "Math Club": {
        "description": "Solve challenging problems and prepare for math competitions",
        "schedule": "Tuesdays, 7:15 AM - 8:00 AM",
        "schedule_details": {
            "days": ["Tuesday"],
            "start_time": "07:15",
            "end_time": "08:00"
        },
        "max_participants": 10,
        "participants": ["james@mergington.edu", "benjamin@mergington.edu"]
    },
    "Debate Team": {
        "description": "Develop public speaking and argumentation skills",
        "schedule": "Fridays, 3:30 PM - 5:30 PM",
        "schedule_details": {
            "days": ["Friday"],
            "start_time": "15:30",
            "end_time": "17:30"
        },
        "max_participants": 12,
        "participants": ["charlotte@mergington.edu", "amelia@mergington.edu"]
    },
    "Weekend Robotics Workshop": {
        "description": "Build and program robots in our state-of-the-art workshop",
        "schedule": "Saturdays, 10:00 AM - 2:00 PM",
        "schedule_details": {
            "days": ["Saturday"],
            "start_time": "10:00",
            "end_time": "14:00"
        },
        "max_participants": 15,
        "participants": ["ethan@mergington.edu", "oliver@mergington.edu"]
    },
    "Science Olympiad": {
        "description": "Weekend science competition preparation for regional and state events",
        "schedule": "Saturdays, 1:00 PM - 4:00 PM",
        "schedule_details": {
            "days": ["Saturday"],
            "start_time": "13:00",
            "end_time": "16:00"
        },
        "max_participants": 18,
        "participants": ["isabella@mergington.edu", "lucas@mergington.edu"]
    },
    "Sunday Chess Tournament": {
        "description": "Weekly tournament for serious chess players with rankings",
        "schedule": "Sundays, 2:00 PM - 5:00 PM",
        "schedule_details": {
            "days": ["Sunday"],
            "start_time": "14:00",
            "end_time": "17:00"
        },
        "max_participants": 16,
        "participants": ["william@mergington.edu", "jacob@mergington.edu"]
    }
}

initial_teachers = [
    {
        "username": "mrodriguez",
        "display_name": "Ms. Rodriguez",
        "password": hash_password("art123"),
        "role": "teacher"
     },
    {
        "username": "mchen",
        "display_name": "Mr. Chen",
        "password": hash_password("chess456"),
        "role": "teacher"
    },
    {
        "username": "principal",
        "display_name": "Principal Martinez",
        "password": hash_password("admin789"),
        "role": "admin"
    }
]

# Initialize collections after sample data is defined.
_initialize_collections()


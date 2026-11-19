from datetime import datetime
from typing import Any

from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError


class MongoCounterStore:
    def __init__(self, client: MongoClient[dict[str, Any]], database_name: str):
        self.database = client[database_name]
        self.collection = self.database["rate_limit_counters"]
        if not self.collection.write_concern.acknowledged:
            raise ValueError("MONGODB_URI must use acknowledged writes.")
        self._index_ready = False

    def ensure_index(self) -> None:
        if not self._index_ready:
            # Creating the same index is safe if requests race during recovery.
            self.collection.create_index("expiresAt", expireAfterSeconds=0)
            self._index_ready = True

    def check_ready(self) -> None:
        self.ensure_index()
        self.database.command("ping")

    def increment(self, key: str, expires_at: datetime) -> int:
        self.ensure_index()
        selector = {"_id": key}
        increment = {"count": 1}
        try:
            counter = self.collection.find_one_and_update(
                selector,
                {"$inc": increment, "$setOnInsert": {"expiresAt": expires_at}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            # A competing upsert can insert this _id before ours does. Only
            # retry when MongoDB explicitly confirms that our insert failed.
            if (exc.details or {}).get("keyPattern") != {"_id": 1}:
                raise
            counter = self.collection.find_one_and_update(
                selector, {"$inc": increment}, return_document=ReturnDocument.AFTER
            )

        if counter is None:
            raise PyMongoError("The counter was unavailable after the update.")
        return counter["count"]

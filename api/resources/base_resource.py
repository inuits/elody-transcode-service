import os

from flask import request
from flask_restful import Resource, abort
from werkzeug.exceptions import BadRequest


class BaseResource(Resource):
    def __init__(self):
        self.collection_api_url = os.getenv(
            "COLLECTION_API_URL", "http://localhost:8000"
        )
        self.storage_api_url = os.getenv("STORAGE_API_URL", "http://localhost:8001")
        self.upload_source = os.getenv("UPLOAD_SOURCE", "/mnt/media-import")

    def _get_request_body(self):
        try:
            request_body = request.get_json()
            invalid_input = request_body is None
        except BadRequest:
            invalid_input = True
        if invalid_input:
            abort(
                405,
                message="Invalid input",
            )
        return request_body

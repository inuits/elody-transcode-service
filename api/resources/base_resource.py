from flask import request
from flask_restful import abort, Resource


class BaseResource(Resource):
    def _check_valid_content(self, content, mimetypes):
        if any(x not in content for x in ["mediafile", ",mimetype", "url"]):
            abort(405, message="Malformed request body")
        if not any(x in content["mimetype"] for x in mimetypes):
            abort(405, message="Mimetype not allowed")

    def _get_request_body(self):
        if request_body := request.get_json(silent=True):
            return request_body
        abort(405, message="Invalid input")

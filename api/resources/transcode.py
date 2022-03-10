import app

from flask import request
from flask_restful import abort, Resource
from transcoder import Transcoder
from werkzeug.exceptions import BadRequest


def _get_request_body():
    try:
        request_body = request.get_json()
        invalid_input = request_body is None
    except BadRequest:
        invalid_input = True
    if invalid_input:
        abort(405, message="Invalid input")
    return request_body


def _check_valid_content(content):
    accepted_mimetypes = [
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/tiff",
    ]
    if "mediafile" not in content or "mimetype" not in content or "url" not in content:
        abort(405, message="Invalid input")
    if content["mimetype"] not in accepted_mimetypes:
        abort(405, message="Not an accepted mimetype")


class Transcode(Resource):
    @app.require_oauth()
    def post(self):
        content = _get_request_body()
        try:
            transcoder = Transcoder(content["mediafile"], content["url"])
            transcoder.transcode_to_jpeg()
        except Exception as ex:
            return str(ex), 400
        return "Transcode successful", 201

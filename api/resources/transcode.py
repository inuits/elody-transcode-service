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


def _check_valid_content(content, mimetypes):
    if "mediafile" not in content or "mimetype" not in content or "url" not in content:
        abort(405, message="Malformed request body")
    if content["mimetype"] not in mimetypes:
        abort(405, message="Mimetype not allowed")


class JpegTranscode(Resource):
    @app.require_oauth("transcode-to-jpeg")
    def post(self):
        content = _get_request_body()
        _check_valid_content(content, app.allowed_image_mimetypes)
        try:
            transcoder = Transcoder(content["mediafile"], content["url"])
            transcoder.transcode_to_jpeg()
        except Exception as ex:
            return str(ex), 400
        return f'Successfully transcoded {content["filename"]} to jpeg', 201


class WidthHeightTranscode(Resource):
    @app.require_oauth("transcode-add-width-height")
    def post(self):
        content = _get_request_body()
        _check_valid_content(content, app.allowed_mimetypes)
        try:
            transcoder = Transcoder(content["mediafile"], content["url"])
            if content["mimetype"] in app.allowed_image_mimetypes:
                transcoder.add_image_width_height()
            else:
                transcoder.add_video_width_height()
        except Exception as ex:
            return str(ex), 400
        return f'Successfully added {content["filename"]} width & height', 201

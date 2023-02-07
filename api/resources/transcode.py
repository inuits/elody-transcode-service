import app

from flask import request
from flask_restful import abort, Resource
from transcoder import Transcoder


def _is_malformed_message(data, fields, mimetypes):
    if not all(x in data for x in fields):
        abort(405, message="Malformed request body")
    if not any(x in data["mediafile"]["mimetype"] for x in mimetypes):
        abort(405, message="Mimetype not allowed")


def _get_request_body():
    if request_body := request.get_json(silent=True):
        return request_body
    abort(405, message="Invalid input")


class JpegTranscode(Resource):
    @app.require_oauth("transcode-to-jpeg")
    def post(self):
        content = _get_request_body()
        _is_malformed_message(content, ["image/"])
        try:
            transcoder = Transcoder(content["mediafile"], content["url"])
            transcoder.transcode("jpg")
        except Exception as ex:
            return str(ex), 400
        return (
            f'Successfully transcoded {content["mediafile"]["filename"]} to jpeg',
            201,
        )


class MP3Transcode(Resource):
    @app.require_oauth("transcode-to-mp3")
    def post(self):
        content = _get_request_body()
        _is_malformed_message(content, ["audio/"])
        if content["mimetype"] == "audio/mpeg":
            abort(400, message=f'{content["mediafile"]["filename"]} is already an mp3')
        try:
            transcoder = Transcoder(content["mediafile"], content["url"])
            transcoder.transcode("mp3")
        except Exception as ex:
            return str(ex), 400
        return (
            f'Successfully transcoded {content["mediafile"]["filename"]} to mp3',
            201,
        )


class MP4Transcode(Resource):
    @app.require_oauth("transcode-to-mp4")
    def post(self):
        content = _get_request_body()
        _is_malformed_message(content, ["video/"])
        try:
            transcoder = Transcoder(content["mediafile"], content["url"])
            transcoder.transcode("mp4")
        except Exception as ex:
            return str(ex), 400
        return (
            f'Successfully transcoded {content["mediafile"]["filename"]} to mp4',
            201,
        )


class WidthHeightTranscode(Resource):
    @app.require_oauth("transcode-add-width-height")
    def post(self):
        content = _get_request_body()
        _is_malformed_message(content, ["image/", "video/"])
        try:
            transcoder = Transcoder(content["mediafile"], content["url"])
            transcoder.transcode("width_height")
        except Exception as ex:
            return str(ex), 400
        return (
            f'Successfully added {content["mediafile"]["filename"]} width & height',
            201,
        )

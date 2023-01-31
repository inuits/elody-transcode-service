import app

from flask import request
from flask_restful import abort, Resource
from transcoder import Transcoder


def _check_valid_content(content, mimetypes):
    if any(x not in content for x in ["mediafile", "mimetype", "url"]):
        abort(405, message="Malformed request body")
    if not any(x in content["mimetype"] for x in mimetypes):
        abort(405, message="Mimetype not allowed")


def _get_request_body():
    if request_body := request.get_json(silent=True):
        return request_body
    abort(405, message="Invalid input")


class JpegTranscode(Resource):
    @app.require_oauth("transcode-to-jpeg")
    def post(self):
        content = _get_request_body()
        _check_valid_content(content, ["image/"])
        try:
            transcoder = Transcoder(content["mediafile"], content["url"])
            transcoder.transcode_to_jpeg()
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
        _check_valid_content(content, ["audio/"])
        if content["mimetype"] == "audio/mpeg":
            abort(400, message=f'{content["mediafile"]["filename"]} is already an mp3')
        try:
            transcoder = Transcoder(content["mediafile"], content["url"])
            transcoder.transcode_from_disk(mp3=True)
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
        _check_valid_content(content, ["video/"])
        try:
            transcoder = Transcoder(content["mediafile"], content["url"])
            transcoder.transcode_from_disk(mp4=True)
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
        _check_valid_content(content, ["image/", "video/"])
        try:
            transcoder = Transcoder(content["mediafile"], content["url"])
            if "image/" in content["mimetype"]:
                transcoder.add_image_width_height()
            else:
                transcoder.transcode_from_disk(video_width_height=True)
        except Exception as ex:
            return str(ex), 400
        return (
            f'Successfully added {content["mediafile"]["filename"]} width & height',
            201,
        )

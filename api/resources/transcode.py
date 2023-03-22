from app import policy_factory
from flask import request
from flask_restful import abort, Resource
from inuits_policy_based_auth import RequestContext
from transcoder import Transcoder


class BaseTranscode(Resource):
    def __get_request_body(self):
        if request_body := request.get_json(silent=True):
            return request_body
        abort(405, message="Invalid input")

    def __is_malformed_message(self, data, fields, mimetypes):
        if not all(x in data for x in fields):
            abort(405, message="Malformed request body")
        if not any(x in data["mediafile"]["mimetype"] for x in mimetypes):
            abort(405, message="Mimetype not allowed")

    def post(self, operation, mimetypes, message):
        content = self.__get_request_body()
        self.__is_malformed_message(
            content, ["mediafile", "mimetype", "url"], mimetypes
        )
        if operation == "mp3" and content["mimetype"] == "audio/mpeg":
            abort(400, message=f'{content["mediafile"]["filename"]} is already an mp3')
        try:
            Transcoder().transcode(content["mediafile"], content["url"], operation)
        except Exception as ex:
            return str(ex), 400
        return message.format(content["mediafile"]["filename"]), 201


class JpegTranscode(BaseTranscode):
    @policy_factory.apply_policies(RequestContext(request, ["transcode-to-jpeg"]))
    def post(self):
        return super().post("jpg", ["image/"], "Successfully transcoded {} to jpeg")


class MP3Transcode(BaseTranscode):
    @policy_factory.apply_policies(RequestContext(request, ["transcode-to-mp3"]))
    def post(self):
        return super().post("mp3", ["audio/"], "Successfully transcoded {} to mp3")


class MP4Transcode(BaseTranscode):
    @policy_factory.apply_policies(RequestContext(request, ["transcode-to-mp4"]))
    def post(self):
        return super().post("mp4", ["video/"], "Successfully transcoded {} to mp4")


class WidthHeightTranscode(BaseTranscode):
    @policy_factory.apply_policies(
        RequestContext(request, ["transcode-add-width-height"])
    )
    def post(self):
        return super().post(
            "width_height", ["image/", "video/"], "Successfully added {} width & height"
        )

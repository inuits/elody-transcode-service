import os

from app import policy_factory
from cloudevents.conversion import to_dict
from cloudevents.http import CloudEvent
from flask import request
from flask_restful import abort, Resource
from inuits_policy_based_auth import RequestContext
from transcoder import Transcoder


class BaseTranscode(Resource):
    def __is_malformed_message(self, data, fields, mimetypes):
        if not all(x in data for x in fields):
            abort(405, message="Malformed request body")
        if not any(x in data["mediafile"]["mimetype"] for x in mimetypes):
            abort(405, message="Mimetype not allowed")

    def _get_auth_headers(self):
        if tenant := request.headers.get("apikey"):
            return {"apikey": tenant}
        return {"Authorization": f'Bearer {os.getenv("STATIC_JWT")}'}

    def _get_request_body(self):
        if request_body := request.get_json(silent=True):
            return request_body
        abort(405, message="Invalid input")

    def post(self, operation, mimetypes, message):
        content = self._get_request_body()
        self.__is_malformed_message(content, ["mediafile", "mimetype"], mimetypes)
        if operation == "mp3" and content["mimetype"] == "audio/mpeg":
            abort(
                400, message=f'{content["mediafile"]["identifier"]} is already an mp3'
            )
        try:
            Transcoder().transcode(
                content["mediafile"],
                operation,
                self._get_auth_headers(),
            )
        except Exception as ex:
            return str(ex), 400
        return message.format(content["mediafile"]["identifier"]), 201


class JpegTranscode(BaseTranscode):
    @policy_factory.authenticate(RequestContext(request))
    def post(self):
        return super().post("jpg", ["image/"], "Successfully transcoded {} to jpeg")


class MP3Transcode(BaseTranscode):
    @policy_factory.authenticate(RequestContext(request))
    def post(self):
        return super().post("mp3", ["audio/"], "Successfully transcoded {} to mp3")


class MP4Transcode(BaseTranscode):
    @policy_factory.authenticate(RequestContext(request))
    def post(self):
        return super().post("mp4", ["video/"], "Successfully transcoded {} to mp4")


class WidthHeightTranscode(BaseTranscode):
    @policy_factory.authenticate(RequestContext(request))
    def post(self):
        return super().post(
            "width_height", ["image/", "video/"], "Successfully added {} width & height"
        )


class PDFTranscode(BaseTranscode):
    @policy_factory.authenticate(RequestContext(request))
    def post(self):
        content = self._get_request_body()
        master_entity_id = request.args.get("master_entity_id", "", str)
        try:
            Transcoder().transcode_multiple_mediafiles(
                content["mediafiles"],
                "pdf",
                self._get_auth_headers(),
                master_entity_id,
            )
        except Exception as ex:
            return str(ex), 400
        return (
            f"Successfully generated PDF from {len(content['mediafiles'])} images",
            201,
        )


class ZipTranscode(BaseTranscode):
    @policy_factory.authenticate(RequestContext(request))
    def post(self):
        attributes = {"type": "dams.create_zip", "source": "dams"}
        data = self._get_request_body()
        data["auth_headers"] = self._get_auth_headers()
        event = to_dict(CloudEvent(attributes, data))
        app.rabbit.send(event, routing_key="dams.create_zip")
        return (
            "ZIP creation job place on the queue",
            201,
        )

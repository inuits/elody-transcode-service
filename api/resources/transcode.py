import app

from flask_restful import abort
from resources.base_resource import BaseResource
from transcoder import Transcoder


class JpegTranscode(BaseResource):
    @app.require_oauth("transcode-to-jpeg")
    def post(self):
        content = self._get_request_body()
        self._check_valid_content(content, ["image/"])
        try:
            transcoder = Transcoder(content["mediafile"], content["url"])
            transcoder.transcode_to_jpeg()
        except Exception as ex:
            return str(ex), 400
        return (
            f'Successfully transcoded {content["mediafile"]["filename"]} to jpeg',
            201,
        )


class MP3Transcode(BaseResource):
    @app.require_oauth("transcode-to-mp3")
    def post(self):
        content = self._get_request_body()
        self._check_valid_content(content, ["audio/"])
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


class MP4Transcode(BaseResource):
    @app.require_oauth("transcode-to-mp4")
    def post(self):
        content = self._get_request_body()
        self._check_valid_content(content, ["video/"])
        try:
            transcoder = Transcoder(content["mediafile"], content["url"])
            transcoder.transcode_from_disk(mp4=True)
        except Exception as ex:
            return str(ex), 400
        return (
            f'Successfully transcoded {content["mediafile"]["filename"]} to mp4',
            201,
        )


class WidthHeightTranscode(BaseResource):
    @app.require_oauth("transcode-add-width-height")
    def post(self):
        content = self._get_request_body()
        self._check_valid_content(content, ["image/", "video/"])
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

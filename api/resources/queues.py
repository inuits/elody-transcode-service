import app

from transcoder import Transcoder


def __is_malformed_message(data, mimetypes):
    if "mediafile" not in data or "mimetype" not in data or "url" not in data:
        return False
    if not any(x in data["mimetype"] for x in mimetypes):
        return False
    return True


@app.rabbit.queue("dams.file_uploaded")
def transcode_add_width_height(routing_key, body, message_id):
    data = body["data"]
    if not __is_malformed_message(data, ["image/", "video/"]):
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        if "image/" in data["mediafile"]["mimetype"]:
            transcoder.transcode("width_height_image")
        else:
            transcoder.transcode("width_height_video")
    except Exception as ex:
        message = (
            f'Adding dimensions for {data["mediafile"]["filename"]} failed with: {ex}'
        )
        app.logger.error(message)


@app.rabbit.queue("dams.file_uploaded")
def transcode_to_jpeg(routing_key, body, message_id):
    data = body["data"]
    if not __is_malformed_message(data, ["image/"]):
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        transcoder.transcode("jpg")
    except Exception as ex:
        message = f'Transcoding {data["mediafile"]["filename"]} failed with: {ex}'
        app.logger.error(message)


@app.rabbit.queue("dams.file_uploaded")
def transcode_to_mp3(routing_key, body, message_id):
    data = body["data"]
    if not __is_malformed_message(data, ["audio/"]) or data["mimetype"] == "audio/mpeg":
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        transcoder.transcode("mp3")
    except Exception as ex:
        message = f'Transcoding {data["mediafile"]["filename"]} failed with: {ex}'
        app.logger.error(message)


@app.rabbit.queue("dams.file_uploaded")
def transcode_to_mp4(routing_key, body, message_id):
    data = body["data"]
    if not __is_malformed_message(data, ["video/"]):
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        transcoder.transcode("mp4")
    except Exception as ex:
        message = f'Transcoding {data["mediafile"]["filename"]} failed with: {ex}'
        app.logger.error(message)

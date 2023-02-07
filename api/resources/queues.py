import app

from transcoder import Transcoder


def __is_malformed_message(data, fields, mimetypes):
    if not all(x in data for x in fields):
        app.logger.error(f"Message malformed: missing one of {fields}")
        return True
    if not any(x in data["mediafile"]["mimetype"] for x in mimetypes):
        return True
    return False


@app.rabbit.queue("dams.file_uploaded")
def transcode_add_width_height(routing_key, body, message_id):
    data = body["data"]
    if __is_malformed_message(
        data, ["mediafile", "mimetype", "url"], ["image/", "video/"]
    ):
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        transcoder.transcode("width_height")
    except Exception as ex:
        message = (
            f'Adding dimensions for {data["mediafile"]["filename"]} failed with: {ex}'
        )
        app.logger.error(message)


@app.rabbit.queue("dams.file_uploaded")
def transcode_to_jpeg(routing_key, body, message_id):
    data = body["data"]
    if __is_malformed_message(data, ["mediafile", "mimetype", "url"], ["image/"]):
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
    if (
        __is_malformed_message(data, ["mediafile", "mimetype", "url"], ["audio/"])
        or data["mimetype"] == "audio/mpeg"
    ):
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
    if __is_malformed_message(data, ["mediafile", "mimetype", "url"], ["video/"]):
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        transcoder.transcode("mp4")
    except Exception as ex:
        message = f'Transcoding {data["mediafile"]["filename"]} failed with: {ex}'
        app.logger.error(message)

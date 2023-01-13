import app

from transcoder import Transcoder


def __should_process_message(data, mimetypes):
    if "mediafile" not in data or "mimetype" not in data or "url" not in data:
        return False
    if not any(x in data["mimetype"] for x in mimetypes):
        return False
    return True


@app.rabbit.queue("dams.file_uploaded")
def transcode_add_width_height(routing_key, body, message_id):
    data = body["data"]
    if not __should_process_message(data, ["image/", "video/"]):
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        if "image/" in data["mediafile"]["mimetype"]:
            transcoder.add_image_width_height()
        else:
            transcoder.transcode_from_disk(video_width_height=True)
    except Exception as ex:
        message = (
            f'Adding dimensions for {data["mediafile"]["filename"]} failed with: {ex}'
        )
        app.logger.error(message)


@app.rabbit.queue("dams.file_uploaded")
def transcode_to_jpeg(routing_key, body, message_id):
    data = body["data"]
    if not __should_process_message(data, ["image/"]):
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        transcoder.transcode_to_jpeg()
    except Exception as ex:
        message = f'Transcoding {data["mediafile"]["filename"]} failed with: {ex}'
        app.logger.error(message)


@app.rabbit.queue("dams.file_uploaded")
def transcode_to_mp3(routing_key, body, message_id):
    data = body["data"]
    if (
        not __should_process_message(data, ["audio/"])
        or data["mimetype"] == "audio/mpeg"
    ):
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        transcoder.transcode_from_disk(mp3=True)
    except Exception as ex:
        message = f'Transcoding {data["mediafile"]["filename"]} failed with: {ex}'
        app.logger.error(message)


@app.rabbit.queue("dams.file_uploaded")
def transcode_to_mp4(routing_key, body, message_id):
    data = body["data"]
    if not __should_process_message(data, ["video/"]):
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        transcoder.transcode_from_disk(mp4=True)
    except Exception as ex:
        message = f'Transcoding {data["mediafile"]["filename"]} failed with: {ex}'
        app.logger.error(message)

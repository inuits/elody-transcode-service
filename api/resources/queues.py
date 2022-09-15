import app

from transcoder import Transcoder


def __should_process_message(data, mimetypes):
    if "mediafile" not in data or "mimetype" not in data or "url" not in data:
        return False
    if not any(x in data["mimetype"] for x in mimetypes):
        return False
    return True


@app.rabbit.queue("dams.file_uploaded")
def start_file_transcode(routing_key, body, message_id):
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
def add_pic_dimensions(routing_key, body, message_id):
    data = body["data"]
    if not __should_process_message(data, ["image/", "video/"]):
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        if "image/" in data["mediafile"]["mimetype"]:
            transcoder.add_image_width_height()
        else:
            transcoder.add_video_width_height()
    except Exception as ex:
        message = (
            f'Adding dimensions for {data["mediafile"]["filename"]} failed with: {ex}'
        )
        app.logger.error(message)


@app.rabbit.queue("dams.file_uploaded")
def transcode_to_mp4(routing_key, body, message_id):
    data = body["data"]
    if not __should_process_message(data, ["video/"]):
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        transcoder.transcode_to_mp4()
    except Exception as ex:
        message = f'Transcoding {data["mediafile"]["filename"]} failed with: {ex}'
        app.logger.error(message)


@app.rabbit.queue("dams.file_uploaded")
def transcode_to_mp3(routing_key, body, message_id):
    data = body["data"]
    if not __should_process_message(data, ["audio/"]) or data["madiafile"][
        "filename"
    ].lower().endswith("mp3"):
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        transcoder.transcode_to_mp3()
    except Exception as ex:
        message = f'Transcoding {data["mediafile"]["filename"]} failed with: {ex}'
        app.logger.error(message)

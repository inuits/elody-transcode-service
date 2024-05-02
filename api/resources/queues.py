import app

from transcoder import Transcoder


def __is_malformed_message(data, fields, mimetypes):
    if not all(x in data for x in fields):
        app.logger.error(f"Message malformed: missing one of {fields}")
        return True
    if not any(x in data["mediafile"]["mimetype"] for x in mimetypes):
        return True
    return False


def __do_transcode(body, operation, mimetypes, error_message):
    data = body["data"]
    if __is_malformed_message(data, ["mediafile", "mimetype"], mimetypes):
        return
    try:
        if "headers" in data:
            Transcoder().transcode(data["mediafile"], operation, data.get("headers"))
        else:
            Transcoder().transcode(data["mediafile"], operation)
    except Exception as ex:
        app.logger.error(f'{error_message.format(data["mediafile"]["filename"])} {ex}')


@app.rabbit.queue("dams.create_zip")
def create_zip(routing_key, body, message_id):
    data = body["data"]
    try:
        zip_location = Transcoder().create_zip(
            data,
            data["auth_headers"],
        )
    except Exception as ex:
        app.logger.error(f"Could not create ZIP-file {ex}")


@app.rabbit.queue("dams.file_uploaded")
def transcode_add_width_height(routing_key, body, message_id):
    __do_transcode(
        body,
        "width_height",
        ["image/", "video/"],
        "Adding width & height for {} failed with:",
    )


@app.rabbit.queue("dams.file_uploaded")
def transcode_to_jpeg(routing_key, body, message_id):
    __do_transcode(body, "jpg", ["image/"], "Transcoding {} to jpeg failed with:")


@app.rabbit.queue("dams.file_uploaded")
def transcode_to_mp3(routing_key, body, message_id):
    __do_transcode(body, "mp3", ["audio/"], "Transcoding {} to mp3 failed with:")


@app.rabbit.queue("dams.file_uploaded")
def transcode_to_mp4(routing_key, body, message_id):
    __do_transcode(body, "mp4", ["video/"], "Transcoding {} to mp4 failed with:")

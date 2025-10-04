import app

from transcoder import Transcoder
from rabbit import get_rabbit
from os import getenv


def __is_malformed_message(data, fields, mimetypes):
    if not all(x in data for x in fields):
        app.logger.error(f"Message malformed: missing one of {fields}")
        return True
    if not any(x in data["mediafile"]["mimetype"] for x in mimetypes):
        return True
    return False


queue_prefix = getenv("QUEUE_PREFIX", "basic")
# queue_type = getenv("QUEUE_TYPE", "classic")
routing_key_prefix = getenv("ROUTING_KEY_PREFIX", "dams")


def __argument_wrapper(*, queue_name, routing_key):
    arguments = {"routing_key": routing_key}
    if getenv("AMQP_MANAGER", "amqpstorm_flask") == "amqpstorm_flask":
        arguments["queue_name"] = queue_name
        # if queue_type:
        #     arguments["queue_arguments"] = {"x-queue-type": queue_type}
    return arguments


def __do_transcode(body, operation, mimetypes, error_message):
    data = body["data"]
    parent_job_id = data.get("parent_job_id")
    if __is_malformed_message(data, ["mediafile", "mimetype"], mimetypes):
        return
    try:
        if "headers" in data:
            Transcoder().transcode(
                data["mediafile"], operation, data.get("headers"), parent_job_id
            )
        else:
            Transcoder().transcode(
                data["mediafile"], operation, parent_job_id=parent_job_id
            )
    except Exception as ex:
        app.logger.error(f'{error_message.format(data["mediafile"]["filename"])} {ex}')


@get_rabbit().queue(
    **__argument_wrapper(queue_name="basic.create_zip", routing_key="dams.create_zip")
)
def create_zip(routing_key, body, message_id):
    data = body["data"]
    user_email = data.pop("user_email", None)
    try:
        zip_location = Transcoder().create_zip(
            data, data["auth_headers"], user_email=user_email
        )
    except Exception as ex:
        app.logger.error(f"Could not create ZIP-file {ex}")


@get_rabbit().queue(
    **__argument_wrapper(
        queue_name="basic.transcode.add.width.height", routing_key="dams.file_uploaded"
    )
)
def transcode_add_width_height(routing_key, body, message_id):
    __do_transcode(
        body,
        "width_height",
        ["image/", "video/"],
        "Adding width & height for {} failed with:",
    )


@get_rabbit().queue(
    **__argument_wrapper(
        queue_name="basic.transcode.to.jpeg", routing_key="dams.file_uploaded"
    )
)
def transcode_to_jpeg(routing_key, body, message_id):
    __do_transcode(body, "jpg", ["image/"], "Transcoding {} to jpeg failed with:")


@get_rabbit().queue(
    **__argument_wrapper(
        queue_name="basic.transcode.to.mp3", routing_key="dams.file_uploaded"
    )
)
def transcode_to_mp3(routing_key, body, message_id):
    __do_transcode(body, "mp3", ["audio/"], "Transcoding {} to mp3 failed with:")


@get_rabbit().queue(
    **__argument_wrapper(
        queue_name="basic.transcode.to.mp4", routing_key="dams.file_uploaded"
    )
)
def transcode_to_mp4(routing_key, body, message_id):
    __do_transcode(body, "mp4", ["video/"], "Transcoding {} to mp4 failed with:")

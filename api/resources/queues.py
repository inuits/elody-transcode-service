import app
from amqpstorm import Message
from policy_factory import get_user_context

from elody.job import (
    fail_job,
    finish_job,
    init_job,
    start_job,
    add_document_to_job,
    finish_job_with_warning,
)
from transcoder import Transcoder
from rabbit import get_rabbit
from os import error, getenv
from converter.ffmpeg import FFMpegConvertError


def __is_malformed_message(data, fields, mimetypes):
    if not all(x in data for x in fields):
        app.logger.error(f"Message malformed: missing one of {fields}")
        return True
    if not any(x in data["mediafile"]["mimetype"] for x in mimetypes):
        return True
    return False


queue_prefix = getenv("QUEUE_PREFIX", "basic")
global_queue_type = getenv("QUEUE_TYPE", "classic")
routing_key_prefix = getenv("ROUTING_KEY_PREFIX", "dams")
delivery_limit = getenv("DELIVERY_LIMIT", 4)


def __argument_wrapper(*, queue_name, routing_key, queue_type=global_queue_type):
    arguments = {"routing_key": routing_key}
    if getenv("AMQP_MANAGER", "amqpstorm_flask") == "amqpstorm_flask":
        arguments["queue_name"] = queue_name
        queue_arguments = {}
        if queue_type:
            queue_arguments.update({"x-queue-type": queue_type})
        if delivery_limit and queue_type == "quorum":
            queue_arguments.update({"x-delivery-limit": delivery_limit})
        arguments["queue_arguments"] = queue_arguments
    return arguments


def __handle_transcode_message(body):
    mimetypes_transcode_mapping = {
        "image": ["transcode_add_width_height", "transcode_to_jpeg"],
        "audio": ["transcode_to_mp3"],
        "video": ["transcode_add_width_height", "transcode_to_mp4"],
    }

    data = body["data"]
    parent_job_id = data.get("parent_job_id")
    mimetype: str = data["mediafile"]["mimetype"]
    mimetype_start = mimetype.split("/")[0]

    routing_keys = mimetypes_transcode_mapping.get(mimetype_start, [])
    if not routing_keys:
        if parent_job_id:

            job_id = init_job(
                name=f"Transcode {data['mediafile']['original_filename']}",
                job_type="Transcode Unsupported Format",
                get_rabbit=get_rabbit,
                user_email=data.get("user_email", "developers@inuits.eu"),
                parent_id=parent_job_id,
            )
            finish_job_with_warning(
                job_id,
                get_rabbit=get_rabbit,
                info_message=f"Generating transcode for mimetypes {mimetype} currently not supported.",
            )
        # TODO: Log this normally as well
    for routing_key in routing_keys:
        get_rabbit().send(body, routing_key=f"{routing_key_prefix}.{routing_key}")


def __do_transcode(body, operation, mimetypes, error_message):
    format_error_message = None
    data = body["data"]
    parent_job_id = data.get("parent_job_id")
    ignore_duplicates = bool(data.get("ignore_duplicates", False))
    if __is_malformed_message(data, ["mediafile", "mimetype"], mimetypes):
        return

    job_id = init_job(
        name=f"Transcode {data['mediafile']['original_filename']}",
        job_type=f"Transcode {operation}",
        get_rabbit=get_rabbit,
        user_email=data.get("user_email", "developers@inuits.eu"),
        parent_id=parent_job_id,
    )
    try:
        start_job(job_id, get_rabbit=get_rabbit)
        if "headers" in data:
            Transcoder().transcode(
                data["mediafile"],
                operation,
                data.get("headers"),
                parent_job_id,
                ignore_duplicate_check=ignore_duplicates,
            )
        else:
            Transcoder().transcode(
                data["mediafile"],
                operation,
                parent_job_id=parent_job_id,
                ignore_duplicate_check=ignore_duplicates,
            )

        add_document_to_job(
            id=job_id,
            id_of_document_job_was_initiated_for=data["mediafile"]["_id"],
            get_rabbit=get_rabbit,
        )
        finish_job(job_id, get_rabbit=get_rabbit)
    except FFMpegConvertError as ex:
        format_error_message = (
            f'{error_message.format(data["mediafile"]["filename"])} {ex.message}'
        )
    except Exception as ex:
        format_error_message = (
            f'{error_message.format(data["mediafile"]["filename"])} {ex}'
        )

    if format_error_message:
        fail_job(job_id, get_rabbit=get_rabbit, exception_message=format_error_message)
        app.logger.error(format_error_message)


# NOTE: Not changing this one currently, it should work pretty instantly (and should actually be reworked anyways)
@get_rabbit().queue(
    **__argument_wrapper(
        queue_name=f"{queue_prefix}.transcode.handler",
        routing_key=[
            f"{routing_key_prefix}.file_uploaded",
            f"{routing_key_prefix}.regenerate_transcode",
        ],
    )
)
def dispatch_transcode(routing_key, body, message_id):
    __handle_transcode_message(body)


@get_rabbit().queue(
    **__argument_wrapper(
        queue_name=f"{queue_prefix}.create.zip",
        routing_key=f"{routing_key_prefix}.create_zip",
        queue_type="quorum",
    ),
    auto_ack=False,
    full_message_object=True,
)
def create_zip(message: Message):
    body = message.json()
    data = body["data"]
    user_email = data.pop("user_email", None)
    try:
        zip_location = Transcoder().create_zip(
            data, data["auth_headers"], user_email=user_email
        )
        message.ack()
    except Exception as ex:
        app.logger.error(f"Could not create ZIP-file {ex}")
        message.nack()


@get_rabbit().queue(
    **__argument_wrapper(
        queue_name=f"{queue_prefix}.transcode.add.width.height",
        routing_key=[
            f"{routing_key_prefix}.transcode_add_width_height",
        ],
        queue_type="quorum",
    ),
    auto_ack=False,
    full_message_object=True,
)
def transcode_add_width_height(message: Message):
    body = message.json()
    __do_transcode(
        body,
        "width_height",
        ["image/", "video/"],
        "Adding width & height for {} failed with:",
    )
    message.ack()


@get_rabbit().queue(
    **__argument_wrapper(
        queue_name=f"{queue_prefix}.transcode.to.jpeg",
        routing_key=[
            f"{routing_key_prefix}.transcode_to_jpeg",
        ],
        queue_type="quorum",
    ),
    auto_ack=False,
    full_message_object=True,
)
def transcode_to_jpeg(message: Message):
    # def transcode_to_jpeg(routing_key, body, message_id):

    body = message.json()
    __do_transcode(body, "jpg", ["image/"], "Transcoding {} to jpeg failed with:")
    message.ack()


@get_rabbit().queue(
    **__argument_wrapper(
        queue_name=f"{queue_prefix}.transcode.to.mp3",
        routing_key=[
            f"{routing_key_prefix}.transcode_to_mp3",
        ],
        queue_type="quorum",
    ),
    auto_ack=False,
    full_message_object=True,
)
def transcode_to_mp3(message: Message):
    body = message.json()
    __do_transcode(body, "mp3", ["audio/"], "Transcoding {} to mp3 failed with:")
    message.ack()


@get_rabbit().queue(
    **__argument_wrapper(
        queue_name=f"{queue_prefix}.transcode.to.mp4",
        routing_key=[
            f"{routing_key_prefix}.transcode_to_mp4",
        ],
        queue_type="quorum",
    ),
    auto_ack=False,
    full_message_object=True,
)
def transcode_to_mp4(message: Message):
    body = message.json()
    __do_transcode(body, "mp4", ["video/"], "Transcoding {} to mp4 failed with:")
    message.ack()

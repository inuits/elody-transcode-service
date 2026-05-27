from os import getenv

import app
from amqpstorm import Message
from converter.ffmpeg import FFMpegConvertError
from elody.job import (
    add_document_to_job,
    fail_job,
    finish_job,
    init_job,
    start_job,
)
from rabbit import get_rabbit
from transcoder import Transcoder


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


def __argument_wrapper(
    *,
    queue_name,
    routing_key,
    queue_type=global_queue_type,
    consumer_timeout=None,
    delivery_limit=delivery_limit,
):
    arguments = {"routing_key": routing_key}
    if getenv("AMQP_MANAGER", "amqpstorm_flask") == "amqpstorm_flask":
        arguments["queue_name"] = queue_name
        queue_arguments = {}
        if consumer_timeout:
            queue_arguments.update({"x-consumer-timeout": consumer_timeout})
        if queue_type:
            queue_arguments.update({"x-queue-type": queue_type})
        if delivery_limit and queue_type == "quorum":
            queue_arguments.update({"x-delivery-limit": delivery_limit})
        arguments["queue_arguments"] = queue_arguments
    return arguments


def __filesize_warning(filesize: str) -> bool:
    try:
        units = {"b": 1, "kb": 10**3, "mb": 10**6, "gb": 10**9, "tb": 10**12}
        number, unit = [
            filesize_part.strip() for filesize_part in filesize.lower().split()
        ]
        size_bytes = float(number) * units[unit]
    except Exception:
        # This means something went wrong with the filesize calculations
        return False

    if size_bytes > 1 * units["gb"]:
        return True

    return False


def __do_transcode(
    body,
    operation,
    mimetypes,
    error_message,
):
    format_error_message = None
    data = body["data"]
    parent_job_id = data.get("parent_job_id")
    ignore_duplicates = bool(data.get("ignore_duplicates", False))
    if __is_malformed_message(
        data,
        ["mediafile", "mimetype"],
        mimetypes,  # Technically this check on mimetypes is no longer needed,
        # since we only bind to topics of the correct mimetype now
    ):
        return

    job_id = init_job(
        name=f"Transcode {data['mediafile']['original_filename']}",
        job_type=f"Transcode {operation}",
        get_rabbit=get_rabbit,
        user_email=data.get("user_email", "developers@inuits.eu"),
        parent_id=parent_job_id,
    )
    try:
        filesize = data["mediafile"].get("filesize", "unknown")
        app.logger.info(
            f"Starting transcode for {data['mediafile']['original_filename']}, size: {filesize}"
        )
        if __filesize_warning(filesize):
            app.logger.warning(
                f"Filesize {filesize} large for mediafile {data['mediafile']['_id']}, may cause OOM"
            )
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
            f"{error_message.format(data['mediafile']['filename'])} {ex.message}"
        )
    except Exception as ex:
        format_error_message = (
            f"{error_message.format(data['mediafile']['filename'])} {ex}"
        )

    if format_error_message:
        fail_job(job_id, get_rabbit=get_rabbit, exception_message=format_error_message)
        app.logger.error(format_error_message)


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
        Transcoder().create_zip(data, data["auth_headers"], user_email=user_email)
        message.ack()
    except Exception as ex:
        app.logger.error(f"Could not create ZIP-file {ex}")
        message.nack()


@get_rabbit().queue(
    **__argument_wrapper(
        queue_name=f"{queue_prefix}.transcode.to.jpeg",
        routing_key=[
            f"{routing_key_prefix}.transcode_to_jpeg",
            f"{routing_key_prefix}.file_uploaded.image.*",
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
            f"{routing_key_prefix}.file_uploaded.audio.*",
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
            f"{routing_key_prefix}.file_uploaded.video.*",
        ],
        queue_type="quorum",
        consumer_timeout=14400000,
    ),
    auto_ack=False,
    full_message_object=True,
)
def transcode_to_mp4(message: Message):
    body = message.json()
    __do_transcode(body, "mp4", ["video/"], "Transcoding {} to mp4 failed with:")
    message.ack()

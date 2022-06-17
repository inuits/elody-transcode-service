import json
import logging
import os

from flask import Flask
from flask_restful import Api
from flask_swagger_ui import get_swaggerui_blueprint
from healthcheck import HealthCheck
from inuits_jwt_auth.authorization import JWTValidator, MyResourceProtector
from rabbitmq_pika_flask import RabbitMQ
from transcoder import Transcoder

SWAGGER_URL = "/api/docs"  # URL for exposing Swagger UI (without trailing '/')
API_URL = "/spec/dams-transcode-service.json"  # Our API url (can of course be a local resource)

swaggerui_blueprint = get_swaggerui_blueprint(SWAGGER_URL, API_URL)

app = Flask(__name__)

api = Api(app)

app.config.update(
    {
        "MQ_EXCHANGE": os.getenv("RABMQ_SEND_EXCHANGE_NAME"),
        "MQ_URL": os.getenv("RABMQ_RABBITMQ_URL"),
        "SECRET_KEY": "SomethingNotEntirelySecret",
        "TESTING": True,
        "DEBUG": True,
    }
)

logging.basicConfig(
    format="%(asctime)s %(process)d,%(threadName)s %(filename)s:%(lineno)d [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

rabbit = RabbitMQ()
rabbit.init_app(app, "basic", json.loads, json.dumps)


def rabbit_available():
    return True, rabbit.get_connection().is_open


health = HealthCheck()
if os.getenv("HEALTH_CHECK_EXTERNAL_SERVICES", True) in ["True", "true", True]:
    health.add_check(rabbit_available)

app.add_url_rule("/health", "healthcheck", view_func=lambda: health.run())


def _should_process_message(data, mimetypes):
    if "mediafile" not in data or "mimetype" not in data or "url" not in data:
        return False
    if not any(x in data["mimetype"] for x in mimetypes):
        return False
    return True


@rabbit.queue("dams.file_uploaded")
def start_file_transcode(routing_key, body, message_id):
    data = body["data"]
    if not _should_process_message(data, ["image/"]):
        return
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        transcoder.transcode_to_jpeg()
    except Exception as ex:
        message = f'Transcoding {data["mediafile"]["filename"]} failed with: {ex}'
        logger.error(message)


@rabbit.queue("dams.file_uploaded")
def add_pic_dimensions(routing_key, body, message_id):
    data = body["data"]
    if not _should_process_message(data, ["image/", "video/"]):
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
        logger.error(message)


require_oauth = MyResourceProtector(
    os.getenv("REQUIRE_TOKEN", True) == ("True" or "true" or True),
)
validator = JWTValidator(
    logger,
    os.getenv("STATIC_ISSUER", False),
    os.getenv("STATIC_PUBLIC_KEY", False),
    os.getenv("REALMS", "").split(","),
    os.getenv("ROLE_PERMISSION_FILE", "role_permission.json"),
    os.getenv("SUPER_ADMIN_ROLE", "role_super_admin"),
    os.getenv("REMOTE_TOKEN_VALIDATION", False),
)
require_oauth.register_token_validator(validator)

app.register_blueprint(swaggerui_blueprint)

from resources.spec import AsyncAPISpec, OpenAPISpec
from resources.transcode import JpegTranscode, WidthHeightTranscode

api.add_resource(AsyncAPISpec, "/spec/dams-transcode-service-events.html")
api.add_resource(OpenAPISpec, "/spec/dams-transcode-service.json")

api.add_resource(JpegTranscode, "/transcode/jpeg")
api.add_resource(WidthHeightTranscode, "/transcode/widthheight")

if __name__ == "__main__":
    app.run(debug=True)

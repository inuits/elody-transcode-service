import json
import logging
import os

import requests
from flask import Flask
from flask_restful import Api
from flask_swagger_ui import get_swaggerui_blueprint
from healthcheck import HealthCheck
from inuits_jwt_auth.authorization import JWTValidator, MyResourceProtector
from job_helper.job_helper import JobHelper
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
job_api_base_url = os.getenv("JOB_API_BASE_URL", "http://collection-api:8000")
"""
job_helper = JobHelper(
    job_api_base_url=job_api_base_url,
    static_jwt=os.getenv("STATIC_JWT", False),
)
"""

rabbit = RabbitMQ()
rabbit.init_app(app, "basic", json.loads, json.dumps)


def job_api_available():
    return True, requests.get(f'{job_api_base_url}{"/health"}').json()


def rabbit_available():
    return True, rabbit.get_connection().is_open


health = HealthCheck()
if os.getenv("HEALTH_CHECK_EXTERNAL_SERVICES", True) in ["True", "true", True]:
    health.add_check(rabbit_available)

app.add_url_rule("/health", "healthcheck", view_func=lambda: health.run())


def _should_process_message(data):
    if "mediafile" not in data or "mimetype" not in data or "url" not in data:
        return False
    accepted_mimetypes = [
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/tiff",
    ]
    if data["mimetype"] not in accepted_mimetypes:
        return False
    return True


@rabbit.queue("dams.file_uploaded")
def start_file_transcode(routing_key, body, message_id):
    data = body["data"]
    if not _should_process_message(data):
        return True
    # job = job_helper.create_new_job("Import csv", "import csv")
    # job = job_helper.progress_job(job)
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        transcoder.transcode_to_jpeg()
        # job_helper.finish_job(job)
    except Exception as ex:
        message = f'Transcoding {data["mediafile"]["filename"]} failed with: {ex}'
        logger.error(message)
        # job_helper.fail_job(job, message)
    return True


@rabbit.queue("dams.file_uploaded")
def add_pic_dimensions(routing_key, body, message_id):
    data = body["data"]
    if not _should_process_message(data):
        return True
    # job = job_helper.create_new_job("Import csv", "import csv")
    # job = job_helper.progress_job(job)
    try:
        transcoder = Transcoder(data["mediafile"], data["url"])
        transcoder.add_pic_dimensions()
        # job_helper.finish_job(job)
    except Exception as ex:
        message = (
            f'Adding dimensions for {data["mediafile"]["filename"]} failed with: {ex}'
        )
        logger.error(message)
        # job_helper.fail_job(job, message)
    return True


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
from resources.transcode import Transcode

api.add_resource(AsyncAPISpec, "/spec/dams-transcode-service-events.html")
api.add_resource(OpenAPISpec, "/spec/dams-transcode-service.json")

api.add_resource(Transcode, "/transcode")

if __name__ == "__main__":
    app.run(debug=True)

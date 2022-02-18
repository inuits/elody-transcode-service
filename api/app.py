import json
import logging
import os

from flask import Flask
from flask_restful import Api
from flask_swagger_ui import get_swaggerui_blueprint
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
        "MQ_EXCHANGE": os.getenv("RABMQ_SEND_EXCHANGE_NAME", "dams"),
        "MQ_URL": os.getenv("RABMQ_RABBITMQ_URL", "amqp://localhost:5672"),
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
"""
job_helper = JobHelper(
    job_api_base_url=os.getenv("JOB_API_BASE_URL", "http://collection-api:8000"),
    static_jwt=os.getenv("STATIC_JWT", False),
)
"""

rabbit = RabbitMQ()
rabbit.init_app(app, "basic", json.loads, json.dumps)


@rabbit.queue("dams.file_uploaded")
def start_file_transcode(routing_key, body, message_id):
    accepted_mimetypes = ["image/jpeg", "image/tiff", "image/bmp", "image/gif"]
    body_dict = json.loads(body)
    if "mimetype" not in body_dict or "file_location" not in body_dict:
        return True
    if body_dict["mimetype"] not in accepted_mimetypes:
        return True
    # job = job_helper.create_new_job("Import csv", "import csv")
    # job = job_helper.progress_job(job)
    try:

        file_location = body_dict["data"]["file_location"]
        transcoder = Transcoder(file_location)
        transcoder.transcode_to_jpeg()
        # job_helper.finish_job(job)
    except Exception as ex:
        logger.error(f"Starting import failed with: {ex}")
        # job_helper.fail_job(job, str(ex))
    return True


require_oauth = MyResourceProtector(
    os.getenv("STATIC_JWT", False),
    {},
    os.getenv("REQUIRE_TOKEN", True) == ("True" or "true" or True),
)
validator = JWTValidator(
    logger,
    os.getenv("STATIC_JWT", False),
    os.getenv("STATIC_ISSUER", False),
    os.getenv("STATIC_PUBLIC_KEY", False),
    os.getenv("REALMS", "").split(","),
    os.getenv("REQUIRE_TOKEN", True) == ("True" or "true" or True),
)
require_oauth.register_token_validator(validator)

app.register_blueprint(swaggerui_blueprint)

from resources.spec import AsyncAPISpec, OpenAPISpec

api.add_resource(AsyncAPISpec, "/spec/dams-transcode-service-events.html")
api.add_resource(OpenAPISpec, "/spec/dams-transcode-service.json")

if __name__ == "__main__":
    app.run(debug=True)

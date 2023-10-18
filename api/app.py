import json
import logging
import os
import secrets

from flask import Flask
from flask_restful import Api
from flask_swagger_ui import get_swaggerui_blueprint
from healthcheck import HealthCheck
from inuits_jwt_auth.authorization import JWTValidator, MyResourceProtector
from rabbitmq_pika_flask import RabbitMQ

if os.getenv("SENTRY_ENABLED", False) in ["True", "true", True]:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration

    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN"),
        integrations=[FlaskIntegration()],
        environment=os.getenv("NOMAD_NAMESPACE"),
    )

SWAGGER_URL = "/api/docs"  # URL for exposing Swagger UI (without trailing '/')
API_URL = "/spec/dams-transcode-service.json"  # Our API url (can of course be a local resource)

swaggerui_blueprint = get_swaggerui_blueprint(SWAGGER_URL, API_URL)

app = Flask(__name__)
api = Api(app)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(16))

logging.basicConfig(
    format="%(asctime)s %(process)d,%(threadName)s %(filename)s:%(lineno)d [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

rabbit = RabbitMQ()
rabbit.init_app(app, "basic", json.loads, json.dumps)

require_oauth = MyResourceProtector(
    logger,
    os.getenv("REQUIRE_TOKEN", True) in ["True", "true", True],
)
validator = JWTValidator(
    logger,
    os.getenv("STATIC_ISSUER", False),
    os.getenv("STATIC_PUBLIC_KEY", False),
    os.getenv("REALMS", "").split(","),
    os.getenv("ROLE_PERMISSION_FILE", "role_permission.json"),
    os.getenv("SUPER_ADMIN_ROLE", "role_super_admin"),
    os.getenv("REMOTE_TOKEN_VALIDATION", False) in ["True", "true", True],
    os.getenv("REMOTE_PUBLIC_KEY", False),
)
require_oauth.register_token_validator(validator)

app.register_blueprint(swaggerui_blueprint)


def rabbit_available():
    connection = rabbit.get_connection()
    if connection.is_open:
        connection.close()
        return True, "Successfully reached RabbitMQ"
    return False, "Failed to reach RabbitMQ"


health = HealthCheck()
if os.getenv("HEALTH_CHECK_EXTERNAL_SERVICES", True) in ["True", "true", True]:
    health.add_check(rabbit_available)
app.add_url_rule("/health", "healthcheck", view_func=lambda: health.run())

from resources.spec import AsyncAPISpec, OpenAPISpec
from resources.transcode import (
    JpegTranscode,
    MP3Transcode,
    MP4Transcode,
    PDFTranscode,
    WidthHeightTranscode,
)
import resources.queues

api.add_resource(AsyncAPISpec, "/spec/dams-transcode-service-events.html")
api.add_resource(OpenAPISpec, "/spec/dams-transcode-service.json")

api.add_resource(JpegTranscode, "/transcode/jpeg")
api.add_resource(MP3Transcode, "/transcode/mp3")
api.add_resource(MP4Transcode, "/transcode/mp4")
api.add_resource(PDFTranscode, "/transcode/pdf")
api.add_resource(WidthHeightTranscode, "/transcode/widthheight")

if __name__ == "__main__":
    app.run()

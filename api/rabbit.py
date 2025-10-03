from elody.loader import load_queues
from elody.util import CustomJSONEncoder, custom_json_dumps
from importlib import import_module
from json import loads
from os import getenv
from typing import Any


_rabbit = None


def init_rabbit(app):
    global _rabbit
    amqp_module = import_module(getenv("AMQP_MANAGER", "amqpstorm_flask"))
    auto_delete_exchange = getenv("AUTO_DELETE_EXCHANGE", False) in [
        1,
        "1",
        True,
        "True",
        "true",
    ]
    durable_exchange = getenv("DURABLE_EXCHANGE", True) in [
        1,
        "1",
        True,
        "True",
        "true",
    ]
    passive_exchange = getenv("PASSIVE_EXCHANGE", False) in [
        1,
        "1",
        True,
        "True",
        "true",
    ]

    ExchangeParams = (
        amqp_module.ExchangeParams
        if amqp_module.__name__ == "amqpstorm_flask"
        else amqp_module.ExchangeParams.ExchangeParams
    )
    _rabbit = amqp_module.RabbitMQ(
        exchange_params=ExchangeParams(
            auto_delete=auto_delete_exchange,
            durable=durable_exchange,
            passive=passive_exchange,
        )
    )
    if amqp_module.__name__ == "amqpstorm_flask":
        _rabbit.init_app(
            app, "basic", loads, custom_json_dumps, json_encoder=CustomJSONEncoder
        )
    else:
        _rabbit.init_app(app, "basic", loads, custom_json_dumps)
    load_queues(None)


def get_rabbit() -> Any:
    global _rabbit
    return _rabbit

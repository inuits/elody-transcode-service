from typing import Any, TypedDict


class MetadataObject(TypedDict):
    key: str
    value: Any


class RelationObject(TypedDict):
    key: str
    type: str


class ElodyEntity(TypedDict):
    _id: str
    id: str
    metadata: list[MetadataObject]
    relations: list[RelationObject]
    type: str


class MediafileEntity(ElodyEntity):
    original_file_location: str
    original_filename: str
    filename: str

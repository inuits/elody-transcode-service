import os
import posixpath
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import app
import requests
from converter import Converter
from elody.exceptions import NotFoundException
from elody.util import (
    get_boolean_env,
    get_item_metadata_value,
    get_raw_id,
    parse_filename_unfriendly_string,
)
from elody_types import MediafileEntity
from exceptions_transcoder import (
    FileDownloadRetryExhausted,
    GetWidthHeightException,
    UnsupportedOperationException,
)
from PIL import ExifTags, Image
from requests.exceptions import ChunkedEncodingError, ConnectionError
from retry import retry
from storage.base_storage import StorageService
from urllib3.exceptions import IncompleteRead, ProtocolError

Image.MAX_IMAGE_PIXELS = None


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class Transcoder(metaclass=Singleton):
    _registry = {}

    def __init_subclass__(cls, format_name, **kwargs):
        super().__init_subclass__(**kwargs)
        Transcoder._registry[format_name] = cls

    @classmethod
    def get_transcoder(cls, format_name: str, storage_service: StorageService):
        transcoder_class = cls._registry.get(format_name)
        if not transcoder_class:
            raise ValueError(f"No transcoder registered for format: {format_name}")
        return transcoder_class(storage_service)

    def __init__(self, storage_service: StorageService):
        self.storage = storage_service
        self.collection_api_url = os.getenv("COLLECTION_API_URL")
        self.csv_exporter_enabled = get_boolean_env("CSV_EXPORTER_ENABLED", False)
        self.csv_exporter_url = os.getenv("CSV_EXPORTER_URL", None)
        self.headers = {
            "Authorization": f"Bearer {os.getenv('STATIC_JWT')}",
            "X-From-Service": "transcode-service",
        }
        self.storage_api_url: str = os.getenv(
            "STORAGE_API_URL", "http://storage-api:5000/"
        )
        self.zip_working_dir = os.getenv("ZIP_WORKING_DIR", "/app")

    def _add_artist_and_copyright_to_exif(self, exif, artist, copyrights):
        if artist:
            exif[ExifTags.Base.Artist] = artist
        if copyrights:
            exif[ExifTags.Base.Copyright] = copyrights

    def __add_entities_to_zip(
        self,
        zipfile,
        working_dir: Path,
        entity_ids,
        headers=None,
        user_email=None,
    ):
        mediafile_ids = []
        for entity_id in entity_ids:
            entity = self.__get_entity(entity_id)
            entity_identifier = self.__get_entity_identifier_for_csv(entity)
            entity_mediafiles = self.__get_entity_mediafiles(entity_id, headers)
            for mediafile in entity_mediafiles.get("results", []):
                mediafile_ids.append(get_raw_id(mediafile))
                self.__add_single_file_to_zip(
                    zipfile,
                    working_dir,
                    mediafile,
                    headers,
                    destination_path=entity_identifier,
                    user_email=user_email,
                )
        return mediafile_ids

    def __add_mediafiles_to_zip(
        self,
        zipfile,
        working_dir: Path,
        mediafile_ids,
        headers=None,
        user_email=None,
    ):
        for mediafile_id in mediafile_ids:
            mediafile = self.__get_mediafile(mediafile_id, headers)
            self.__add_single_file_to_zip(
                zipfile,
                working_dir,
                mediafile,
                headers,
                user_email=user_email,
            )
        return mediafile_ids

    def __add_objects_csv_to_zip(
        self,
        zipfile,
        working_dir: Path,
        object_ids,
        object_type,
        fields=None,
        headers=None,
    ):
        if csv_for_objects := self.__get_csv_for_objects(
            object_ids,
            object_type,
            fields,
            headers,
        ):
            objects_csv_path = working_dir / f"{object_type}.csv"
            with objects_csv_path.open("w") as objects_csv:
                objects_csv.write(csv_for_objects)
            zipfile.write(objects_csv_path, f"{object_type}.csv")

    def __add_single_file_to_zip(
        self,
        zipfile,
        working_dir: Path,
        mediafile,
        headers=None,
        destination_path: Path = Path(),
        user_email=None,
    ):
        filename: str = mediafile["original_filename"]
        app.logger.debug(f"Adding {filename} to zip.")
        read_location = working_dir / filename
        with read_location.open("wb") as input_file:
            self._get_file(
                self._get_mediafile_download_link(
                    mediafile,
                    headers,
                    user_email=user_email,
                ),
                input_file,
                headers,
            )
        zipfile.write(read_location, Path(destination_path) / filename)
        read_location.unlink()

    def __get_csv_for_objects(
        self,
        object_ids,
        object_type="entities",
        fields=None,
        headers: dict | None = None,
    ):

        object_type_mapper = {"entities": "asset", "mediafiles": "mediafile"}

        if not object_ids:
            return None
        if headers is None:
            headers = {}

        if self.csv_exporter_enabled:
            req = requests.post(
                f"{self.csv_exporter_url}/{object_type}",
                params={
                    "order_by": "title",
                    "limit": len(object_ids),
                    "type": object_type_mapper[object_type],
                },
                json={
                    "ids": object_ids,
                    "fields": fields,
                    "exclude_non_editable_fields": True,
                },
                headers=self.__get_headers(
                    {
                        "Accept": "text/csv",
                        "Content-Type": "application/json",
                        **headers,
                    }
                ),
            )
        else:
            req = requests.get(
                f"{self.collection_api_url}/{object_type}",
                params={
                    "ids": ",".join(object_ids),
                    "field[]": fields,
                    "exclude_non_editable_fields": True,
                },
                headers=self.__get_headers({"Accept": "text/csv", **headers}),
            )
        if req.status_code != 200:
            app.logger.info(
                f"Could not fetch CSV for {object_type}, status code: {req.status_code}, error: {req.text}",
            )
            return None
        return req.text

    def __get_entity(self, entity_id, headers=None):
        entity_url = f"{self.collection_api_url}/entities/{entity_id}"
        req = requests.get(
            entity_url,
            headers=self.__get_headers(headers),
        )
        req.raise_for_status()
        return req.json()

    def __get_entity_identifier_for_csv(self, entity):
        return parse_filename_unfriendly_string(entity.get("id", None)) or entity["_id"]

    def __get_entity_mediafiles(self, entity_id, headers=None):
        entity_mediafiles_url = (
            f"{self.collection_api_url}/entities/{entity_id}/mediafiles"
        )
        params = {"skip": 0, "limit": 100}
        stop = False
        response = {"count": 0, "results": []}
        while not stop:
            req = requests.get(
                entity_mediafiles_url,
                params=params,
                headers=self.__get_headers(headers),
            )
            req.raise_for_status()
            partial_response = req.json()
            if not partial_response.get("next"):
                stop = True
            response["results"].extend(partial_response["results"])
            response["count"] += partial_response["count"]
            params["skip"] += 100
        return response

    def _get_exif_for_mediafile(self, mediafile):
        artist, copyrights = [], []
        if photographer := get_item_metadata_value(mediafile, "photographer"):
            artist.append(f"photographer: {photographer}")
        if source := get_item_metadata_value(mediafile, "source"):
            artist.append(f"source: {source}")
        if copyright := get_item_metadata_value(mediafile, "copyright"):
            copyrights.append(f"rightsholder: {copyright}")
        if rights := get_item_metadata_value(mediafile, "rights"):
            copyrights.append(f"license: {rights}")
        if artist:
            artist = ", ".join(artist)
        if copyrights:
            copyrights = ", ".join(copyrights)
        return artist, copyrights

    def _get_file(self, url, output, headers=None, max_retries=5):
        retries = 0
        base_headers = self.__get_headers(headers) or {}

        while retries <= max_retries:
            try:
                req_headers = base_headers.copy()
                current_bytes = output.tell()
                if current_bytes > 0:
                    req_headers["Range"] = f"bytes={current_bytes}-"

                with requests.get(url, headers=req_headers, stream=True) as req:
                    if req.status_code not in (200, 206):
                        req.raise_for_status()

                    if req.status_code == 200 and current_bytes > 0:
                        output.seek(0)
                        output.truncate(0)

                    shutil.copyfileobj(req.raw, output)

                return

            except (
                IncompleteRead,
                ChunkedEncodingError,
                ConnectionError,
                ProtocolError,
            ) as e:
                retries += 1
                if retries > max_retries:
                    raise FileDownloadRetryExhausted(
                        url=url, retries=max_retries, exception=e
                    ) from e

                time.sleep(2**retries)
                app.logger.warning(
                    f"Network drop detected. Resuming download... (Attempt {retries}/{max_retries})"
                )

    def __get_headers(self, headers=None):
        if headers and isinstance(headers, dict):
            return {**self.headers, **(headers)}
        return self.headers

    def __get_mediafile(self, mediafile_id, headers=None) -> MediafileEntity:
        mediafiles_url = f"{self.collection_api_url}/mediafiles/{mediafile_id}"
        req = requests.get(
            mediafiles_url,
            headers=self.__get_headers(headers),
        )
        req.raise_for_status()
        return req.json()

    def _get_mediafile_download_link(self, mediafile, headers=None, user_email=None):

        mediafile_id = get_raw_id(mediafile)

        mediafile = self.__get_mediafile(mediafile_id)
        app.logger.debug(
            f"Mediafile {mediafile_id} raw location: {mediafile.get('original_file_location')}"
        )
        external_download_url = mediafile.get("original_file_location")
        return self.__parse_storage_api_url(external_download_url, user_email)

    def __parse_storage_api_url(
        self, incoming_url: str, user_email: str | None = None
    ) -> str:

        app.logger.debug(f"Incoming url: {incoming_url}")
        parsed_incoming_url = urlparse(incoming_url)
        parsed_internal = urlparse(self.storage_api_url)
        tail_path = parsed_incoming_url.path.removeprefix("/storage/v1").lstrip("/")
        new_path = posixpath.join(parsed_internal.path, tail_path)
        query_params = parse_qsl(parsed_incoming_url.query)
        if user_email:
            query_params.append(("user_email", user_email))
        new_query = urlencode(query_params)

        return urlunparse(
            (
                parsed_internal.scheme,
                parsed_internal.netloc,
                new_path,  # generally should be  /download-with-ticket/<filename> if using internal urls, or /storage/v1 if using external
                parsed_incoming_url.params,  # generally we don't support params, but I think it's in theory used for cantaloupe when requesting a specific frame?
                new_query,  # ticket_id=...&user_email=...
                parsed_incoming_url.fragment,
            )
        )

    def __get_zip_upload_link(
        self,
        entity_id,
        zip_filename,
        headers=None,
        user_email=None,
    ):
        if not headers:
            headers = {}
        mediafile = {
            "filename": zip_filename,
            "technical_origin": "download",
            "metadata": [],
            "relation_properties": {"is_downloadset": True},
        }
        url = f"{self.collection_api_url}/entities/{entity_id}/mediafiles"
        headers = {"Accept": "text/uri-list", **headers}
        req = requests.post(url, json=mediafile, headers=headers)
        if req.status_code not in (200, 201):
            req.raise_for_status()
        upload_url = req.text.strip().replace('"', "")
        return self.__parse_storage_api_url(upload_url)

    def __patch_mediafile(self, mediafile, payload, headers):
        req = requests.patch(
            f"{self.collection_api_url}/mediafiles/{get_raw_id(mediafile)}",
            json=payload,
            headers=self.__get_headers(headers),
        )
        if req.status_code not in (200, 201, 204):
            req.raise_for_status()

    def __set_download_entity_progress(
        self,
        download_entity_id,
        progress,
        headers=None,
    ):
        payload = [
            {
                "key": "status",
                "value": progress,
            },
        ]
        req = requests.patch(
            f"{self.collection_api_url}/entities/{download_entity_id}/metadata",
            json=payload,
            headers=self.__get_headers(headers),
        )
        if req.status_code != 200:
            app.logger.warning(
                f"Failed report progress on download entity, status code: {req.status_code}",
            )

    def __upload_mediafile(
        self,
        file_name,
        file_bytes,
        headers=None,
        master_entity_id=None,
    ):
        req = requests.post(
            f"{self.collection_api_url}/mediafiles",
            json={"filename": file_name},
            headers={"Accept": "text/uri-list", **self.__get_headers(headers)},
        )
        if req.status_code != 201:
            req.raise_for_status()
        upload_link = req.text.strip()
        if master_entity_id:
            mediafile_id = parse_qs(urlparse(upload_link).query).get("id", [])[0]
            req = requests.post(
                f"{self.collection_api_url}/entities/{master_entity_id}/relations",
                json=[{"key": mediafile_id, "type": "hasMediafile"}],
                headers=self.__get_headers(headers),
            )
            if req.status_code != 201:
                requests.delete(
                    f"{self.collection_api_url}/mediafiles/{mediafile_id}",
                    headers=self.__get_headers(headers),
                )
                req.raise_for_status()
        req = requests.post(
            upload_link,
            data=file_bytes,
            headers=self.__get_headers(headers),
        )
        if req.status_code != 201:
            req.raise_for_status()

    def _upload_transcode(
        self,
        mediafile,
        file_name,
        file_bytes,
        headers=None,
        parent_job_id=None,
        ignore_duplicate_check=False,
    ):
        req = requests.post(
            f"{self.collection_api_url}/tickets",
            json={"filename": file_name},
            headers=self.__get_headers(headers),
        )
        if req.status_code != 201:
            req.raise_for_status()
        ticket_id = req.text.strip().replace('"', "")
        storage_url = f"{self.storage_api_url}/upload/transcode?id={get_raw_id(mediafile)}&ticket_id={ticket_id}&ignore_duplicate_check={ignore_duplicate_check}"
        if parent_job_id:
            storage_url += f"&parent_job_id={parent_job_id}"
        app.logger.debug(f"Uploading with {storage_url}")
        req = requests.post(
            storage_url,
            data=file_bytes,
            headers=self.__get_headers(headers),
        )
        if req.status_code != 201:
            req.raise_for_status()

    @retry((NotFoundException), tries=3, delay=2)
    def __make_upload_zip_request(self, zip_upload_link, zip):

        req = requests.post(zip_upload_link, data=zip)
        if req.status_code == 404:
            raise NotFoundException
        return req

    def __upload_zip_to_download_entity(
        self,
        download_entity_id,
        zip_location: Path,
        headers=None,
        user_email=None,
    ):
        """Add zip to download entity and upload to S3
        Also deletes the zip from the filesystem
        """
        app.logger.debug(f"Starting zip upload for {download_entity_id}.")
        with zip_location.open("rb") as zip:
            zip_upload_link = self.__get_zip_upload_link(
                download_entity_id,
                zip_location.name,
                headers,
                user_email=user_email,
            )
            app.logger.debug(f"received zip_upload_link {zip_upload_link}\n\n")
            req = self.__make_upload_zip_request(zip_upload_link, zip)
            if req.status_code != 201:
                app.logger.warning(
                    f"Failed to upload zip to download entity, status code: {req.status_code}",
                )
                return
            zip_location.unlink()

    def add_width_height(self, mediafile, read_location: Path, headers=None):
        if "image/" in mediafile["mimetype"]:
            with Image.open(str(read_location)) as img:
                data = {"img_width": img.width, "img_height": img.height}
        else:
            info = Converter().probe(str(read_location))
            data = {
                "img_width": info.video.video_width,
                "img_height": info.video.video_height,
            }
        if not data["img_width"] or not data["img_height"]:
            raise GetWidthHeightException(mediafile)
        self.__patch_mediafile(mediafile, data, headers)

    def create_zip(self, request_body, headers=None, user_email=None):
        if download_entity_id := request_body.get("download_entity_id"):
            self.__set_download_entity_progress(
                download_entity_id,
                "In Progress",
                headers,
            )
        basic_csv = bool(request_body.get("basic_csv"))
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            datetime_string = datetime.now(ZoneInfo("Europe/Brussels")).strftime(
                "%Y-%m-%d_%H-%M-%S",
            )
            download_entity_title = request_body.get("download_entity_title")
            zip_location = (
                temp_dir_path / f"{download_entity_title}-{datetime_string}.zip"
            )
            app.logger.info(
                f"Starting zip creation for {download_entity_id} in dir {zip_location}."
            )
            with ZipFile(zip_location, "w") as zip:
                try:
                    mediafiles_for_entity = self.__add_entities_to_zip(
                        zip,
                        temp_dir_path,
                        request_body.get("entities", []),
                        headers,
                        user_email=user_email,
                    )
                    app.logger.debug(
                        f"Finished adding entities for {download_entity_id}."
                    )
                except:
                    self.__set_download_entity_progress(
                        download_entity_id, "Failed", headers
                    )
                    raise
                try:
                    self.__add_mediafiles_to_zip(
                        zip,
                        temp_dir_path,
                        request_body.get("mediafiles", []),
                        headers,
                        user_email=user_email,
                    )
                    app.logger.debug(
                        f"Finished adding mediafiles for {download_entity_id}."
                    )
                except:
                    self.__set_download_entity_progress(
                        download_entity_id, "Failed", headers
                    )
                    raise
                object_ids = {
                    "entities": request_body.get("entities", []),
                    "mediafiles": list(
                        set(
                            request_body.get("mediafiles", []) + mediafiles_for_entity,
                        ),
                    ),
                }
                if basic_csv:
                    try:
                        for object_type, csv_fields_definition_field in {
                            "entities": "csv_entity_columns",
                            "mediafiles": "csv_mediafile_columns",
                        }.items():
                            self.__add_objects_csv_to_zip(
                                zip,
                                temp_dir_path,
                                object_ids.get(object_type),
                                object_type,
                                request_body.get(csv_fields_definition_field, []),
                                headers,
                            )
                        app.logger.debug(f"Added csvs for {download_entity_id}.")
                    except:
                        self.__set_download_entity_progress(
                            download_entity_id, "Failed", headers
                        )
                        raise
            if download_entity_id:
                try:
                    self.__upload_zip_to_download_entity(
                        download_entity_id,
                        zip_location,
                        headers,
                        user_email=user_email,
                    )
                    self.__set_download_entity_progress(
                        download_entity_id, "Finished", headers
                    )
                except Exception:  # noqa: BLE001
                    self.__set_download_entity_progress(
                        download_entity_id, "Failed", headers
                    )

    def transcode(
        self,
        mediafile: MediafileEntity,
        operation_name: str,
        headers: dict | None = None,
        parent_job_id: str | None = None,
        user_email: str | None = None,
        ignore_duplicate_check: bool = False,
    ): ...

    def transcode_multiple_mediafiles(
        self,
        mediafiles,
        operation_name,
        headers=None,
        master_entity_id=None,
        user_email=None,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            write_location = temp_dir_path / f"{uuid4()}.{operation_name}"
            operation = {
                "pdf": {
                    "func": self.transcode_to_pdf,
                    "args": [mediafiles, temp_dir_path, write_location],
                },
            }.get(operation_name)
            if not operation:
                raise UnsupportedOperationException(operation_name)
            for mediafile in mediafiles:
                read_location = temp_dir_path / cast(str, mediafile["filename"])
                with read_location.open("wb") as input_file:
                    self._get_file(
                        self._get_mediafile_download_link(
                            mediafile,
                            headers,
                            user_email=user_email,
                        ),
                        input_file,
                        headers,
                    )
            operation["func"](*operation["args"])  # ty:ignore[call-non-callable, not-iterable]
            if operation.get("upload", True):
                with write_location.open("rb") as output_file:
                    self.__upload_mediafile(
                        write_location.name,
                        output_file,
                        headers,
                        master_entity_id,
                    )

    def transcode_to_pdf(self, mediafiles, read_location: Path, write_location: Path):
        images = [
            Image.open(f"{read_location / f.get('filename')}") for f in mediafiles
        ]
        images[0].save(
            write_location,
            "PDF",
            resolution=100.0,
            save_all=True,
            append_images=images[1:],
        )

    def get_filepaths(
        self, mediafile: MediafileEntity, temp_dir_name: str, operation_name
    ) -> tuple[Path, Path]:
        temp_dir_path = Path(temp_dir_name)
        original_filename_as_path = Path(mediafile["original_filename"])
        download_location = temp_dir_path / mediafile["filename"]
        write_location = (
            temp_dir_path
            / f"{original_filename_as_path.parent / original_filename_as_path.stem}.{operation_name}"
        )

        return download_location, write_location

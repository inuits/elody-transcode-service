import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from math import floor, sqrt
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse
from uuid import uuid4
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import app
import requests
from converter import Converter
from elody.exceptions import NotFoundException
from PIL import ExifTags, Image, ImageOps, TiffImagePlugin
from requests.exceptions import ChunkedEncodingError, ConnectionError
from retry import retry
from urllib3.exceptions import IncompleteRead, ProtocolError

Image.MAX_IMAGE_PIXELS = None


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class Transcoder(metaclass=Singleton):
    def __init__(self):
        self.collection_api_url = os.getenv("COLLECTION_API_URL")
        self.csv_exporter_enabled = os.getenv("CSV_EXPORTER_ENABLED", False) in {
            "true",
            "True",
            1,
        }
        self.csv_exporter_url = os.getenv("CSV_EXPORTER_URL", None)
        self.headers = {
            "Authorization": f"Bearer {os.getenv('STATIC_JWT')}",
            "X-From-Service": "transcode-service",
        }
        self.storage_api_url = os.getenv("STORAGE_API_URL")
        self.zip_working_dir = os.getenv("ZIP_WORKING_DIR", "/app")

    def __add_artist_and_copyright_to_exif(self, exif, artist, copyrights):
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
            entity_identifier = self.__get_entity_identifier(entity)
            entity_mediafiles = self.__get_entity_mediafiles(entity_id, headers)
            for mediafile in entity_mediafiles.get("results", []):
                mediafile_ids.append(self.__get_raw_id(mediafile))
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
            self.__get_file(
                self.__get_mediafile_download_link(
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
                params={"order_by": "title", "limit": len(object_ids)},
                json={
                    "ids": object_ids,
                    "fields": fields,
                    "exclude_non_editable_fields": True,
                    "type": object_type_mapper[object_type],
                },
                headers=self.__get_headers(
                    {
                        **{"Accept": "text/csv", "Content-Type": "application/json"},
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
                headers=self.__get_headers({**{"Accept": "text/csv"}, **headers}),
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
        if req.status_code != 200:
            raise Exception(
                f"Could not get entity  from {entity_url}\n" + req.text.strip(),
            )
        return req.json()

    # TODO: We should move this to the elody-sdk  # noqa: FIX002
    @staticmethod
    def __parse_filename_unfriendly_string(
        input: str | None,
        *,
        replace_char="_",
    ) -> str | None:
        if input is None:
            return None

        return re.sub(r'[<>:"/\\|?*]|^\.|\.$', replace_char, input)

    def __get_entity_identifier(self, entity):
        return (
            self.__parse_filename_unfriendly_string(entity.get("id", None))
            or entity["_id"]
        )

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
            if req.status_code != 200:
                raise Exception(
                    f"Could not get entity mediafiles from {entity_mediafiles_url}\n"
                    + req.text.strip(),
                )
            partial_response = req.json()
            if not partial_response.get("next"):
                stop = True
            response["results"].extend(partial_response["results"])
            response["count"] += partial_response["count"]
            params["skip"] += 100
        return response

    def __get_exif_for_mediafile(self, mediafile):
        artist, copyrights = [], []
        if photographer := self.__get_item_metadata_value(mediafile, "photographer"):
            artist.append(f"photographer: {photographer}")
        if source := self.__get_item_metadata_value(mediafile, "source"):
            artist.append(f"source: {source}")
        if copyright := self.__get_item_metadata_value(mediafile, "copyright"):
            copyrights.append(f"rightsholder: {copyright}")
        if rights := self.__get_item_metadata_value(mediafile, "rights"):
            copyrights.append(f"license: {rights}")
        if artist:
            artist = ", ".join(artist)
        if copyrights:
            copyrights = ", ".join(copyrights)
        return artist, copyrights

    def __get_file(self, url, output, headers=None, max_retries=5):
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
                        raise Exception(
                            f"Could not get file from {url}\nStatus: {req.status_code}\n{req.text.strip()}"
                        )

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
                    raise Exception(
                        f"Failed to fully download {url} after {max_retries} retries. Last error: {e}"
                    ) from e

                time.sleep(2**retries)
                app.logger.warning(
                    f"Network drop detected. Resuming download... (Attempt {retries}/{max_retries})"
                )

    def __get_headers(self, headers=None):
        if headers and isinstance(headers, dict):
            return {**self.headers, **(headers)}
        return self.headers

    def __get_item_metadata_value(self, item, key):
        for entry in item.get("metadata", []):
            if entry["key"] == key:
                return entry["value"]
        return None

    def __get_mediafile(self, mediafile_id, headers=None):
        mediafiles_url = f"{self.collection_api_url}/mediafiles/{mediafile_id}"
        req = requests.get(
            mediafiles_url,
            headers=self.__get_headers(headers),
        )
        if req.status_code != 200:
            raise Exception(
                f"Could not get mediafile details from {mediafiles_url}\n"
                + req.text.strip(),
            )
        req.raise_for_status()
        return req.json()

    def __get_mediafile_download_link(self, mediafile, headers=None, user_email=None):
        mediafile = self.__get_mediafile(self.__get_raw_id(mediafile))
        app.logger.debug(
            f"Mediafile {self.__get_raw_id(mediafile)} raw location: {mediafile.get('original_file_location')}"
        )
        parsed_uri = urlparse(mediafile.get("original_file_location"))

        user_email_parameter = f"&user_email={user_email}" if user_email else ""
        return f"{self.storage_api_url.replace('/storage/v1', '')}{parsed_uri.path}?{parsed_uri.query}{user_email_parameter}"  # ty:ignore[unresolved-attribute]

    def __get_raw_id(self, item):
        return item.get("_key", item["_id"])

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
        headers = {**{"Accept": "text/uri-list"}, **headers}
        req = requests.post(url, json=mediafile, headers=headers)
        if req.status_code not in (200, 201):
            raise Exception(req.text.strip())
        upload_url = req.text.strip().replace('"', "")
        parsed = urlparse(upload_url)
        parsed_path = parsed.path
        parsed_path.replace("/storage/v1/", "")
        internal_base = self.storage_api_url.rstrip("/")
        query = f"?{parsed.query}" if parsed.query else ""
        return f"{internal_base}{parsed_path}{query}&user_email={user_email}"

    def __patch_mediafile(self, mediafile, payload, headers):
        req = requests.patch(
            f"{self.collection_api_url}/mediafiles/{self.__get_raw_id(mediafile)}",
            json=payload,
            headers=self.__get_headers(headers),
        )
        if req.status_code not in (200, 201, 204):
            raise Exception(req.text.strip())

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
            raise Exception(req.text.strip())
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
                raise Exception(req.text.strip())
        req = requests.post(
            upload_link,
            data=file_bytes,
            headers=self.__get_headers(headers),
        )
        if req.status_code != 201:
            raise Exception(req.text.strip())

    def __upload_transcode(
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
            raise Exception(req.text.strip())
        ticket_id = req.text.strip().replace('"', "")
        storage_url = f"{self.storage_api_url}/upload/transcode?id={self.__get_raw_id(mediafile)}&ticket_id={ticket_id}&ignore_duplicate_check={ignore_duplicate_check}"
        if parent_job_id:
            storage_url += f"&parent_job_id={parent_job_id}"
        app.logger.debug(f"Uploading with {storage_url}")
        req = requests.post(
            storage_url,
            data=file_bytes,
            headers=self.__get_headers(headers),
        )
        if req.status_code != 201:
            raise Exception(req.text.strip())

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
        app.logger.info(f"Starting zip upload for {download_entity_id}.")
        with zip_location.open("rb") as zip:
            zip_upload_link = self.__get_zip_upload_link(
                download_entity_id,
                zip_location.name,
                headers,
                user_email=user_email,
            )
            app.logger.info(f"received zip_upload_link {zip_upload_link}\n\n")
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
            raise Exception("Could not get width and/or height")
        self.__patch_mediafile(mediafile, data, headers)

    def create_zip(self, request_body, headers=None, user_email=None):
        if download_entity_id := request_body.get("download_entity_id"):
            self.__set_download_entity_progress(
                download_entity_id,
                "In Progress",
                headers,
            )
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
                except Exception:
                    self.__set_download_entity_progress(
                        download_entity_id, "Failed", headers
                    )

    def transcode(
        self,
        mediafile,
        operation_name,
        headers=None,
        parent_job_id=None,
        user_email=None,
        ignore_duplicate_check=False,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            original_filename_as_path = Path(mediafile["original_filename"])
            read_location = temp_dir_path / cast(str, mediafile["filename"])
            write_location = (
                temp_dir_path
                / f"{original_filename_as_path.parent / original_filename_as_path.stem}.{operation_name}"
            )
            operation = {
                "jpg": {
                    "func": self.transcode_to_jpeg,
                    "args": [mediafile, read_location, write_location, headers],
                },
                "mp3": {
                    "func": self.transcode_to_mp3,
                    "args": [read_location, write_location],
                },
                "mp4": {
                    "func": self.transcode_to_mp4,
                    "args": [mediafile, read_location, write_location, headers],
                },
            }.get(operation_name)
            if not operation:
                raise Exception(f"Operation {operation_name} not supported")
            with read_location.open("wb") as input_file:
                app.logger.info("Starting download of file")
                self.__get_file(
                    self.__get_mediafile_download_link(
                        mediafile,
                        headers,
                        user_email=user_email,
                    ),
                    input_file,
                    headers,
                )
                app.logger.info("Finished download of file")
            operation["func"](*operation["args"])  # ty:ignore[call-non-callable, not-iterable]
            if operation.get("upload", True):
                with write_location.open("rb") as output_file:
                    self.__upload_transcode(
                        mediafile,
                        write_location.name,
                        output_file,
                        headers,
                        parent_job_id,
                        ignore_duplicate_check=ignore_duplicate_check,
                    )

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
                raise Exception(f"Operation {operation_name} not supported")
            for mediafile in mediafiles:
                read_location = temp_dir_path / cast(str, mediafile["filename"])
                with read_location.open("wb") as input_file:
                    self.__get_file(
                        self.__get_mediafile_download_link(
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

    def transcode_resize(self, src_imag_size: tuple, max_size: int) -> bool | tuple:
        """
        If the transcode has a total pixels <= max_size**2 it is fine, and we should not resize
        Otherwise, to get to max pixels we need to multiply total_pixels * max_pixels/total_pixels
        This means we need to multiply each dimension of the image by the square_root

        Let's say max = 200 -> max_pixels = 40000, and we have an image of 400*400 = 160000.
        40000 / 160000 = 1/4
        this means we have to multiply by sqrt(1/4) = 1/2 -> (200,200)
        """
        max_pixels = max_size**2
        total_pixels = src_imag_size[0] * src_imag_size[1]
        if total_pixels <= max_pixels:
            return False
        scale_factor = sqrt(max_pixels / total_pixels)
        return (
            floor(src_imag_size[0] * scale_factor),
            floor(src_imag_size[1] * scale_factor),
        )

    def transcode_to_jpeg(self, mediafile, read_location, write_location, headers=None):
        self.add_width_height(mediafile, read_location, headers)
        MAX_DIMENSION = 4000
        with Image.open(read_location) as src_img:
            exif = src_img.getexif()
            exif.pop(TiffImagePlugin.STRIPOFFSETS, None)
            artist, copyrights = self.__get_exif_for_mediafile(mediafile)
            self.__add_artist_and_copyright_to_exif(exif, artist, copyrights)

            if src_img.mode == "P" and src_img.format == "TIFF":
                colormap = src_img.tag_v2.get(320)
                if colormap and max(colormap) <= 255:
                    app.logger.warning(
                        "Detected malformed 8-bit TIFF ColorMap. Patching..."
                    )
                    num_colors = len(colormap) // 3
                    fixed_palette = []
                    for i in range(num_colors):
                        r = colormap[i]
                        g = colormap[i + num_colors]
                        b = colormap[i + 2 * num_colors]
                        fixed_palette.extend([r, g, b])
                    src_img.putpalette(fixed_palette)

            if src_img.mode in ("I", "F", "I;16", "I;16B"):
                app.logger.warning(f"Normalizing high-depth mode: {src_img.mode}")
                min_val, max_val = src_img.getextrema()
                if max_val > min_val:
                    scale = 255.0 / (max_val - min_val)
                    src_img = src_img.point(lambda i: (i - min_val) * scale).convert(
                        "L"
                    )
                else:
                    src_img = src_img.convert("L")

            if src_img.mode == "P":
                if "transparency" in src_img.info:
                    src_img = src_img.convert("RGBA")
                else:
                    src_img = src_img.convert("RGB")

            if src_img.mode in ("RGBA", "LA"):
                background = Image.new("RGB", src_img.size, (255, 255, 255))
                background.paste(src_img, mask=src_img.split()[-1])
                src_img = background

            ImageOps.exif_transpose(src_img, in_place=True)

            if resized_size := self.transcode_resize(src_img.size, MAX_DIMENSION):
                src_img.thumbnail(resized_size, Image.Resampling.LANCZOS)
            with src_img.convert("RGB") as dst_img:
                try:
                    dst_img.save(
                        write_location,
                        quality=75,
                        optimize=True,
                        progressive=True,
                        exif=exif,
                    )
                except Exception as ex:
                    exif.clear()
                    self.__add_artist_and_copyright_to_exif(exif, artist, copyrights)
                    dst_img.save(
                        write_location,
                        quality=75,
                        optimize=True,
                        progressive=True,
                        exif=exif,
                    )
                    app.logger.info(f"First conversion failed with: {ex}")

    def transcode_to_mp3(self, read_location: Path, write_location: Path):
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(read_location), str(write_location)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            app.logger.debug("MP3 transcode finished")

        except subprocess.CalledProcessError as e:
            app.logger.error(f"FFmpeg failed with exit code {e.returncode}")
            app.logger.error(f"FFmpeg error log:\n{e.stderr}")

            raise

    def transcode_to_mp4(
        self, mediafile, read_location: Path, write_location: Path, headers=None
    ):
        self.add_width_height(mediafile, read_location, headers)

        c = Converter()
        info = c.probe(str(read_location))
        opts = {
            "format": "mp4",
            "video": {
                "codec": "h264",
                "width": info.video.video_width,
                "height": info.video.video_height,
                "fps": info.video.video_fps,
                "ffmpeg_skin_opts": "-movflags +faststart",
            },
        }
        if info.audio:
            AAC_SUPPORTED_SAMPLERATES = [
                96000,
                88200,
                64000,
                48000,
                44100,
                32000,
                24000,
                22050,
                16000,
                12000,
                11025,
                8000,
                7350,
            ]
            source_rate = info.audio.audio_samplerate
            closest_rate = min(
                AAC_SUPPORTED_SAMPLERATES,
                key=lambda x: abs(x - source_rate),
            )

            opts["audio"] = {
                "codec": "aac",
                "samplerate": closest_rate,
                "channels": info.audio.audio_channels,
            }
        for _ in c.convert(str(read_location), str(write_location), opts, timeout=0):
            pass

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

import app
import os
import pydub
import requests
import shutil
import tempfile

from converter import Converter
from datetime import datetime
from PIL import ExifTags, Image, ImageOps, TiffImagePlugin
from urllib.parse import parse_qs, urlparse
from uuid import uuid4
from zipfile import ZipFile

Image.MAX_IMAGE_PIXELS = None


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class Transcoder(metaclass=Singleton):
    def __init__(self):
        self.collection_api_url = os.getenv("COLLECTION_API_URL")
        self.headers = {"Authorization": f'Bearer {os.getenv("STATIC_JWT")}'}
        self.storage_api_url = os.getenv("STORAGE_API_URL")
        self.zip_working_dir = os.getenv("ZIP_WORKING_DIR", "/app")

    def __add_artist_and_copyright_to_exif(self, exif, artist, copyrights):
        if artist:
            exif[ExifTags.Base.Artist] = artist
        if copyrights:
            exif[ExifTags.Base.Copyright] = copyrights

    def __add_entities_to_zip(
        self, zipfile, working_dir, entity_ids, headers=None, user_email=None
    ):
        mediafile_ids = list()
        for entity_id in entity_ids:
            entity_mediafiles = self.__get_entity_mediafiles(entity_id, headers)
            for mediafile in entity_mediafiles.get("results", list()):
                mediafile_ids.append(self.__get_raw_id(mediafile))
                self.__add_single_file_to_zip(
                    zipfile,
                    working_dir,
                    mediafile,
                    headers,
                    entity_id,
                    user_email=user_email,
                )
        return mediafile_ids

    def __add_mediafiles_to_zip(
        self, zipfile, working_dir, mediafile_ids, headers=None, user_email=None
    ):
        for mediafile_id in mediafile_ids:
            mediafile = self.__get_mediafile(mediafile_id, headers)
            self.__add_single_file_to_zip(
                zipfile, working_dir, mediafile, headers, user_email=user_email
            )
        return mediafile_ids

    def __add_objects_csv_to_zip(
        self, zipfile, working_dir, object_ids, object_type, fields=None, headers=None
    ):
        if csv_for_objects := self.__get_csv_for_objects(
            object_ids, object_type, fields, headers
        ):
            objects_csv_path = os.path.join(working_dir, f"{object_type}.csv")
            with open(objects_csv_path, "w") as objects_csv:
                objects_csv.write(csv_for_objects)
            zipfile.write(objects_csv_path, f"{object_type}.csv")

    def __add_single_file_to_zip(
        self,
        zipfile,
        working_dir,
        mediafile,
        headers=None,
        destination_path="",
        user_email=None,
    ):
        filename = mediafile["original_filename"]
        read_location = os.path.join(working_dir, filename)
        with open(read_location, "wb") as input_file:
            self.__get_file(
                self.__get_mediafile_download_link(
                    mediafile, headers, user_email=user_email
                ),
                input_file,
                headers,
            )
        zipfile.write(read_location, os.path.join(destination_path, filename))

    def __get_csv_for_objects(
        self, object_ids, object_type="entities", fields=None, headers=None
    ):
        if not object_ids:
            return
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
                f"Could not fetch CSV for {object_type}, status code: {req.status_code}"
            )
            return
        return req.text

    def __get_entity_mediafiles(self, entity_id, headers=None):
        entity_mediafiles_url = (
            f"{self.collection_api_url}/entities/{entity_id}/mediafiles"
        )
        req = requests.get(
            entity_mediafiles_url,
            headers=self.__get_headers(headers),
        )
        if req.status_code != 200:
            raise Exception(
                f"Could not get entity mediafiles from {entity_mediafiles_url}\n"
                + req.text.strip()
            )
        return req.json()

    def __get_exif_for_mediafile(self, mediafile):
        artist, copyrights = list(), list()
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

    def __get_file(self, url, output, headers=None):
        with requests.get(url, headers=self.__get_headers(headers), stream=True) as req:
            if req.status_code != 200:
                raise Exception(f"Could not get file from {url}\n" + req.text.strip())
            shutil.copyfileobj(req.raw, output)

    def __get_headers(self, headers=None):
        if headers and isinstance(headers, dict):
            return {**self.headers, **headers}
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
                + req.text.strip()
            )
        return req.json()

    def __get_mediafile_download_link(self, mediafile, headers=None, user_email=None):
        mediafile = self.__get_mediafile(self.__get_raw_id(mediafile))
        parsed_uri = urlparse(mediafile.get("original_file_location"))
        user_email_parameter = f"&user_email={user_email}" if user_email else ""
        return f"{self.storage_api_url.replace('/storage/v1', '')}{parsed_uri.path}?{parsed_uri.query}{user_email_parameter}"

    def __get_raw_id(self, item):
        return item.get("_key", item["_id"])

    def __get_zip_upload_link(
        self, entity_id, zip_filename, headers=None, user_email=None
    ):
        mediafile = {
            "filename": zip_filename,
            "technical_origin": "download",
            "metadata": list(),
            "relation_properties": {"is_downloadset": True},
        }
        url = f"{self.collection_api_url}/entities/{entity_id}/mediafiles"
        headers = {**{"Accept": "text/uri-list"}, **headers}
        req = requests.post(url, json=mediafile, headers=headers)
        return req.text.strip().replace('"', "") + f"&user_email={user_email}"

    def __patch_mediafile(self, mediafile, payload, headers):
        req = requests.patch(
            f"{self.collection_api_url}/mediafiles/{self.__get_raw_id(mediafile)}",
            json=payload,
            headers=self.__get_headers(headers),
        )
        if req.status_code not in (200, 201, 204):
            raise Exception(req.text.strip())

    def __set_download_entity_progress(
        self, download_entity_id, progress, headers=None
    ):
        payload = [
            {
                "key": "status",
                "value": progress,
            }
        ]
        req = requests.patch(
            f"{self.collection_api_url}/entities/{download_entity_id}/metadata",
            json=payload,
            headers=self.__get_headers(headers),
        )
        if req.status_code != 200:
            app.logger.info(
                f"Failed report progress on download entity, status code: {req.status_code}"
            )

    def __upload_mediafile(
        self, file_name, file_bytes, headers=None, master_entity_id=None
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
            mediafile_id = parse_qs(urlparse(upload_link).query).get("id", list())[0]
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
            files={"file": (file_name, file_bytes)},
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
        req = requests.post(
            storage_url,
            files={"file": (file_name, file_bytes)},
            headers=self.__get_headers(headers),
        )
        if req.status_code != 201:
            raise Exception(req.text.strip())

    def __upload_zip_to_download_entity(
        self, download_entity_id, zip_location, headers=None, user_email=None
    ):
        with open(zip_location, "rb") as zip:
            zip_upload_link = self.__get_zip_upload_link(
                download_entity_id,
                os.path.basename(zip_location),
                headers,
                user_email=user_email,
            )
            req = requests.post(zip_upload_link, files={"file": zip})
            if req.status_code != 201:
                app.logger.info(
                    f"Failed to upload zip to download entity, status code: {req.status_code}"
                )
                return
            os.remove(zip_location)

    def add_width_height(self, mediafile, read_location, headers=None):
        if "image/" in mediafile["mimetype"]:
            with Image.open(read_location) as img:
                data = {"img_width": img.width, "img_height": img.height}
        else:
            info = Converter().probe(read_location)
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
                download_entity_id, "In Progress", headers
            )
        zip_location = None
        with tempfile.TemporaryDirectory() as temp_dir:
            datetime_string = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            download_entity_title = request_body.get("download_entity_title")
            zip_location = os.path.join(
                self.zip_working_dir, f"{download_entity_title}-{datetime_string}.zip"
            )
            with ZipFile(zip_location, "w") as zip:
                mediafiles_for_entity = self.__add_entities_to_zip(
                    zip,
                    temp_dir,
                    request_body.get("entities", list()),
                    headers,
                    user_email=user_email,
                )
                self.__add_mediafiles_to_zip(
                    zip,
                    temp_dir,
                    request_body.get("mediafiles", list()),
                    headers,
                    user_email=user_email,
                )
                object_ids = {
                    "entities": request_body.get("entities", list()),
                    "mediafiles": list(
                        set(
                            request_body.get("mediafiles", list())
                            + mediafiles_for_entity
                        )
                    ),
                }
                for object_type, csv_fields_definition_field in {
                    "entities": "csv_entity_columns",
                    "mediafiles": "csv_mediafile_columns",
                }.items():
                    self.__add_objects_csv_to_zip(
                        zip,
                        temp_dir,
                        object_ids.get(object_type),
                        object_type,
                        request_body.get(csv_fields_definition_field, list()),
                        headers,
                    )
        if download_entity_id:
            self.__upload_zip_to_download_entity(
                download_entity_id, zip_location, headers, user_email=user_email
            )
            self.__set_download_entity_progress(download_entity_id, "Finished", headers)
        return zip_location

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
            read_location = os.path.join(temp_dir, mediafile["filename"])
            write_location = os.path.join(
                temp_dir,
                f'{os.path.splitext(mediafile["original_filename"])[0]}.{operation_name}',
            )
            operation = {
                "jpg": {
                    "func": self.transcode_to_jpeg,
                    "args": [mediafile, read_location, write_location],
                },
                "mp3": {
                    "func": self.transcode_to_mp3,
                    "args": [read_location, write_location],
                },
                "mp4": {
                    "func": self.transcode_to_mp4,
                    "args": [read_location, write_location],
                },
                "width_height": {
                    "func": self.add_width_height,
                    "args": [mediafile, read_location, headers],
                    "upload": False,
                },
            }.get(operation_name)
            if not operation:
                raise Exception(f"Operation {operation_name} not supported")
            with open(read_location, "wb") as input_file:
                self.__get_file(
                    self.__get_mediafile_download_link(
                        mediafile, headers, user_email=user_email
                    ),
                    input_file,
                    headers,
                )
            operation["func"](*operation["args"])
            if operation.get("upload", True):
                with open(write_location, "rb") as output_file:
                    self.__upload_transcode(
                        mediafile,
                        os.path.basename(write_location),
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
            write_location = os.path.join(
                temp_dir,
                f"{uuid4()}.{operation_name}",
            )
            operation = {
                "pdf": {
                    "func": self.transcode_to_pdf,
                    "args": [mediafiles, temp_dir, write_location],
                },
            }.get(operation_name)
            if not operation:
                raise Exception(f"Operation {operation_name} not supported")
            for mediafile in mediafiles:
                read_location = os.path.join(temp_dir, mediafile["filename"])
                with open(read_location, "wb") as input_file:
                    self.__get_file(
                        self.__get_mediafile_download_link(
                            mediafile, headers, user_email=user_email
                        ),
                        input_file,
                        headers,
                    )
            operation["func"](*operation["args"])
            if operation.get("upload", True):
                with open(write_location, "rb") as output_file:
                    self.__upload_mediafile(
                        os.path.basename(write_location),
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
        else:

            scale_factor = sqrt(max_pixels / total_pixels)
            return (
                floor(src_imag_size[0] * scale_factor),
                floor(src_imag_size[1] * scale_factor),
            )

    def transcode_to_jpeg(self, mediafile, read_location, write_location):
        MAX_DIMENSION = 4000
        with Image.open(read_location) as src_img:
            exif = src_img.getexif()
            exif.pop(TiffImagePlugin.STRIPOFFSETS, None)
            artist, copyrights = self.__get_exif_for_mediafile(mediafile)
            self.__add_artist_and_copyright_to_exif(exif, artist, copyrights)
            if src_img.mode == "I;16":
                src_img = src_img.point(lambda i: i * (1 / 255))
            ImageOps.exif_transpose(src_img, in_place=True)

            if resized_size := self.transcode_resize(src_img.size, MAX_DIMENSION):
                src_img.thumbnail(resized_size, Image.Resampling.LANCZOS)
            with src_img.convert("RGB") as dst_img:
                try:
                    dst_img.save(write_location, quality=75, optimize=True, progressive=True, exif=exif)
                except Exception as ex:
                    exif.clear()
                    self.__add_artist_and_copyright_to_exif(exif, artist, copyrights)
                    dst_img.save(write_location, quality=75, optimize=True, progressive=True, exif=exif)
                    app.logger.info(f"First conversion failed with: {ex}")

    def transcode_to_mp3(self, read_location, write_location):
        audio = pydub.AudioSegment.from_file(read_location)
        audio.export(write_location, format="mp3")

    def transcode_to_mp4(self, read_location, write_location):
        c = Converter()
        info = c.probe(read_location)
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
                AAC_SUPPORTED_SAMPLERATES, key=lambda x: abs(x - source_rate)
            )

            opts["audio"] = {
                "codec": "aac",
                "samplerate": closest_rate,
                "channels": info.audio.audio_channels,
            }
        for _ in c.convert(read_location, write_location, opts, timeout=0):
            pass

    def transcode_to_pdf(self, mediafiles, read_location, write_location):
        images = [
            Image.open(f"{os.path.join(read_location, f.get('filename'))}")
            for f in mediafiles
        ]
        images[0].save(
            write_location,
            "PDF",
            resolution=100.0,
            save_all=True,
            append_images=images[1:],
        )

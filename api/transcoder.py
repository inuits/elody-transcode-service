import io
import os
import pydub
import requests
import shutil
import tempfile

from converter import Converter
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = None


class Transcoder:
    def __init__(self, mediafile, url):
        self.collection_api_url = os.getenv("COLLECTION_API_URL")
        self.headers = {"Authorization": f'Bearer {os.getenv("STATIC_JWT")}'}
        self.mediafile = mediafile
        self.storage_api_url = os.getenv("STORAGE_API_URL")
        self.url = url

    def __add_video_width_height(self, file_path):
        info = Converter().probe(file_path)
        data = {
            "img_width": info.video.video_width,
            "img_height": info.video.video_height,
        }
        self.__patch_mediafile(data)

    def __get_exif_for_mediafile(self, mediafile):
        artist = f'source: {self.__get_item_metadata_value(mediafile, "source")}'
        if photographer := self.__get_item_metadata_value(mediafile, "photographer"):
            artist = f"photographer: {photographer}, {artist}"
        rights = f'license: {self.__get_item_metadata_value(mediafile, "rights")}'
        if copyrights := self.__get_item_metadata_value(mediafile, "copyright"):
            rights = f"rightsholder: {copyrights}, {rights}"
        return artist, rights

    def __get_file(self, output):
        with requests.get(self.url, headers=self.headers, stream=True) as req:
            if req.status_code != 200:
                raise Exception(req.text.strip())
            shutil.copyfileobj(req.raw, output)
        return output

    def __get_item_metadata_value(self, item, key):
        for entry in item["metadata"]:
            if entry["key"] == key:
                return entry["value"]
        return False

    def __get_raw_id(self, item):
        return item.get("_key", item["_id"])

    def __patch_mediafile(self, payload):
        req = requests.patch(
            f"{self.collection_api_url}/mediafiles/{self.__get_raw_id(self.mediafile)}",
            json=payload,
            headers=self.headers,
        )
        if req.status_code != 201:
            raise Exception(req.text.strip())

    def __transcode_to_mp3(self, temp_dir, read_location, output_filename):
        write_location = os.path.join(temp_dir, output_filename)
        audio = pydub.AudioSegment.from_file(read_location)
        audio.export(write_location, format="mp3")
        with open(write_location, "rb") as write_file:
            self.__upload_transcode(output_filename, write_file)

    def __transcode_to_mp4(self, temp_dir, file_path, output_filename):
        write_location = os.path.join(temp_dir, output_filename)
        c = Converter()
        info = c.probe(file_path)
        opts = {
            "format": "mp4",
            "video": {
                "codec": "h264",
                "width": info.video.video_width,
                "height": info.video.video_height,
                "fps": info.video.video_fps,
            },
        }
        if info.audio:
            opts["audio"] = {
                "codec": "aac",
                "samplerate": info.audio.audio_samplerate,
                "channels": info.audio.audio_channels,
            }
        for _ in c.convert(file_path, write_location, opts, timeout=0):
            pass
        with open(write_location, "rb") as output_file:
            self.__upload_transcode(output_filename, output_file)

    def __upload_transcode(self, file_name, file_bytes):
        req = requests.post(
            f"{self.storage_api_url}/upload/transcode?id={self.__get_raw_id(self.mediafile)}",
            files={"file": (file_name, file_bytes)},
            headers=self.headers,
        )
        if req.status_code != 201:
            raise Exception(req.text.strip())

    def add_image_width_height(self):
        with (
            self.__get_file(io.BytesIO()) as input_file,
            Image.open(input_file) as img,
        ):
            data = {"img_width": img.width, "img_height": img.height}
        if not data["img_width"] or not data["img_height"]:
            raise Exception("Could not get width and/or height")
        self.__patch_mediafile(data)

    def transcode_from_disk(self, video_width_height=False, mp3=False, mp4=False):
        with tempfile.TemporaryDirectory() as temp_dir:
            read_location = os.path.join(temp_dir, self.mediafile["filename"])
            with open(read_location, "wb") as input_file:
                self.__get_file(input_file)
            if video_width_height:
                self.__add_video_width_height(read_location)
            elif mp3:
                output_filename = (
                    f'{os.path.splitext(self.mediafile["original_filename"])[0]}.mp3'
                )
                self.__transcode_to_mp3(temp_dir, read_location, output_filename)
            elif mp4:
                output_filename = (
                    f'{os.path.splitext(self.mediafile["original_filename"])[0]}.mp4'
                )
                self.__transcode_to_mp4(temp_dir, read_location, output_filename)

    def transcode_to_jpeg(self):
        with (
            self.__get_file(io.BytesIO()) as input_file,
            Image.open(input_file) as src_img,
            ImageOps.exif_transpose(src_img).convert("RGB") as dst_img,
            io.BytesIO() as output_file,
        ):
            exif = dst_img.getexif()
            exif[0x013B], exif[0x8298] = self.__get_exif_for_mediafile(self.mediafile)
            dst_img.save(output_file, "jpeg", quality=95, exif=exif)
            output_file.seek(0)
            output_filename = (
                f'{os.path.splitext(self.mediafile["original_filename"])[0]}.jpg'
            )
            self.__upload_transcode(output_filename, output_file)

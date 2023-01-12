import io
import os
import pydub
import requests
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

    def __get_file(self):
        req = requests.get(self.url, headers=self.headers)
        if req.status_code != 200:
            raise Exception(req.json())
        return req.content

    def __patch_mediafile(self, payload):
        req = requests.patch(
            f'{self.collection_api_url}/mediafiles/{self.mediafile.get("_key", self.mediafile["_id"])}',
            json=payload,
            headers=self.headers,
        )
        if req.status_code != 201:
            raise Exception(req.json())

    def __upload_transcode(self, file_name, file_bytes):
        req = requests.post(
            f'{self.storage_api_url}/upload/transcode?id={self.mediafile["_key"]}',
            files={"file": (file_name, file_bytes)},
            headers=self.headers,
        )
        if req.status_code != 201:
            raise Exception(req.json())

    def add_image_width_height(self):
        with Image.open(io.BytesIO(self.__get_file())) as img:
            data = {"img_width": img.width, "img_height": img.height}
        if not data["img_width"] or not data["img_height"]:
            raise Exception("Could not get width and/or height")
        self.__patch_mediafile(data)

    def add_video_width_height(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            read_location = os.path.join(temp_dir, self.mediafile["filename"])
            with open(read_location, "wb") as read_file:
                read_file.write(self.__get_file())
            c = Converter()
            info = c.probe(read_location)
            data = {
                "img_width": info.video.video_width,
                "img_height": info.video.video_height,
            }
        self.__patch_mediafile(data)

    def transcode_to_jpeg(self):
        with Image.open(io.BytesIO(self.__get_file())) as img:
            out_img = ImageOps.exif_transpose(img).convert("RGB")
        new_bytes = io.BytesIO()
        out_img.save(new_bytes, "jpeg", quality=95)
        new_bytes.seek(0)
        file_name = f'{os.path.splitext(self.mediafile["original_filename"])[0]}.jpg'
        self.__upload_transcode(file_name, new_bytes)
        out_img.close()

    def transcode_to_mp3(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            read_location = os.path.join(temp_dir, self.mediafile["filename"])
            with open(read_location, "wb") as read_file:
                read_file.write(self.__get_file())
            new_file_name = (
                f'{os.path.splitext(self.mediafile["original_filename"])[0]}.mp3'
            )
            write_location = os.path.join(temp_dir, new_file_name)
            sound = pydub.AudioSegment.from_file(read_location)
            sound.export(write_location, format="mp3")
            with open(write_location, "rb") as write_file:
                self.__upload_transcode(new_file_name, write_file.read())

    def transcode_to_mp4(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            read_location = os.path.join(temp_dir, self.mediafile["filename"])
            with open(read_location, "wb") as read_file:
                read_file.write(self.__get_file())
            new_file_name = (
                f'{os.path.splitext(self.mediafile["original_filename"])[0]}.mp4'
            )
            write_location = os.path.join(temp_dir, new_file_name)
            c = Converter()
            info = c.probe(read_location)
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
            conv = c.convert(read_location, write_location, opts, timeout=0)
            for _ in conv:
                pass
            with open(write_location, "rb") as write_file:
                self.__upload_transcode(new_file_name, write_file.read())

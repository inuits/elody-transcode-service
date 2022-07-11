import app
import cv2
import io
import moviepy.editor as moviepy
import numpy
import os
import requests
import tempfile
import time

from PIL import Image

Image.MAX_IMAGE_PIXELS = None


class Transcoder:
    def __init__(self, mediafile, url):
        self.collection_api_url = os.getenv(
            "COLLECTION_API_URL", "http://collection-api:8000"
        )
        self.headers = {"Authorization": f'Bearer {os.getenv("STATIC_JWT", "None")}'}
        self.mediafile = mediafile
        self.storage_api_url = os.getenv("STORAGE_API_URL", "http://storage-api:8001")
        self.url = url

    def _get_file(self):
        req = requests.get(self.url, headers=self.headers)
        if req.status_code != 200:
            raise Exception(req.json())
        return req.content

    def _patch_mediafile(self, payload):
        req = requests.patch(
            f"{self.collection_api_url}/mediafiles/{self._get_raw_id(self.mediafile)}",
            json=payload,
            headers=self.headers,
        )
        if req.status_code != 201:
            raise Exception(req.json())

    def _process_file(self, file):
        src_np_arr = numpy.frombuffer(file, numpy.uint8)
        return cv2.imdecode(src_np_arr, cv2.IMREAD_COLOR)

    def _get_raw_id(self, item):
        return item["_key"] if "_key" in item else item["_id"]

    def _get_image_width_height_pil(self, image):
        try:
            img = Image.open(io.BytesIO(image))
            return img.width, img.height
        except:
            return None, None

    def _get_image_width_height_opencv(self, image):
        try:
            img = self._process_file(image)
            height = img.shape[0]
            width = img.shape[1]
            return width, height
        except:
            return None, None

    def add_image_width_height(self):
        image = self._get_file()
        width, height = self._get_image_width_height_opencv(image)
        if not width or not height:
            app.logger.error(
                "Failed to get width and/or height using OpenCV, trying PIL"
            )
            width, height = self._get_image_width_height_pil(image)
        if not width or not height:
            raise Exception("Could not get width and/or height")
        data = {"img_width": width, "img_height": height}
        self._patch_mediafile(data)

    def add_video_width_height(self):
        with tempfile.NamedTemporaryFile() as temp:
            temp.write(self._get_file())
            vcap = cv2.VideoCapture(temp.name)
            width = int(vcap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(vcap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            data = {"img_width": width, "img_height": height}
            self._patch_mediafile(data)

    def _upload_transcode(self, file_name, file_bytes):
        req = requests.post(
            f'{self.storage_api_url}/upload/transcode?id={self.mediafile["_key"]}',
            files={"file": (file_name, file_bytes)},
            headers=self.headers,
        )
        if req.status_code != 201:
            raise Exception(req.json())

    def _transcode_to_jpeg_opencv(self, original_file):
        opencv_img = self._process_file(original_file)
        retval, ret_np_arr = cv2.imencode(".jpg", opencv_img)
        return io.BytesIO(ret_np_arr.tobytes())

    def _transcode_to_jpeg_pil(self, original_file):
        img = Image.open(io.BytesIO(original_file))
        out_img = img.convert("RGB")
        new_bytes = io.BytesIO()
        out_img.save(new_bytes, "jpeg", quality=95)
        new_bytes.seek(0)
        return new_bytes

    def transcode_to_jpeg(self):
        original_file = self._get_file()
        try:
            file_bytes = self._transcode_to_jpeg_opencv(original_file)
        except:
            app.logger.error("Failed to transcode to jpeg using OpenCV, trying PIL")
            file_bytes = self._transcode_to_jpeg_pil(original_file)
        file_name = f'{os.path.splitext(self.mediafile["original_filename"])[0]}.jpg'
        self._upload_transcode(file_name, file_bytes)

    def transcode_to_mp4(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            read_location = os.path.join(temp_dir, self.mediafile["filename"])
            with open(read_location, "wb") as read_file:
                read_file.write(self._get_file())
            new_file_name = (
                f'{os.path.splitext(self.mediafile["original_filename"])[0]}.mp4'
            )
            write_location = os.path.join(temp_dir, new_file_name)
            with moviepy.VideoFileClip(read_location) as vfc:
                vfc.write_videofile(
                    write_location, temp_audiofile_path=temp_dir, logger=None, threads=4
                )
                time.sleep(60)
                with open(write_location, "rb") as write_file:
                    self._upload_transcode(new_file_name, write_file.read())

import cv2
import io
import numpy
import os
import requests


class Transcoder:
    def __init__(self, mediafile, url):
        self.collection_api_url = os.getenv(
            "COLLECTION_API_URL", "http://collection-api:8000"
        )
        self.headers = {"Authorization": f'Bearer {os.getenv("STATIC_JWT", "None")}'}
        self.mediafile = mediafile
        self.storage_api_url = os.getenv("STORAGE_API_URL", "http://storage-api:8001")
        self.url = url

    def _get_raw_id(self, item):
        return item["_key"] if "_key" in item else item["_id"]

    def _upload_transcode(self, file):
        req = requests.post(
            f'{self.storage_api_url}/upload/transcode?id={self.mediafile["_key"]}',
            files=file,
            headers=self.headers,
        )
        if req.status_code != 201:
            raise Exception(req.json())

    def _get_file(self):
        req = requests.get(self.url, headers=self.headers)
        if req.status_code != 200:
            raise Exception(req.json())
        return req

    def _process_file(self):
        req = self._get_file()
        src_np_arr = numpy.frombuffer(req.content, numpy.uint8)
        return cv2.imdecode(src_np_arr, cv2.IMREAD_COLOR)

    def add_pic_dimensions(self):
        opencv_img = self._process_file()
        data = {"img_height": opencv_img.shape[0], "img_width": opencv_img.shape[1]}
        req = requests.patch(
            f"{self.collection_api_url}/mediafiles/{self._get_raw_id(self.mediafile)}",
            json=data,
            headers=self.headers,
        )
        if req.status_code != 201:
            raise Exception(req.json())

    def transcode_to_jpeg(self):
        opencv_img = self._process_file()
        retval, ret_np_arr = cv2.imencode(".jpg", opencv_img)
        file = {"file": io.BytesIO(ret_np_arr.tobytes())}
        self._upload_transcode(file)

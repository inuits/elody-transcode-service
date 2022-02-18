import cv2
import io
import numpy
import os
import requests


class Transcoder:
    def __init__(self, mediafile, url):
        self.headers = {"Authorization": f'Bearer {os.getenv("STATIC_JWT", "None")}'}
        self.mediafile = mediafile
        self.storage_api_url = os.getenv("STORAGE_API_URL", "http://storage-api:8001")
        self.url = url

    def transcode_to_jpeg(self):
        req = requests.get(self.url, headers=self.headers)
        src_np_arr = numpy.frombuffer(req.content, numpy.uint8)
        opencv_img = cv2.imdecode(src_np_arr, cv2.IMREAD_COLOR)
        retval, ret_np_arr = cv2.imencode(".jpg", opencv_img)
        file = {"file": io.BytesIO(ret_np_arr.tobytes())}
        requests.post(
            f'{self.storage_api_url}/upload/transcode?id={self.mediafile["_key"]}',
            files=file,
            headers=self.headers,
        )

import cv2
import numpy
import os
import requests


class Transcoder:
    def __init__(self, file_location):
        self.file_location = file_location
        self.headers = {f'Authorization": "Bearer {os.getenv("STATIC_JWT", "None")}'}

    def _get_request(self, file_location):
        for i in range(3):
            try:
                req = requests.get(file_location, headers=self.headers)
                break
            except requests.exceptions.ConnectionError:
                continue
        if req.status_code != 200:
            raise Exception(f"GET to {file_location} with headers {req.headers} failed with {req.json()}")
        return req.json()

    def transcode_to_jpeg(self):
        img_bytes = self._get_request(self.file_location)
        numpy_array = numpy.frombuffer(img_bytes, numpy.uint8)
        opencv_img = cv2.imdecode(numpy_array, cv2.IMREAD_COLOR)
        transcoded_img_bytes = cv2.imencode(".jpg", opencv_img)
        # make sure transcoded img is uploaded

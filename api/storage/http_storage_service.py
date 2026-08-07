import shutil
import time
from logging import Logger
from os import getenv
from pathlib import Path

import requests
from elody.util import get_raw_id
from elody_types import MediafileEntity
from exceptions_transcoder.exceptions import FileDownloadRetryExhausted
from requests.exceptions import ChunkedEncodingError, ConnectionError
from urllib3.exceptions import IncompleteRead, ProtocolError


class HttpStorageService:
    def __init__(self, storage_api_url: str, collection_api_url: str, logger: Logger):
        self.storage_api_url = storage_api_url
        self.collection_api_url = collection_api_url
        self.session = requests.Session()
        self.headers = {
            "Authorization": f"Bearer {getenv('STATIC_JWT')}",
            "X-From-Service": "transcode-service",
        }
        self.logger = logger

    def __get_headers(self, headers=None):
        if headers and isinstance(headers, dict):
            return {**self.headers, **(headers)}
        return self.headers

    def __get_ticket_id(self, file_name: str, headers: dict | None = None) -> str:

        req = requests.post(
            f"{self.collection_api_url}/tickets",
            json={"filename": file_name},
            headers=self.__get_headers(headers),
        )
        if req.status_code != 201:
            req.raise_for_status()

        ticket_id = req.text.strip().replace('"', "")
        return ticket_id

    def get_file(
        self, url: str, output_path: Path, headers=None, max_retries=5
    ) -> None:
        retries = 0
        base_headers = self.__get_headers(headers) or {}

        with output_path.open("wb") as output:
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
                    self.logger.warning(
                        f"Network drop detected. Resuming download... (Attempt {retries}/{max_retries})"
                    )

    def upload_transcode(
        self,
        mediafile: MediafileEntity,
        file_name: str,
        file_path: Path,
        headers: dict | None = None,
        parent_job_id: str | None = None,
        ignore_duplicate_check=False,
    ):
        ticket_id = self.__get_ticket_id(file_name, headers)
        storage_url = f"{self.storage_api_url}/upload/transcode?id={get_raw_id(mediafile)}&ticket_id={ticket_id}&ignore_duplicate_check={ignore_duplicate_check}"
        if parent_job_id:
            storage_url += f"&parent_job_id={parent_job_id}"
        self.logger.debug(f"Uploading with {storage_url}")
        with file_path.open("rb") as file_bytes:
            req = requests.post(
                storage_url,
                data=file_bytes,
                headers=self.__get_headers(headers),
            )
            if req.status_code != 201:
                req.raise_for_status()

    def upload_thumbnail(
        self,
        mediafile: MediafileEntity,
        file_name: str,
        file_path: Path,
        headers: dict | None = None,
        parent_job_id: str | None = None,
        ignore_duplicate_check=False,
    ):
        ticket_id = self.__get_ticket_id(file_name, headers)
        storage_url = f"{self.storage_api_url}/upload/thumbnail?id={get_raw_id(mediafile)}&ticket_id={ticket_id}&ignore_duplicate_check={ignore_duplicate_check}"
        if parent_job_id:
            storage_url += f"&parent_job_id={parent_job_id}"
        self.logger.debug(f"Uploading with {storage_url}")
        with file_path.open("rb") as file_bytes:
            req = requests.post(
                storage_url,
                data=file_bytes,
                headers=self.__get_headers(headers),
            )
            if req.status_code != 201:
                req.raise_for_status()

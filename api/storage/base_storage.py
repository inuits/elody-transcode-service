from pathlib import Path
from typing import Protocol

from elody_types import MediafileEntity


class StorageService(Protocol):
    def get_file(
        self, url: str, output_path: Path, headers: dict | None = None
    ) -> None: ...

    def upload_transcode(
        self,
        mediafile: MediafileEntity,
        file_name: str,
        file_path: Path,
        headers: dict | None = None,
        parent_job_id: str | None = None,
        ignore_duplicate_check=False,
    ) -> None: ...

    # def upload_thumbnail(
    #     self,
    #     mediafile: MediafileEntity,
    #     file_name: str,
    #     file_path: Path,
    #     headers: dict | None = None,
    #     parent_job_id: str | None = None,
    #     ignore_duplicate_check=False,
    # ) -> None: ...

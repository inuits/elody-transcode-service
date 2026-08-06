import subprocess
import tempfile
from pathlib import Path

from app import app
from elody_types import MediafileEntity

from .transcoder import Transcoder


class MP3Transcoder(Transcoder, format_name="mp3"):
    def transcode(
        self,
        mediafile: MediafileEntity,
        operation_name: str,
        headers: dict | None = None,
        parent_job_id: str | None = None,
        user_email: str | None = None,
        ignore_duplicate_check: bool = False,
    ):

        with tempfile.TemporaryDirectory() as temp_dir:
            download_location, write_location = self.get_filepaths(
                mediafile, temp_dir, operation_name
            )
            app.logger.info("Starting download of file")
            self.storage.get_file(
                self._get_mediafile_download_link(
                    mediafile,
                    headers,
                    user_email=user_email,
                ),
                download_location,
                headers,
            )
            app.logger.info("Finished download of file")

            self.transcode_to_mp3(
                download_location,
                write_location,
            )
            self.storage.upload_transcode(
                mediafile,
                write_location.name,
                write_location,
                headers,
                parent_job_id,
                ignore_duplicate_check=ignore_duplicate_check,
            )

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

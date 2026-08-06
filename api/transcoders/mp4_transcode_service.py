import tempfile
from pathlib import Path

from app import app
from converter import Converter
from elody_types import MediafileEntity

from .transcoder import Transcoder


class MP4Transcoder(Transcoder, format_name="mp4"):
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
            # thumbnail_write_location = write_location.with_suffix(".jpg")
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

            self.transcode_to_mp4(
                mediafile,
                download_location,
                write_location,
                # thumbnail_write_location,
                headers,
            )
            self.storage.upload_transcode(
                mediafile,
                write_location.name,
                write_location,
                headers,
                parent_job_id,
                ignore_duplicate_check=ignore_duplicate_check,
            )
            # self.storage.upload_thumbnail(
            #     mediafile,
            #     thumbnail_write_location.name,
            #     thumbnail_write_location,
            #     headers,
            #     parent_job_id,
            #     ignore_duplicate_check=ignore_duplicate_check,
            # )

    def transcode_to_mp4(
        self,
        mediafile,
        read_location: Path,
        write_location: Path,
        # thumbnail_write_location: Path,
        headers=None,
    ):
        self.add_width_height(mediafile, read_location, headers)

        c = Converter()
        info = c.probe(str(read_location))
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
                AAC_SUPPORTED_SAMPLERATES,
                key=lambda x: abs(x - source_rate),
            )

            opts["audio"] = {
                "codec": "aac",
                "samplerate": closest_rate,
                "channels": info.audio.audio_channels,
            }
        for _ in c.convert(str(read_location), str(write_location), opts, timeout=0):
            pass

        # c.thumbnail(str(write_location), 0, str(thumbnail_write_location))

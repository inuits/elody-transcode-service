import tempfile
from pathlib import Path

import pyvips
from app import app
from elody_types import MediafileEntity

from .transcoder import Transcoder


class PTIFFTranscoder(Transcoder, format_name="ptiff"):
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
            temp_dir_path = Path(temp_dir)
            original_filename_as_path = Path(mediafile["original_filename"])
            download_location = temp_dir_path / mediafile["filename"]

            write_location = (
                temp_dir_path
                / f"{original_filename_as_path.parent / original_filename_as_path.stem}.tif"
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

            try:
                self.transcode_to_ptiff(
                    mediafile,
                    str(download_location),
                    str(write_location),
                    headers,
                )
                app.logger.info("Finished transcoding to PTIFF")
            except Exception as e:
                app.logger.exception(e, stack_info=True)
                raise

            self.storage.upload_transcode(
                mediafile,
                write_location.name,
                write_location,
                headers,
                parent_job_id,
                ignore_duplicate_check=ignore_duplicate_check,
            )

    def transcode_to_ptiff(
        self, mediafile, read_location: str, write_location: str, headers=None
    ):
        self.add_width_height(mediafile, Path(read_location), headers)

        image = pyvips.Image.new_from_file(read_location)

        if image.format in ("ushort", "short", "uint", "int", "float", "double"):
            app.logger.warning(f"Normalizing high-depth mode: {image.format}")
            min_val = image.min()
            max_val = image.max()
            if max_val > min_val:
                scale = 255.0 / (max_val - min_val)
                image = ((image - min_val) * scale).cast("uchar")
            else:
                image = image.cast("uchar")

        image = image.autorot()

        if image.hasalpha():
            image = image.flatten(background=[255, 255, 255])

        if image.interpretation not in ["b-w", "srgb"]:
            image = image.colourspace("srgb")

        image = image.copy()
        artist, copyrights = self._get_exif_for_mediafile(mediafile)

        if artist:
            image.set_type(pyvips.GValue.gstr_type, "exif-ifd0-Artist", artist)
        if copyrights:
            image.set_type(pyvips.GValue.gstr_type, "exif-ifd0-Copyright", copyrights)

        image.tiffsave(
            write_location,
            compression="jpeg",
            Q=75,
            tile=True,
            tile_width=256,
            tile_height=256,
            pyramid=True,
            bigtiff=True,
        )

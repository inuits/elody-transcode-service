import tempfile
from math import floor, sqrt
from pathlib import Path
from typing import Literal, cast

from app import app
from elody_types import MediafileEntity
from PIL import Image, ImageOps, TiffImagePlugin
from PIL.TiffImagePlugin import TiffImageFile

from .transcoder import Transcoder


class JPEGTranscoder(Transcoder, format_name="jpeg"):
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
                / f"{original_filename_as_path.parent / original_filename_as_path.stem}.{operation_name}"
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
                self.transcode_to_jpeg(
                    mediafile,
                    download_location,
                    write_location,
                    headers,
                )

                app.logger.info("Finished download of file")
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

    def transcode_to_jpeg(self, mediafile, read_location, write_location, headers=None):
        self.add_width_height(mediafile, read_location, headers)
        MAX_DIMENSION = 4000
        with Image.open(read_location) as src_img:
            exif = src_img.getexif()
            exif.pop(TiffImagePlugin.STRIPOFFSETS, None)
            artist, copyrights = self._get_exif_for_mediafile(mediafile)
            self._add_artist_and_copyright_to_exif(exif, artist, copyrights)

            if src_img.mode == "P" and src_img.format == "TIFF":
                colormap = cast(TiffImageFile, src_img).tag_v2.get(320)
                if colormap and max(colormap) <= 255:
                    app.logger.warning(
                        "Detected malformed 8-bit TIFF ColorMap. Patching..."
                    )
                    num_colors = len(colormap) // 3
                    fixed_palette = []
                    for i in range(num_colors):
                        r = colormap[i]
                        g = colormap[i + num_colors]
                        b = colormap[i + 2 * num_colors]
                        fixed_palette.extend([r, g, b])
                    src_img.putpalette(fixed_palette)

            if src_img.mode in ("I", "F", "I;16", "I;16B"):
                app.logger.warning(f"Normalizing high-depth mode: {src_img.mode}")
                min_val, max_val = src_img.getextrema()
                if max_val > min_val:
                    scale = 255.0 / (max_val - min_val)
                    src_img = src_img.point(lambda i: (i - min_val) * scale).convert(
                        "L"
                    )
                else:
                    src_img = src_img.convert("L")

            if src_img.mode == "P":
                if "transparency" in src_img.info:
                    src_img = src_img.convert("RGBA")
                else:
                    src_img = src_img.convert("RGB")

            if src_img.mode in ("RGBA", "LA"):
                background = Image.new("RGB", src_img.size, (255, 255, 255))
                background.paste(src_img, mask=src_img.split()[-1])
                src_img = background

            ImageOps.exif_transpose(src_img, in_place=True)

            # if resized_size := self.transcode_resize(src_img.size, MAX_DIMENSION):
            #     src_img.thumbnail(resized_size, Image.Resampling.LANCZOS)
            with src_img.convert("RGB") as dst_img:
                try:
                    dst_img.save(
                        write_location,
                        quality=75,
                        optimize=True,
                        progressive=True,
                        exif=exif,
                    )
                except Exception as ex:  # noqa: BLE001
                    exif.clear()
                    self._add_artist_and_copyright_to_exif(exif, artist, copyrights)
                    dst_img.save(
                        write_location,
                        quality=75,
                        optimize=True,
                        progressive=True,
                        exif=exif,
                    )
                    app.logger.info(f"First conversion failed with: {ex}")

    def transcode_resize(
        self, src_imag_size: tuple, max_size: int
    ) -> Literal[False] | tuple:
        """
        If the transcode has a total pixels <= max_size**2 it is fine, and we should not resize
        Otherwise, to get to max pixels we need to multiply total_pixels * max_pixels/total_pixels
        This means we need to multiply each dimension of the image by the square_root

        Let's say max = 200 -> max_pixels = 40000, and we have an image of 400*400 = 160000.
        40000 / 160000 = 1/4
        this means we have to multiply by sqrt(1/4) = 1/2 -> (200,200)
        """
        max_pixels = max_size**2
        total_pixels = src_imag_size[0] * src_imag_size[1]
        if total_pixels <= max_pixels:
            return False
        scale_factor = sqrt(max_pixels / total_pixels)
        return (
            floor(src_imag_size[0] * scale_factor),
            floor(src_imag_size[1] * scale_factor),
        )

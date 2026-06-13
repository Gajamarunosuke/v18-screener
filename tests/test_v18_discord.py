import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sector_heatmap import send_discord_image


class DiscordImageTests(unittest.TestCase):
    def test_posts_png_as_multipart_attachment(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "heatmap.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nsample")

            with patch("urllib.request.urlopen") as urlopen:
                send_discord_image("https://example.test/webhook", image_path)

            request = urlopen.call_args.args[0]
            content_type = request.headers["Content-type"]
            body = request.data
            self.assertIn("multipart/form-data; boundary=", content_type)
            self.assertIn(b'name="payload_json"', body)
            self.assertIn(b'name="files[0]"; filename="heatmap.png"', body)
            self.assertIn(image_path.read_bytes(), body)


if __name__ == "__main__":
    unittest.main()

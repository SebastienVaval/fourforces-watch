"""Classify one local image with Grok via the xAI API (water on road?).

    python -m scripts.classify_image path/to/photo.jpg
"""
import json
import mimetypes
import sys

from dotenv import load_dotenv

load_dotenv()

from detect.grok import classify_image  # noqa: E402

if __name__ == "__main__":
    path = sys.argv[1]
    print(json.dumps(classify_image(open(path, "rb").read(), mimetypes.guess_type(path)[0] or "image/jpeg"), indent=2))

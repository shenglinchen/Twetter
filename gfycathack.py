"""Quick hack to determine HD mp4 download link for a gfycat video."""

import requests
from bs4 import BeautifulSoup


def get_gfycat_mp4_download_url(media_url, logger):
    """Actual hack method."""
    response = requests.get(media_url)
    logger.debug('Response code %s for: %s' % (response.status_code, media_url))
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'lxml')
    mp4_url = ""
    for tag in soup.find_all("source", src=True):
        src = tag['src']
        if "giant" in src:
            if "mp4" in src:
                mp4_url = src

    return mp4_url
